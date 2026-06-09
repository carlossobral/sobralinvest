import pandas as pd
from pathlib import Path
from etl.database.supabase_client import supabase

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj): return None
    return "".join(filter(str.isdigit, str(cnpj)))

def main():
    print("1. Lendo Pasta1.xlsx...")
    xlsx_path = Path("Pasta1.xlsx")
    if not xlsx_path.exists():
        print("❌ Pasta1.xlsx não encontrado.")
        return
        
    df_xlsx = pd.read_excel(xlsx_path)
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    col_ticker = next((c for c in df_xlsx.columns if 'código' in c or 'codigo' in c), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_ticker or not col_cnpj:
        print(f"❌ Colunas não encontradas. Disponíveis: {df_xlsx.columns.tolist()}")
        return
        
    df_xlsx['ticker'] = df_xlsx[col_ticker].astype(str).str.strip().str.upper()
    df_xlsx['cnpj'] = df_xlsx[col_cnpj].apply(normalizar_cnpj)
    df_xlsx = df_xlsx.dropna(subset=['cnpj'])
    
    mapa_ticker_cnpj = dict(zip(df_xlsx['ticker'], df_xlsx['cnpj']))
    print(f"✅ {len(mapa_ticker_cnpj)} CNPJs lidos do Excel.")
    
    print("\n2. Buscando tickers no Supabase...")
    empresas = supabase.table("empresas").select("ticker").execute().data
    tickers_db = {e['ticker'].upper() for e in empresas}
    
    print("\n3. Atualizando coluna cnpj na tabela empresas...")
    registros_update = []
    for ticker in tickers_db:
        if ticker in mapa_ticker_cnpj:
            registros_update.append({
                "ticker": ticker,
                "cnpj": mapa_ticker_cnpj[ticker]
            })
            
    print(f"✅ {len(registros_update)} empresas encontradas para atualizar.")
    
    if not registros_update:
        return
        
    lote = 100
    for i in range(0, len(registros_update), lote):
        supabase.table("empresas").upsert(
            registros_update[i:i+lote], 
            on_conflict="ticker"
        ).execute()
        
    print(f"\n🏆 CONCLUÍDO! {len(registros_update)} CNPJs atualizados no Supabase.")

if __name__ == "__main__":
    main()
