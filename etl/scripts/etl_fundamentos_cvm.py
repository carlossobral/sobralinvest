import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

# Mapeamento robusto usando Regex para lidar com a bagunça da CVM
MAPEAMENTO_CONTAS = {
    'receita_liquida': r'(?i)receita.l.quida|receita.de.vendas|receita.operacional.l.quida',
    'lucro_bruto': r'(?i)lucro.bruto|resultado.bruto',
    'ebit': r'(?i)lucro.antes.do.resultado.financeiro|resultado.operacional|lucro.operacional|ebit',
    'lucro_liquido': r'(?i)lucro.l.quido.do.exerc.cio|lucro.l.quido.atribu',
    'ativo_total': r'(?i)total.do.ativo|ativo.total',
    'ativo_circulante': r'(?i)ativo.circulante(?!.*n.o.circulante)',
    'passivo_circulante': r'(?i)passivo.circulante(?!.*n.o.circulante)',
    'patrimonio_liquido': r'(?i)patrim.nio.l.quido.consolidado|patrim.nio.l.quido',
    'caixa': r'(?i)caixa.e.equivalentes|disponibilidades',
    'divida_bruta': r'(?i)debentures|empr.stimos.e.financiamentos'
}

def registrar_carga(status, registros, mensagem):
    supabase.table("etl_cargas").insert({
        "processo": "etl_fundamentos_cvm",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status, "registros": registros, "mensagem": mensagem
    }).execute()

def baixar_e_ler_cvm(ano, tipo):
    """Baixa o ZIP da CVM e retorna DataFrames de DRE, BPA e BPP"""
    url_base = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS"
    url = f"{url_base}/{tipo.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: return None
        
        dfs = {'DRE': [], 'BPA': [], 'BPP': []}
        with ZipFile(BytesIO(r.content)) as z:
            for nome in z.namelist():
                if 'CONSOLIDADO' not in nome.upper(): continue
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                if 'DRE' in nome: dfs['DRE'].append(df)
                elif 'BPA' in nome: dfs['BPA'].append(df)
                elif 'BPP' in nome: dfs['BPP'].append(df)
        return {k: pd.concat(v, ignore_index=True) for k, v in dfs.items() if v}
    except Exception as e:
        print(f"Erro ano {ano}: {e}")
        return None

def padronizar_contas(df_dre, df_bpa, df_bpp):
    """Aplica Regex para transformar a bagunça da CVM em colunas fixas"""
    dados_finais = []
    
    # Processa DRE (Acumulado)
    if df_dre is not None:
        for conta_padrao, regex in MAPEAMENTO_CONTAS.items():
            if conta_padrao in ['ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta']:
                continue
            df_filtrado = df_dre[df_dre['DS_CONTA'].str.contains(regex, na=False, regex=True)]
            if not df_filtrado.empty:
                agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
                agg['conta'] = conta_padrao
                dados_finais.append(agg)

    # Processa Balanço (BPA + BPP - Saldo de Fechamento)
    for df_bal, tipo in [(df_bpa, 'BPA'), (df_bpp, 'BPP')]:
        if df_bal is None: continue
        for conta_padrao, regex in MAPEAMENTO_CONTAS.items():
            if tipo == 'BPA' and conta_padrao not in ['ativo_total', 'ativo_circulante', 'caixa']: continue
            if tipo == 'BPP' and conta_padrao not in ['passivo_circulante', 'patrimonio_liquido', 'divida_bruta']: continue
            
            df_filtrado = df_bal[df_bal['DS_CONTA'].str.contains(regex, na=False, regex=True)]
            if not df_filtrado.empty:
                agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
                agg['conta'] = conta_padrao
                dados_finais.append(agg)

    if not dados_finais: return pd.DataFrame()
    
    df_final = pd.concat(dados_finais)
    # Pivot: 1 linha por empresa/data, colunas = contas contábeis
    df_pivot = df_final.pivot_table(
        index=['CD_CVM', 'DT_REFER'], 
        columns='conta', 
        values='VL_CONTA', 
        aggfunc='sum'
    ).reset_index()
    
    return df_pivot

def main():
    print("🔄 Buscando de/para CD_CVM -> Ticker...")
    emp_data = supabase.table("empresas").select("ticker, cd_cvm").execute().data
    mapa_cvm = {str(e['cd_cvm']): e['ticker'] for e in emp_data if e.get('cd_cvm')}
    
    if not mapa_cvm:
        print("❌ Tabela empresas não tem cd_cvm populado. Rode o etl_empresas primeiro.")
        return

    anos = range(2018, datetime.now().year + 1) # Últimos 6 anos
    total_inseridos = 0
    
    try:
        for ano in anos:
            print(f"\n📊 Processando {ano}...")
            # DFP (Anual)
            dados_dfp = baixar_e_ler_cvm(ano, 'DFP')
            if dados_dfp:
                df_pivot = padronizar_contas(dados_dfp.get('DRE'), dados_dfp.get('BPA'), dados_dfp.get('BPP'))
                if not df_pivot.empty:
                    df_pivot['ticker'] = df_pivot['CD_CVM'].astype(str).map(mapa_cvm)
                    df_pivot = df_pivot.dropna(subset=['ticker'])
                    df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
                    df_pivot['trimestre'] = 4 # DFP é consolidado anual
                    df_pivot['data_referencia'] = df_pivot['DT_REFER']
                    
                    cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 'ebit', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta']
                    df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].copy()
                    df_final['divida_liquida'] = df_final.get('divida_bruta', 0) - df_final.get('caixa', 0)
                    
                    # Upsert em Fundamentos Anuais e Trimestrais
                    registros = df_final.replace({np.nan: None}).to_dict('records')
                    if registros:
                        supabase.table("fundamentos_anuais").upsert(registros, on_conflict="ticker,ano").execute()
                        supabase.table("fundamentos_trimestrais").upsert(registros, on_conflict="ticker,ano,trimestre").execute()
                        total_inseridos += len(registros)
                        print(f"  ✅ DFP {ano}: {len(registros)} empresas")

            # ITR (Trimestral)
            dados_itr = baixar_e_ler_cvm(ano, 'ITR')
            if dados_itr:
                df_pivot = padronizar_contas(dados_itr.get('DRE'), dados_itr.get('BPA'), dados_itr.get('BPP'))
                if not df_pivot.empty:
                    df_pivot['ticker'] = df_pivot['CD_CVM'].astype(str).map(mapa_cvm)
                    df_pivot = df_pivot.dropna(subset=['ticker'])
                    df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
                    df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
                    df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
                    df_pivot = df_pivot.dropna(subset=['trimestre'])
                    df_pivot['data_referencia'] = df_pivot['DT_REFER']
                    
                    cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 'ebit', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta']
                    df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].copy()
                    df_final['divida_liquida'] = df_final.get('divida_bruta', 0) - df_final.get('caixa', 0)
                    
                    registros = df_final.replace({np.nan: None}).to_dict('records')
                    if registros:
                        supabase.table("fundamentos_trimestrais").upsert(registros, on_conflict="ticker,ano,trimestre").execute()
                        total_inseridos += len(registros)
                        print(f"  ✅ ITR {ano}: {len(registros)} empresas")
                        
        registrar_carga("SUCESSO", total_inseridos, "Fundamentos CVM consolidados")
        print(f"\n🏆 CONCLUÍDO! {total_inseridos} registros inseridos em fundamentos_trimestrais/anuais.")
        
    except Exception as e:
        registrar_carga("ERRO", 0, str(e))
        raise e

if __name__ == "__main__":
    main()
