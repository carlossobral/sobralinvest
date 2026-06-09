import pandas as pd
import re
from pathlib import Path
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

ARQUIVO_XLSX = Path("Pasta1.xlsx")

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj):
        return None
    return "".join(filter(str.isdigit, str(cnpj))).zfill(14)

def registrar_carga(status: str, registros: int, mensagem: str):
    try:
        supabase.table("etl_cargas").insert({
            "processo": "popular_cd_cvm",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }).execute()
    except Exception as e:
        print(f"Erro ao registrar carga: {e}")

def main():
    print("1. Lendo Pasta1.xlsx...")
    if not ARQUIVO_XLSX.exists():
        print(f"❌ Arquivo {ARQUIVO_XLSX} não encontrado na raiz.")
        registrar_carga("ERRO", 0, f"Arquivo {ARQUIVO_XLSX} não encontrado")
        return

    df_xlsx = pd.read_excel(ARQUIVO_XLSX)
    df_xlsx.columns = [str(c).strip().lower() for c in df_xlsx.columns]
    
    col_codigo = next((c for c in df_xlsx.columns if 'código' in c or 'codigo' in c), None)
    col_cnpj = next((c for c in df_xlsx.columns if 'cnpj' in c), None)
    
    if not col_codigo or not col_cnpj:
        print(f"❌ Colunas não encontradas. Disponíveis: {df_xlsx.columns.tolist()}")
        registrar_carga("ERRO", 0, f"Colunas não encontradas: {df_xlsx.columns.tolist()}")
        return
        
    print(f"✅ Colunas identificadas: Código='{col_codigo}', CNPJ='{col_cnpj}'")
    
    mapa_ticker_cnpj = {}
    
    for _, row in df_xlsx.iterrows():
        cnpj = normalizar_cnpj(row[col_cnpj])
        if not cnpj:
            continue
            
        codigos_raw = str(row[col_codigo])
        codigos = re.split(r'[,\s;/]+', codigos_raw)
        
        for cod in codigos:
            ticker = cod.strip().upper()
            if ticker and ticker != 'NAN' and len(ticker) >= 4:
                mapa_ticker_cnpj[ticker] = cnpj
                
    print(f"✅ {len(mapa_ticker_cnpj)} tickers mapeados para CNPJs.")
    
    print("\n2. Buscando empresas SEM CNPJ no Supabase...")
    # BUSCAR EMPRESAS QUE NÃO TÊM CNPJ (IS NULL)
    empresas_db = supabase.table("empresas").select("ticker").is_("cnpj", "null").execute().data
    tickers_db = {e['ticker'].upper() for e in empresas_db}
    
    print(f"Empresas sem CNPJ encontradas: {len(tickers_db)}")
    
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
        print("Nenhum registro para atualizar.")
        registrar_carga("SUCESSO", 0, "Nenhum CNPJ atualizado")
        return
        
    lote = 100
    for i in range(0, len(registros_update), lote):
        supabase.table("empresas").upsert(
            registros_update[i:i+lote], 
            on_conflict="ticker"
        ).execute()
        
    print(f"\n🏆 CONCLUÍDO! {len(registros_update)} CNPJs atualizados no Supabase.")
    registrar_carga("SUCESSO", len(registros_update), f"{len(registros_update)} CNPJs atualizados")

if __name__ == "__main__":
    main()
