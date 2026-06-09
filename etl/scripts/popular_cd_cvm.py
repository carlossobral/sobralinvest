import httpx
import pandas as pd
from io import BytesIO
from pathlib import Path
from etl.database.supabase_client import supabase

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj): return None
    return "".join(filter(str.isdigit, str(cnpj)))

def main():
    print("1. Lendo Pasta1.xlsx para obter CNPJs...")
    xlsx_path = Path("Pasta1.xlsx")
    if not xlsx_path.exists():
        print("❌ Pasta1.xlsx não encontrado na raiz do projeto.")
        return
        
    df_xlsx = pd.read_excel(xlsx_path)
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    col_ticker = next((c for c in df_xlsx.columns if c in ['Empresa', 'código(s)', 'CNPJ', 'ativo']), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_ticker or not col_cnpj:
        print(f"❌ Colunas não encontradas. Disponíveis: {df_xlsx.columns.tolist()}")
        return
        
    df_xlsx['ticker'] = df_xlsx[col_ticker].astype(str).str.strip().str.upper()
    df_xlsx['cnpj'] = df_xlsx[col_cnpj].apply(normalizar_cnpj)
    df_xlsx = df_xlsx.dropna(subset=['cnpj'])
    
    mapa_ticker_cnpj = dict(zip(df_xlsx['ticker'], df_xlsx['cnpj']))
    print(f"✅ {len(mapa_ticker_cnpj)} tickers com CNPJ lidos do Excel.")
    
    print("\n2. Baixando cadastro da CVM (cad_cia_aberta.csv)...")
    url = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)
    r.raise_for_status()
    
    df_cvm = pd.read_csv(BytesIO(r.content), sep=';', encoding='latin1', low_memory=False)
    df_cvm['cnpj'] = df_cvm['CNPJ_CIA'].apply(normalizar_cnpj)
    df_cvm = df_cvm.dropna(subset=['cnpj', 'CD_CVM'])
    
    mapa_cnpj_cdcvm = dict(zip(df_cvm['cnpj'], df_cvm['CD_CVM'].astype(int)))
    print(f"✅ {len(mapa_cnpj_cdcvm)} CNPJs com CD_CVM lidos da CVM.")
    
    print("\n3. Cruzando dados e atualizando Supabase...")
    registros_update = []
    for ticker, cnpj in mapa_ticker_cnpj.items():
        cd_cvm = mapa_cnpj_cdcvm.get(cnpj)
        if cd_cvm:
            registros_update.append({
                "ticker": ticker,
                "cd_cvm": cd_cvm
            })
            
    print(f"✅ {len(registros_update)} empresas encontradas via cruzamento de CNPJ.")
    
    if not registros_update:
        print("Nenhum registro para atualizar.")
        return
        
    lote = 100
    for i in range(0, len(registros_update), lote):
        supabase.table("empresas").upsert(
            registros_update[i:i+lote], 
            on_conflict="ticker"
        ).execute()
        
    print(f"\n🏆 CONCLUÍDO! {len(registros_update)} empresas tiveram o cd_cvm populado.")

if __name__ == "__main__":
    main()
