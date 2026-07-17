from datetime import datetime, UTC
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
import httpx
import pandas as pd
import re
import math
from etl.database.supabase_client import supabase

URL_MFINANCE = "https://mfinance.com.br/api/v1/stocks"
URL_CVM_CADASTRO = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
URL_FRE_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip"

TICKERS_IGNORADOS = {
    # "BIED3",
    # "BRBI11",
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

def limpar_nan(registros):
    """Converte valores NaN do Pandas para None (null no banco)"""
    for r in registros:
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
            # Trata pd.NA caso exista
            try:
                if pd.isna(v):
                    r[k] = None
            except:
                pass
    return registros

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
    print("3. Baixando cadastro CVM (cd_cvm)...")
    try:
        response = httpx.get(URL_CVM_CADASTRO, timeout=120, follow_redirects=True)
        response.raise_for_status()
        
        df_cvm = pd.read_csv(BytesIO(response.content), sep=';', encoding='latin1')
        df_cvm['cnpj'] = df_cvm['CNPJ_CIA'].apply(normalizar_cnpj)
        df_cvm = df_cvm.dropna(subset=['cnpj', 'CD_CVM'])
        df_cvm['cd_cvm'] = df_cvm['CD_CVM'].astype(int)
        
        df_cvm = df_cvm[['cnpj', 'cd_cvm']].drop_duplicates(subset='cnpj')
        print(f"   ✅ {len(df_cvm)} CNPJs mapeados para CD_CVM.")
        return df_cvm
    except Exception as e:
        print(f"   ❌ Erro ao baixar CVM: {e}")
        return pd.DataFrame(columns=['cnpj', 'cd_cvm'])

def buscar_fre_mais_recente():
    ano = datetime.now().year
    while ano >= 2010:
        url = URL_FRE_BASE.format(ano=ano)
        try:
            print(f"   Tentando FRE {ano}...")
            r = httpx.get(url, timeout=300, follow_redirects=True)
            if r.status_code == 200:
                print(f"   ✅ FRE encontrado: {ano}")
                return r.content, ano
        except Exception:
            pass
        ano -= 1
    raise Exception("Nenhum FRE encontrado.")

def carregar_dados_fre():
    print("4. Baixando e processando FRE (Ações Totais e Circulação)...")
    try:
        zip_content, ano = buscar_fre_mais_recente()
        z = ZipFile(BytesIO(zip_content))
        
        capital_file = f"fre_cia_aberta_capital_social_{ano}.csv"
        circulacao_file = f"fre_cia_aberta_distribuicao_capital_{ano}.csv"
        
        df_capital = pd.read_csv(z.open(capital_file), sep=";", encoding="latin1", low_memory=False)
        df_circ = pd.read_csv(z.open(circulacao_file), sep=";", encoding="latin1", low_memory=False)
        
        df_capital["cnpj"] = df_capital["CNPJ_Companhia"].apply(normalizar_cnpj)
        capital = (
            df_capital.groupby("cnpj")["Quantidade_Total_Acoes"]
            .sum()
            .reset_index()
            .rename(columns={"Quantidade_Total_Acoes": "qtd_acoes_totais"})
        )
        
        df_circ["cnpj"] = df_circ["CNPJ_Companhia"].apply(normalizar_cnpj)
        circulacao = (
            df_circ.groupby("cnpj")["Quantidade_Total_Acoes_Circulacao"]
            .sum()
            .reset_index()
            .rename(columns={"Quantidade_Total_Acoes_Circulacao": "qtd_acoes_circulacao"})
        )
        
        df_fre = capital.merge(circulacao, on="cnpj", how="left")
        print(f"   ✅ {len(df_fre)} registros de capital social encontrados.")
        return df_fre
    except Exception as e:
        print(f"   ❌ Erro no FRE: {e}")
        return pd.DataFrame(columns=['cnpj', 'qtd_acoes_totais', 'qtd_acoes_circulacao'])

def main():
    try:
        df_mfinance = buscar_mfinance()
        df_cnpj, mapa_ticker_cnpj = buscar_cnpj_xlsx()
        df_cvm = buscar_cadastro_cvm()
        df_fre = carregar_dados_fre()
        
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
        
        # Merge com CVM (cd_cvm)
        df_final = df_final.merge(df_cvm, on="cnpj", how="left")
        
        # Merge com FRE (Totais e Circulação)
        df_final = df_final.merge(df_fre, on="cnpj", how="left")
        
        # ==========================================
# TRATAMENTO FINAL DOS DADOS
# ==========================================

print("6. Calculando Free Float...")

df_final["qtd_acoes_totais"] = pd.to_numeric(
    df_final["qtd_acoes_totais"],
    errors="coerce"
)

df_final["qtd_acoes_circulacao"] = pd.to_numeric(
    df_final["qtd_acoes_circulacao"],
    errors="coerce"
)

df_final["pct_free_float"] = (
    df_final["qtd_acoes_circulacao"]
    / df_final["qtd_acoes_totais"]
) * 100

# ==========================================
# AJUSTE DOS TIPOS
# ==========================================

# cd_cvm precisa ser inteiro de verdade
if "cd_cvm" in df_final.columns:
    df_final["cd_cvm"] = (
        pd.to_numeric(
            df_final["cd_cvm"],
            errors="coerce"
        )
        .round(0)
        .astype("Int64")
    )

# quantidade_acoes do MFinance
if "quantidade_acoes" in df_final.columns:
    df_final["quantidade_acoes"] = (
        pd.to_numeric(
            df_final["quantidade_acoes"],
            errors="coerce"
        )
        .round(0)
        .astype("Int64")
    )

# FRE
if "qtd_acoes_totais" in df_final.columns:
    df_final["qtd_acoes_totais"] = (
        pd.to_numeric(
            df_final["qtd_acoes_totais"],
            errors="coerce"
        )
        .round(0)
        .astype("Int64")
    )

if "qtd_acoes_circulacao" in df_final.columns:
    df_final["qtd_acoes_circulacao"] = (
        pd.to_numeric(
            df_final["qtd_acoes_circulacao"],
            errors="coerce"
        )
        .round(0)
        .astype("Int64")
    )

# ==========================================
# FILTRO DE IGNORADOS
# ==========================================

print("7. Aplicando filtros (TICKERS_IGNORADOS)...")

df_final = df_final[
    ~df_final["ticker"].isin(TICKERS_IGNORADOS)
].copy()

colunas_finais = [
    "ticker",
    "nome",
    "setor",
    "subsetor",
    "segmento",
    "quantidade_acoes",
    "cnpj",
    "cd_cvm",
    "qtd_acoes_totais",
    "qtd_acoes_circulacao",
    "pct_free_float",
    "ativo",
]

df_final = df_final[colunas_finais]

# ==========================================
# CONVERSÃO SEGURA PARA JSON
# ==========================================

def converter_valor(v):

    if pd.isna(v):
        return None

    # pandas Int64 -> int python
    if isinstance(v, (pd.Int64Dtype,)):
        return int(v)

    # numpy integers
    try:
        import numpy as np

        if isinstance(v, np.integer):
            return int(v)

        if isinstance(v, np.floating):

            if np.isnan(v):
                return None

            return float(v)

    except:
        pass

    return v


registros = []

for _, row in df_final.iterrows():

    registro = {}

    for col in df_final.columns:

        valor = row[col]

        if pd.isna(valor):
            valor = None

        elif str(df_final[col].dtype) == "Int64":
            valor = int(valor)

        registro[col] = valor

    registros.append(registro)

print(f"8. Iniciando Upsert no Supabase ({len(registros)} registros)...")

# DEBUG
print(registros[:3])

# ==========================================
# UPSERT
# ==========================================

lote = 500

for i in range(0, len(registros), lote):

    supabase.table("empresas").upsert(
        registros[i:i + lote],
        on_conflict="ticker"
    ).execute()

mensagem = (
    f"{len(registros)} empresas carregadas "
    f"e atualizadas com sucesso."
)

registrar_carga(
    status="SUCESSO",
    registros=len(registros),
    mensagem=mensagem
)

print(f"✅ CONCLUÍDO! {mensagem}")
