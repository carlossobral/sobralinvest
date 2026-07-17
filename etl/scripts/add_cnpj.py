import pandas as pd
import re
from pathlib import Path
from etl.database.supabase_client import supabase

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj): return None
    return "".join(filter(str.isdigit, str(cnpj))).zfill(14)

def main():
    print("1. Lendo Pasta1.xlsx...")
    xlsx_path = Path("Pasta1.xlsx")
    if not xlsx_path.exists():
        print("❌ Pasta1.xlsx não encontrado.")
        return
        
    df_xlsx = pd.read_excel(xlsx_path)
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    col_codigo = next((c for c in df_xlsx.columns if 'código' in c or 'codigo' in c), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_codigo or not col_cnpj:
        print(f"❌ Colunas não encontradas. Disponíveis: {df_xlsx.columns.tolist()}")
        return
        
    # Mapeamento Ticker -> CNPJ (Split por vírgula, espaço, barra, newline)
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

    print(f"✅ {len(mapa_ticker_cnpj)} tickers mapeados diretamente.")
    
    # Buscar empresas SEM CNPJ no Supabase
    print("\n2. Buscando empresas SEM CNPJ no Supabase...")
    empresas_db = supabase.table("empresas").select("ticker").is_("cnpj", "null").execute().data
    tickers_faltantes = [e['ticker'].upper() for e in empresas_db]
    print(f"Empresas sem CNPJ: {len(tickers_faltantes)}")
    
    registros_update = []
    
    for ticker in tickers_faltantes:
        # 1. Tentativa direta
        if ticker in mapa_ticker_cnpj:
            registros_update.append({"ticker": ticker, "cnpj": mapa_ticker_cnpj[ticker]})
        else:
            # 2. Solução 2: Fallback por Ticker Raiz (4 primeiros caracteres)
            raiz = ticker[:4]
            cnpj_encontrado = None
            for t_map, cnpj in mapa_ticker_cnpj.items():
                if t_map.startswith(raiz):
                    cnpj_encontrado = cnpj
                    break
            
            if cnpj_encontrado:
                registros_update.append({"ticker": ticker, "cnpj": cnpj_encontrado})
                
    print(f"\n3. Atualizando {len(registros_update)} CNPJs via match direto + raiz...")
    
    if not registros_update:
        return
        
    lote = 100
    for i in range(0, len(registros_update), lote):
        supabase.table("empresas").upsert(
            registros_update[i:i+lote], 
            on_conflict="ticker"
        ).execute()
        
    print(f"🏆 CONCLUÍDO! {len(registros_update)} CNPJs atualizados.")

if __name__ == "__main__":
    main()
