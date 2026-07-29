from datetime import datetime, UTC
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
import httpx
import pandas as pd
import re
from etl.database.supabase_client import supabase

URL_MFINANCE = "https://mfinance.com.br/api/v1/stocks"
URL_CVM_CADASTRO = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
URL_DFP_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"

TICKERS_IGNORADOS = {
    "AFLT3", "AHEB3", "AHEB5", "AHEB6", "APTI3", "APTI4", "AURA33", "BALM3", 
    "BALM4", "BBML3", "BDLL3", "BDLL4", "BOBR3", "BOBR4", "BRQB3", "CALI3", 
    "CASN3", "CASN4", "CATA3", "CATA4", "CEGR3", "CTAX3", "CTCA3", "CTKA3", 
    "CTKA4", "CTSA3", "CTSA4", "DOHL3", "DOHL4", "DTCY3", "DTCY4", "EALT3", 
    "EALT4", "EKTR3", "EKTR4", "ENMT3", "ENMT4", "EPAR3", "ESTR3", "ESTR4", 
    "FIGE3", "FIGE4", "G2DI33", "GOLL54", "GPAR3", "GSHP3", "HBTS3", "HBTS5", "HBTS6", 
    "HETA3", "HETA4", "HOOT3", "HOOT4", "IGSN3", "JFEN3", "JOPA3", "JOPA4", 
    "LMED3", "LTEL3B", "LUXM3", "LUXM4", "MAPT3", "MAPT4", "MGEL3", "MGEL4", 
    "MMAQ3", "MMAQ4", "MNDL3", "MRSA3B", "MRSA5B", "MRSA6B", "MSPA3", "MSPA4", 
    "MWET3", "MWET4", "NEMO3", "ODER3", "ODER4", "OIBR3", "OIBR4", "OSXB3", 
    "PATI3", "PATI4", "PEAB3", "PEAB4", "PLAS3", "PPAR3", "PPLA11", "PTCA3", 
    "QUSW3", "RPAD3", "RPAD5", "RPAD6", "RPMG3", "RSID3", "SNSY3", "SNSY5", 
    "SNSY6", "SOND3", "SOND5", "SOND6", "TELB3", "TELB4", "TRAD3", "TXRX3", "TXRX4", 
    "VSPT3", "VSPT4", "IBOV"
}

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj): 
        return None
    return "".join(filter(str.isdigit, str(cnpj))).zfill(14)

def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert({
        "processo": "etl_empresas",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status,
        "registros": registros,
        "mensagem": mensagem,
    }).execute()

def buscar_mfinance():
    print("1. Buscando empresas na MFinance...")
    response = httpx.get(URL_MFINANCE, timeout=60)
    response.raise_for_status()
    
    dados = response.json()
    stocks = dados.get("stocks", [])
    
    registros = []
    for item in stocks:
        nome = item.get("name")
        if not nome or str(nome).strip() == "#N/A":
            continue
            
        registros.append({
            "ticker": item.get("symbol"),
            "nome": nome,
            "setor": item.get("sector"),
            "subsetor": item.get("subSector"),
            "segmento": item.get("segment"),
            "quantidade_acoes": item.get("shares"),
            "ativo": True,
        })
        
    print(f"   ✅ {len(registros)} empresas encontradas.")
    return pd.DataFrame(registros)

def buscar_cnpj_xlsx():
    print("2. Lendo Pasta1.xlsx para mapear CNPJs...")
    xlsx_path = Path("Pasta1.xlsx")
    if not xlsx_path.exists():
        print("   ❌ Pasta1.xlsx não encontrado. Pulando etapa de CNPJ.")
        return pd.DataFrame(columns=['ticker', 'cnpj']), {}
        
    df_xlsx = pd.read_excel(xlsx_path)
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    col_codigo = next((c for c in df_xlsx.columns if 'código' in c or 'codigo' in c), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_codigo or not col_cnpj:
        print("   ❌ Colunas não encontradas no xlsx.")
        return pd.DataFrame(columns=['ticker', 'cnpj']), {}
        
    mapa_ticker_cnpj = {}
    for _, row in df_xlsx.iterrows():
        cnpj = normalizar_cnpj(row[col_cnpj])
        if not cnpj: continue
        
        codigos_raw = str(row[col_codigo])
        codigos = re.split(r'[,\s;/\n]+', codigos_raw)
        
        for cod in codigos:
            ticker = cod.strip().upper()
            if ticker and ticker != 'NAN' and len(ticker) >= 4:
                mapa_ticker_cnpj[ticker] = cnpj

    df_cnpj = pd.DataFrame(list(mapa_ticker_cnpj.items()), columns=['ticker', 'cnpj'])
    print(f"   ✅ {len(df_cnpj)} tickers mapeados.")
    return df_cnpj, mapa_ticker_cnpj

def buscar_cadastro_cvm():
    print("3. Baixando cadastro CVM (cd_cvm e data_registro)...")
    try:
        response = httpx.get(URL_CVM_CADASTRO, timeout=120, follow_redirects=True)
        response.raise_for_status()
        
        df_cvm = pd.read_csv(BytesIO(response.content), sep=';', encoding='latin1')
        df_cvm['cnpj'] = df_cvm['CNPJ_CIA'].apply(normalizar_cnpj)
        df_cvm = df_cvm.dropna(subset=['cnpj', 'CD_CVM'])
        df_cvm['cd_cvm'] = df_cvm['CD_CVM'].astype(int)
        
        # Extrai cd_cvm de TODAS as linhas
        df_cd_cvm = df_cvm[['cnpj', 'cd_cvm']].drop_duplicates(subset='cnpj')
        
        # Extrai a data_registro_cvm APENAS das linhas BOLSA/ATIVO
        df_bolsa = df_cvm[(df_cvm["TP_MERC"] == "BOLSA") & (df_cvm["SIT"] == "ATIVO")].copy()
        df_bolsa['data_registro_cvm'] = pd.to_datetime(df_bolsa['DT_REG'], format="%Y-%m-%d", errors="coerce")
        df_bolsa = df_bolsa[['cnpj', 'data_registro_cvm']].drop_duplicates(subset='cnpj')
        
        df_final_cvm = df_cd_cvm.merge(df_bolsa, on='cnpj', how='left')
        
        print(f"   ✅ {len(df_final_cvm)} CNPJs mapeados para CD_CVM e Data Registro.")
        return df_final_cvm
    except Exception as e:
        print(f"   ❌ Erro ao baixar CVM: {e}")
        return pd.DataFrame(columns=['cnpj', 'cd_cvm', 'data_registro_cvm'])

def carregar_dados_dfp():
    print("4. Baixando e processando DFP (Composição de Capital)...")
    try:
        # Baixa DFP do ano atual e do ano anterior para garantir que pegamos todos
        ano_atual = datetime.now().year
        anos_para_buscar = [ano_atual, ano_atual - 1]
        
        dfs = []
        
        for ano in anos_para_buscar:
            url = URL_DFP_BASE.format(ano=ano)
            try:
                print(f"   Tentando DFP {ano}...")
                r = httpx.get(url, timeout=300, follow_redirects=True)
                if r.status_code == 200:
                    print(f"   ✅ DFP {ano} encontrado.")
                    z = ZipFile(BytesIO(r.content))
                    # O arquivo dentro do zip segue o padrão dfp_cia_aberta_composicao_capital_{ano}.csv
                    capital_file = f"dfp_cia_aberta_composicao_capital_{ano}.csv"
                    
                    if capital_file in z.namelist():
                        df_cap = pd.read_csv(z.open(capital_file), sep=";", encoding="latin1", low_memory=False)
                        dfs.append(df_cap)
                    else:
                        print(f"   Arquivo {capital_file} não encontrado no zip do DFP {ano}.")
                elif r.status_code == 404:
                    print(f"   DFP {ano} não disponível (404).")
            except Exception as e:
                print(f"   Erro ao baixar DFP {ano}: {e}")
                
        if not dfs:
            raise Exception("Nenhum arquivo DFP de composição de capital foi encontrado.")

        df_completo = pd.concat(dfs, ignore_index=True)
        
        # Filtra apenas colunas necessárias
        # As colunas no DFP são: CNPJ_CIA, DT_REFER, VERSAO, DENOM_CIA, TP_DOC, etc...
        # Filtra apenas colunas necessárias
        col_cnpj = 'CNPJ_CIA'
        col_data = 'DT_REFER'
        col_total = 'QT_ACAO_TOTAL_CAP_INTEGR' # Total de Ações
        col_tesouraria = 'QT_ACAO_TOTAL_TESOURO' # Ações em Tesouraria (com 'O' no final!)
        
        # Se as colunas não baterem exatamente, tenta achar pelo nome parecido
        if col_total not in df_completo.columns:
            for c in df_completo.columns:
                if 'TOTAL' in c and 'CAP' in c and 'INTEGR' in c:
                    col_total = c
                if 'TOTAL' in c and 'TESOURO' in c: # Corrigido para TESOURO
                    col_tesouraria = c

        df_completo = df_completo[[col_cnpj, col_data, col_total, col_tesouraria]].copy()
        df_completo.columns = ['cnpj', 'data_referencia', 'qtd_acoes_totais', 'qtd_acoes_tesouraria']
        
        # Limpeza
        df_completo['cnpj'] = df_completo['cnpj'].apply(normalizar_cnpj)
        df_completo['data_referencia'] = pd.to_datetime(df_completo['data_referencia'], errors='coerce')
        df_completo['qtd_acoes_totais'] = pd.to_numeric(df_completo['qtd_acoes_totais'], errors='coerce')
        df_completo['qtd_acoes_tesouraria'] = pd.to_numeric(df_completo['qtd_acoes_tesouraria'], errors='coerce').fillna(0)
        
        # Ordena por data e remove duplicadas, ficando com a mais recente
        df_completo = df_completo.sort_values(by=['cnpj', 'data_referencia'], ascending=[True, False])
        df_completo = df_completo.drop_duplicates(subset=['cnpj'], keep='first')
        
        # Calcula Ações em Circulação
        df_completo['qtd_acoes_circulacao'] = df_completo['qtd_acoes_totais'] - df_completo['qtd_acoes_tesouraria']
        
        print(f"   ✅ {len(df_completo)} registros de composição de capital processados.")
        return df_completo
        
    except Exception as e:
        print(f"   ❌ Erro no DFP: {e}")
        return pd.DataFrame(columns=['cnpj', 'qtd_acoes_totais', 'qtd_acoes_circulacao'])

def main():
    try:
        df_mfinance = buscar_mfinance()
        df_cnpj, mapa_ticker_cnpj = buscar_cnpj_xlsx()
        df_cvm = buscar_cadastro_cvm()
        df_dfp = carregar_dados_dfp()
        
        if df_mfinance.empty:
            print("❌ MFinance vazio. Abortando.")
            return
            
        print("5. Unificando DataFrames...")
        # Merge MFinance com CNPJ
        df_final = df_mfinance.merge(df_cnpj, on="ticker", how="left")
        
        # Fallback Ticker Raiz para CNPJs vazios
        missing_cnpj_mask = df_final['cnpj'].isna()
        if missing_cnpj_mask.any() and mapa_ticker_cnpj:
            root_map = {}
            for t, c in mapa_ticker_cnpj.items():
                root = t[:4]
                if root not in root_map:
                    root_map[root] = c
                    
            df_final.loc[missing_cnpj_mask, 'cnpj'] = df_final.loc[missing_cnpj_mask, 'ticker'].apply(
                lambda x: root_map.get(x[:4]) if pd.notna(x) else None
            )
        
        # Merge com CVM (cd_cvm e data_registro_cvm)
        df_final = df_final.merge(df_cvm, on="cnpj", how="left")
        
        # Merge com DFP (Totais e Circulação)
        df_final = df_final.merge(df_dfp, on="cnpj", how="left")
        
        # ==========================================
        # TRATAMENTO FINAL DOS DADOS
        # ==========================================
        print("6. Calculando Free Float e Anos de Listagem...")
        
        # Cálculo do Free Float
        df_final["qtd_acoes_totais"] = pd.to_numeric(df_final["qtd_acoes_totais"], errors="coerce")
        df_final["qtd_acoes_circulacao"] = pd.to_numeric(df_final["qtd_acoes_circulacao"], errors="coerce")
        df_final["pct_free_float"] = (df_final["qtd_acoes_circulacao"] / df_final["qtd_acoes_totais"]) * 100
        
        # Cálculo dos Anos de Listagem
        hoje = pd.Timestamp.now()
        df_final["anos_listagem"] = ((hoje - df_final["data_registro_cvm"]).dt.days // 365).astype("Int64")
        
        # Ajuste dos tipos para Int64 (nullable do pandas) para evitar virar float no JSON
        for col in ["cd_cvm", "quantidade_acoes", "qtd_acoes_totais", "qtd_acoes_circulacao", "anos_listagem"]:
            if col in df_final.columns:
                df_final[col] = pd.to_numeric(df_final[col], errors="coerce").round(0).astype("Int64")
        
        print("7. Aplicando filtros (TICKERS_IGNORADOS)...")
        df_final = df_final[~df_final["ticker"].isin(TICKERS_IGNORADOS)].copy()
        
        colunas_finais = [
            "ticker", "nome", "setor", "subsetor", "segmento",
            "quantidade_acoes", "cnpj", "cd_cvm", "qtd_acoes_totais",
            "qtd_acoes_circulacao", "pct_free_float", "data_registro_cvm", "anos_listagem", "ativo"
        ]
        df_final = df_final[colunas_finais]
        
        # ==========================================
        # CONVERSÃO SEGURA PARA JSON
        # ==========================================
        registros = []
        for _, row in df_final.iterrows():
            registro = {}
            for col in df_final.columns:
                valor = row[col]
                if pd.isna(valor):
                    valor = None
                elif str(df_final[col].dtype) == "Int64":
                    valor = int(valor)
                elif isinstance(valor, pd.Timestamp):
                    valor = valor.strftime("%Y-%m-%d")
                registro[col] = valor
            registros.append(registro)
            
        print(f"8. Iniciando Upsert no Supabase ({len(registros)} registros)...")
        lote = 500
        for i in range(0, len(registros), lote):
            supabase.table("empresas").upsert(
                registros[i:i+lote], 
                on_conflict="ticker"
            ).execute()
            
        mensagem = f"{len(registros)} empresas carregadas e atualizadas com sucesso."
        registrar_carga(status="SUCESSO", registros=len(registros), mensagem=mensagem)
        print(f"✅ CONCLUÍDO! {mensagem}")
        
    except Exception as e:
        registrar_carga(status="ERRO", registros=0, mensagem=str(e))
        print(f"❌ ERRO FATAL: {e}")
        raise

if __name__ == "__main__":
    main()
