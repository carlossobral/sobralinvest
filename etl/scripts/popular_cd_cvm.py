import pandas as pd
import re
from pathlib import Path
from etl.database.supabase_client import supabase

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj):
        return None
    # Mantém apenas números e garante 14 dígitos com zeros à esquerda
    return "".join(filter(str.isdigit, str(cnpj))).zfill(14)

def main():
    print("1. Lendo Pasta1.xlsx para obter CNPJs...")
    xlsx_path = Path("Pasta1.xlsx")
    if not xlsx_path.exists():
        print("❌ Pasta1.xlsx não encontrado na raiz do projeto.")
        return
        
    df_xlsx = pd.read_excel(xlsx_path)
    # Converter nomes das colunas para minúsculo para facilitar a busca
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    # Buscar colunas de forma robusta (case-insensitive)
    col_ticker = next((c for c in df_xlsx.columns if 'código' in c or 'codigo' in c), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_ticker or not col_cnpj:
        print(f"❌ Colunas não encontradas. Disponíveis: {df_xlsx.columns.tolist()}")
        return
        
    print(f"✅ Colunas encontradas: Ticker='{col_ticker}', CNPJ='{col_cnpj}'")
    
    # Dicionário para mapear Ticker -> CNPJ
    mapa_ticker_cnpj = {}
    
    for _, row in df_xlsx.iterrows():
        cnpj = normalizar_cnpj(row[col_cnpj])
        if not cnpj:
            continue
            
        codigos_raw = str(row[col_ticker])
        # Separar por vírgula, espaço, barra ou ponto e vírgula (ex: "ALPA3, ALPA4" ou "USIM3/USIM5")
        codigos = re.split(r'[,\s;/]+', codigos_raw)
        
        for cod in codigos:
            ticker = cod.strip().upper()
            if ticker and ticker != 'NAN' and len(ticker) >= 4:
                mapa_ticker_cnpj[ticker] = cnpj
                
    print(f"✅ {len(mapa_ticker_cnpj)} tickers mapeados para CNPJs a partir do Excel.")
    
    print("\n2. Buscando tickers existentes no Supabase...")
    empresas_db = supabase.table("empresas").select("ticker").execute().data
    tickers_db = {e['ticker'].upper() for e in empresas_db}
    
    print("\n3. Filtrando e atualizando coluna cnpj na tabela empresas...")
    registros_update = []
    for ticker in tickers_db:
        if ticker in mapa_ticker_cnpj:
            registros_update.append({
                "ticker": ticker,
                "cnpj": mapa_ticker_cnpj[ticker]
            })
            
    print(f"✅ {len(registros_update)} empresas encontradas para atualizar.")
    
    if not registros_update:
        print("Nenhum registro para atualizar.")
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
