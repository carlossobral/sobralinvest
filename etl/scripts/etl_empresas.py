from datetime import datetime, UTC
import httpx
import pandas as pd
from io import BytesIO
from zipfile import ZipFile
from etl.database.supabase_client import supabase

URL_MFINANCE = "https://mfinance.com.br/api/v1/stocks"
URL_FRE_CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta.zip"

def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert({
        "processo": "etl_empresas",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status,
        "registros": registros,
        "mensagem": mensagem,
    }).execute()

def buscar_fre_cvm():
    print("Baixando FRE da CVM...")
    try:
        r = httpx.get(URL_FRE_CVM, timeout=180, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  Erro ao baixar FRE: {e}")
        return pd.DataFrame()

    dfs = []
    with ZipFile(BytesIO(r.content)) as z:
        # Procura todos os CSVs de valor mobiliário dentro do ZIP (ignora pastas)
        files = [n for n in z.namelist() if 'valor_mobiliario' in n.lower() and n.endswith('.csv')]
        
        if not files:
            print("  Nenhum arquivo de valor mobiliário encontrado no FRE.")
            return pd.DataFrame()

        print(f"  Encontrados {len(files)} arquivos de valor mobiliário.")
        
        for f in files:
            df = pd.read_csv(z.open(f), sep=';', encoding='latin1', low_memory=False)
            dfs.append(df)
            
    if not dfs:
        return pd.DataFrame()
    
    df = pd.concat(dfs, ignore_index=True)
    
    # Seleciona colunas relevantes
    cols = ['CNPJ_Companhia', 'Codigo_CVM', 'Data_Referencia', 'Ticker', 'Quantidade_Total_Acoes', 'Percentual_Livre_Circulacao']
    df = df[cols].copy()
    
    # Limpeza
    df['Ticker'] = df['Ticker'].astype(str).str.strip()
    df['Quantidade_Total_Acoes'] = pd.to_numeric(df['Quantidade_Total_Acoes'], errors='coerce')
    df['Percentual_Livre_Circulacao'] = pd.to_numeric(df['Percentual_Livre_Circulacao'], errors='coerce')
    df['Data_Referencia'] = pd.to_datetime(df['Data_Referencia'])
    
    # Ordena por data para pegar o mais recente
    df = df.sort_values('Data_Referencia', ascending=False)
    
    # Remove duplicatas mantendo o mais recente
    df = df.drop_duplicates(subset=['Ticker'], keep='first')
    
    # Calcula qtd_acoes_circulacao
    df['qtd_acoes_circulacao'] = (df['Quantidade_Total_Acoes'] * df['Percentual_Livre_Circulacao'] / 100).fillna(0).astype('Int64')
    
    df = df.rename(columns={
        'CNPJ_Companhia': 'cnpj',
        'Codigo_CVM': 'cd_cvm',
        'Quantidade_Total_Acoes': 'qtd_acoes_totais',
        'Percentual_Livre_Circulacao': 'pct_free_float'
    })
    
    print(f"  {len(df)} tickers encontrados no FRE.")
    return df[['Ticker', 'cnpj', 'cd_cvm', 'qtd_acoes_totais', 'qtd_acoes_circulacao', 'pct_free_float']]

def buscar_mfinance():
    print("Buscando empresas na MFinance...")
    try:
        response = httpx.get(URL_MFINANCE, timeout=60)
        response.raise_for_status()
        
        dados = response.json()
        stocks = dados.get("stocks", [])
        
        registros = []
        ignoradas = 0
        
        for item in stocks:
            nome = item.get("name")
            if not nome or str(nome).strip() == "#N/A":
                ignoradas += 1
                continue
                
            registros.append({
                "ticker": item.get("symbol"),
                "nome": nome,
                "setor": item.get("sector"),
                "subsetor": item.get("subSector"),
                "segmento": item.get("segment"),
                "quantidade_acoes": item.get("shares"), # Fallback
                "ativo": True,
            })
            
        print(f"  {len(registros)} empresas na MFinance. {ignoradas} ignoradas.")
        return pd.DataFrame(registros)
        
    except Exception as e:
        print(f"  Erro MFinance: {e}")
        return pd.DataFrame()

def main():
    print("Iniciando ETL Empresas...")
    
    df_mfinance = buscar_mfinance()
    df_fre = buscar_fre_cvm()
    
    if df_mfinance.empty:
        print("MFinance vazio. Abortando.")
        return
    
    # Merge MFinance com FRE
    if not df_fre.empty:
        df_fre = df_fre.rename(columns={'Ticker': 'ticker'})
        df_merge = df_mfinance.merge(df_fre, on='ticker', how='left')
    else:
        df_merge = df_mfinance.copy()
        for col in ['cnpj', 'cd_cvm', 'qtd_acoes_totais', 'qtd_acoes_circulacao', 'pct_free_float']:
            df_merge[col] = None
    
    # Upsert
    registros = df_merge.to_dict('records')
    
    try:
        supabase.table("empresas").upsert(registros, on_conflict="ticker").execute()
        registrar_carga(
            status="SUCESSO",
            registros=len(registros),
            mensagem=f"{len(registros)} empresas carregadas."
        )
        print(f"✅ {len(registros)} empresas salvas no Supabase.")
    except Exception as e:
        registrar_carga(status="ERRO", registros=0, mensagem=str(e))
        raise

if __name__ == "__main__":
    main()
