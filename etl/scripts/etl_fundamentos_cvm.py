import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

# Regex ajustado baseado nos nomes reais da CVM
MAPEAMENTO = {
    'receita_liquida': r'(?i)receita.de.venda|receita.operacional.bruta|3\.01',
    'lucro_bruto': r'(?i)resultado.bruto|lucro.bruto|3\.03',
    'ebit': r'(?i)resultado.antes.do.resultado.financeiro|resultado.operacional|3\.05',
    'lucro_liquido': r'(?i)consolidado.do.per.odo|lucro.l.quido.do.exerc.cio|3\.11(?!.*atribu)',
    'ativo_total': r'(?i)total.do.ativo|1\.01',
    'ativo_circulante': r'(?i)ativo.circulante(?!.*n.o.circulante)|1\.01',
    'passivo_circulante': r'(?i)passivo.circulante(?!.*n.o.circulante)|2\.01',
    'patrimonio_liquido': r'(?i)patrim.nio.l.quido.consolidado|patrim.nio.l.quido|2\.03',
    'caixa': r'(?i)caixa.e.equivalentes|disponibilidades|1\.01\.01',
    'divida_bruta': r'(?i)debentures|empr.stimos.e.financiamentos|2\.02'
}

def obter_mapa_tickers():
    print("🔄 Buscando mapeamento CD_CVM -> Ticker...")
    emp_data = supabase.table("empresas").select("ticker, cd_cvm").not_.is_("cd_cvm", "null").execute().data
    mapa = {str(int(e['cd_cvm'])): e['ticker'] for e in emp_data if e.get('cd_cvm')}
    print(f"✅ {len(mapa)} tickers mapeados.")
    return mapa

def processar_ano(ano, tipo_doc, mapa_tickers):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: 
            print(f"  ⚠️ Arquivo {ano} {tipo_doc} não encontrado (Status {r.status_code})")
            return []
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            arquivos_consolidados = [n for n in z.namelist() if '_con_' in n.lower() or 'consolidado' in n.lower()]
            
            if not arquivos_consolidados:
                print(f"  ⚠️ Nenhum arquivo consolidado encontrado no ZIP de {ano} {tipo_doc}")
                return []

            for nome in arquivos_consolidados:
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    # Buscar por CD_CONTA ou DS_CONTA
                    df_filtrado = df[
                        df['CD_CONTA'].str.match(regex, na=False) | 
                        df['DS_CONTA'].str.contains(regex, na=False, regex=True)
                    ]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais: 
            return []
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(
            index=['CD_CVM', 'DT_REFER'], 
            columns='conta', 
            values='valor', 
            aggfunc='sum'
        ).reset_index()
        
        df_pivot['CD_CVM_STR'] = df_pivot['CD_CVM'].astype(str)
        df_pivot['ticker'] = df_pivot['CD_CVM_STR'].map(mapa_tickers)
        
        tickers_encontrados = df_pivot['ticker'].notna().sum()
        print(f"   🔍 {tickers_encontrados} tickers mapeados com sucesso no {tipo_doc} {ano}")
        
        df_pivot = df_pivot.dropna(subset=['ticker'])
        
        df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
        df_pivot['data_referencia'] = df_pivot['DT_REFER']
        
        if tipo_doc == 'ITR':
            df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
            df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
            df_pivot = df_pivot.dropna(subset=['trimestre'])
        else:
            df_pivot['trimestre'] = 4
            
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 
                'ebit', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 
                'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta', 
                'divida_liquida']
        
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        
        if 'trimestre' in df_final.columns:
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        if 'ano' in df_final.columns:
            df_final['ano'] = df_final['ano'].astype(int)
            
        return df_final.to_dict('records')
        
    except Exception as e:
        print(f"❌ Erro ano {ano} {tipo_doc}: {e}")
        return []

def main():
    print("🔄 Iniciando carga otimizada de fundamentos (Camada Silver)...")
    mapa_tickers = obter_mapa_tickers()
    
    if not mapa_tickers:
        print("❌ Nenhum ticker com CD_CVM encontrado. Abortando.")
        return

    total_registros = 0
    anos = range(2024, 2025)
    
    for ano in anos:
        print(f"\n📊 Processando {ano}...")
        
        registros_dfp = processar_ano(ano, 'DFP', mapa_tickers)
        if registros_dfp:
            registros_anuais = [{k: v for k, v in reg.items() if k != 'trimestre'} for reg in registros_dfp]
            supabase.table("fundamentos_anuais").upsert(registros_anuais, on_conflict="ticker,ano").execute()
            supabase.table("fundamentos_trimestrais").upsert(registros_dfp, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_dfp)
            print(f"  ✅ DFP {ano}: {len(registros_dfp)} registros")
            
        registros_itr = processar_ano(ano, 'ITR', mapa_tickers)
        if registros_itr:
            supabase.table("fundamentos_trimestrais").upsert(registros_itr, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_itr)
            print(f"  ✅ ITR {ano}: {len(registros_itr)} registros")

    print(f"\n🏆 CONCLUÍDO! {total_registros} registros salvos.")

if __name__ == "__main__":
    main()
