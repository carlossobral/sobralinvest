from datetime import datetime, UTC
from io import BytesIO
import httpx
import pandas as pd
from etl.database.supabase_client import supabase

def normalizar_cnpj(cnpj):
    if pd.isna(cnpj):
        return None
    return "".join(filter(str.isdigit, str(cnpj))).zfill(14)

def main():
    print("1. Baixando cadastro CVM (cad_cia_aberta.csv)...")
    url = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    
    try:
        response = httpx.get(url, timeout=120, follow_redirects=True)
        response.raise_for_status()
        
        df_cvm = pd.read_csv(BytesIO(response.content), sep=';', encoding='latin1')
        df_cvm['cnpj_norm'] = df_cvm['CNPJ_CIA'].apply(normalizar_cnpj)
        df_cvm = df_cvm.dropna(subset=['cnpj_norm', 'CD_CVM'])
        
        mapa_cnpj_cdcvm = dict(zip(df_cvm['cnpj_norm'], df_cvm['CD_CVM'].astype(int)))
        print(f"✅ {len(mapa_cnpj_cdcvm)} CNPJs mapeados para CD_CVM")
        
    except Exception as e:
        print(f"❌ Erro ao baixar CVM: {e}")
        return
    
    print("\n2. Buscando empresas no Supabase...")
    empresas = supabase.table("empresas").select("ticker, cnpj").execute().data
    
    registros_update = []
    for emp in empresas:
        cnpj_emp = normalizar_cnpj(emp.get('cnpj'))
        if cnpj_emp and cnpj_emp in mapa_cnpj_cdcvm:
            registros_update.append({
                "ticker": emp['ticker'],
                "cd_cvm": mapa_cnpj_cdcvm[cnpj_emp]
            })
    
    print(f"\n3. Atualizando {len(registros_update)} empresas com CD_CVM...")
    
    lote = 100
    for i in range(0, len(registros_update), lote):
        supabase.table("empresas").upsert(
            registros_update[i:i+lote],
            on_conflict="ticker"
        ).execute()
    
    print(f"\n🏆 CONCLUÍDO! {len(registros_update)} empresas tiveram o cd_cvm populado.")

if __name__ == "__main__":
    main()
