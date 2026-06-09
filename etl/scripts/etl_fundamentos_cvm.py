import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

# Mapeamento robusto para achar as contas na bagunça da CVM
MAPEAMENTO = {
    'receita_liquida': r'(?i)receita.l.quida|receita.de.vendas',
    'lucro_bruto': r'(?i)lucro.bruto|resultado.bruto',
    'ebit': r'(?i)lucro.antes.do.resultado.financeiro|resultado.operacional|ebit',
    'lucro_liquido': r'(?i)lucro.l.quido.do.exerc.cio|lucro.l.quido.atribu',
    'ativo_total': r'(?i)total.do.ativo|ativo.total',
    'ativo_circulante': r'(?i)ativo.circulante(?!.*n.o.circulante)',
    'passivo_circulante': r'(?i)passivo.circulante(?!.*n.o.circulante)',
    'patrimonio_liquido': r'(?i)patrim.nio.l.quido.consolidado|patrim.nio.l.quido',
    'caixa': r'(?i)caixa.e.equivalentes|disponibilidades',
    'divida_bruta': r'(?i)debentures|empr.stimos.e.financiamentos'
}

def processar_ano(ano, tipo_doc):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: return []
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            for nome in z.namelist():
                if 'CONSOLIDADO' not in nome.upper(): continue
                
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    df_filtrado = df[df['DS_CONTA'].str.contains(regex, na=False, regex=True)]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais: return []
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(index=['CD_CVM', 'DT_REFER'], columns='conta', values='valor', aggfunc='sum').reset_index()
        
        # Merge com tickers
        empresas = pd.DataFrame(supabase.table("empresas").select("ticker, cd_cvm").execute().data)
        mapa_cvm = {str(e['cd_cvm']): e['ticker'] for e in empresas if e.get('cd_cvm')}
        
        df_pivot['ticker'] = df_pivot['CD_CVM'].astype(str).map(mapa_cvm)
        df_pivot = df_pivot.dropna(subset=['ticker'])
        df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
        df_pivot['data_referencia'] = df_pivot['DT_REFER']
        
        if tipo_doc == 'ITR':
            df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
            df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
            df_pivot = df_pivot.dropna(subset=['trimestre'])
        else:
            df_pivot['trimestre'] = 4 # DFP é anual
            
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 'ebit', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida']
        return df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None}).to_dict('records')
        
    except Exception as e:
        print(f"Erro ano {ano} {tipo_doc}: {e}")
        return []

def main():
    print("🔄 Iniciando carga leve de fundamentos (sem estourar o banco)...")
    total_registros = 0
    
    # Processa DFP (Anual) e ITR (Trimestral) dos últimos anos
    for ano in range(2018, datetime.now().year + 1):
        print(f"Processando {ano}...")
        
        # DFP
        registros_dfp = processar_ano(ano, 'DFP')
        if registros_dfp:
            supabase.table("fundamentos_anuais").upsert(registros_dfp, on_conflict="ticker,ano").execute()
            supabase.table("fundamentos_trimestrais").upsert(registros_dfp, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_dfp)
            
        # ITR
        registros_itr = processar_ano(ano, 'ITR')
        if registros_itr:
            supabase.table("fundamentos_trimestrais").upsert(registros_itr, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_itr)

    supabase.table("etl_cargas").insert({
        "processo": "etl_fundamentos_cvm",
        "inicio": datetime.now(UTC).isoformat(),
        "status": "SUCESSO",
        "registros": total_registros,
        "mensagem": "Fundamentos agregados carregados"
    }).execute()
    
    print(f"✅ CONCLUÍDO! {total_registros} registros de fundamentos salvos.")

if __name__ == "__main__":
    main()
