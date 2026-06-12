import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

ANO_INICIAL = 2019  
ANO_FINAL = datetime.now().year  

# REGEX BLINDADO: Apenas códigos de conta oficiais. 
# Remove fallbacks de texto que causam soma indevida de sub-contas (ex: ITUB4 PL).
MAPEAMENTO = {
    'receita_liquida': r'(?i)^3\.01$|^3\.01\.00$',
    'lucro_bruto': r'(?i)^3\.03$|^3\.03\.00$',
    'ebit': r'(?i)^3\.05$|^3\.05\.00$',
    'depreciacao_amortizacao': r'(?i)^3\.05\.03$|^3\.05\.04$',
    'lucro_liquido': r'(?i)^3\.11$|^3\.11\.00$',
    'ativo_total': r'(?i)^1\.01$|^1\.01\.00$',
    'ativo_circulante': r'(?i)^1\.01\.01$|^1\.01\.01\.00$',
    'passivo_circulante': r'(?i)^2\.01$|^2\.01\.00$',
    'patrimonio_liquido': r'(?i)^2\.03$|^2\.03\.00$', # Apenas o código exato
    'caixa': r'(?i)^1\.01\.01\.01$|^1\.01\.01\.01\.00$',
    'divida_bruta': r'(?i)^2\.02$|^2\.02\.00$'
}

COLUNAS_DRE = ['receita_liquida', 'lucro_bruto', 'ebit', 'ebitda', 'lucro_liquido']
COLUNAS_FINANCEIRAS = COLUNAS_DRE + ['ativo_total', 'ativo_circulante', 'passivo_circulante', 
                                      'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida']

def obter_dados_empresas():
    print("🔄 Buscando dados da tabela empresas...")
    emp_data = supabase.table("empresas").select("ticker, cd_cvm, quantidade_acoes").not_.is_("cd_cvm", "null").execute().data
    
    mapa_tickers, mapa_acoes = {}, {}
    for e in emp_data:
        if e.get('cd_cvm'):
            cd_cvm_str = str(int(e['cd_cvm']))
            mapa_tickers[cd_cvm_str] = e['ticker']
            mapa_acoes[cd_cvm_str] = int(e['quantidade_acoes']) if e.get('quantidade_acoes') else None
            
    print(f"✅ {len(mapa_tickers)} tickers e ações mapeados.")
    return mapa_tickers, mapa_acoes

def processar_ano(ano, tipo_doc, mapa_tickers, mapa_acoes):
    if ano > ANO_FINAL: return pd.DataFrame()

    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: return pd.DataFrame()
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            arquivos_consolidados = [n for n in z.namelist() if '_con_' in n.lower() or 'consolidado' in n.lower()]
            if not arquivos_consolidados: return pd.DataFrame()

            for nome in arquivos_consolidados:
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    # Match estrito no código da conta
                    df_filtrado = df[df['CD_CONTA'].astype(str).str.match(regex, na=False)]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais: return pd.DataFrame()
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(index=['CD_CVM', 'DT_REFER'], columns='conta', values='valor', aggfunc='sum').reset_index()
        
        if 'ebit' in df_pivot.columns and 'depreciacao_amortizacao' in df_pivot.columns:
            df_pivot['ebitda'] = df_pivot['ebit'] + df_pivot['depreciacao_amortizacao']
        elif 'ebit' in df_pivot.columns:
            df_pivot['ebitda'] = df_pivot['ebit']
            
        df_pivot['CD_CVM_STR'] = df_pivot['CD_CVM'].astype(str)
        df_pivot['ticker'] = df_pivot['CD_CVM_STR'].map(mapa_tickers)
        df_pivot['quantidade_acoes'] = df_pivot['CD_CVM_STR'].map(mapa_acoes)
        
        df_pivot = df_pivot.dropna(subset=['ticker'])
        df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
        df_pivot['data_referencia'] = df_pivot['DT_REFER']
        
        if tipo_doc == 'ITR':
            df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
            df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
            df_pivot = df_pivot.dropna(subset=['trimestre'])
        else:
            df_pivot['trimestre'] = 4
            
        # Converter de MILHARES para REAIS
        for col in COLUNAS_FINANCEIRAS:
            if col in df_pivot.columns:
                df_pivot[col] = df_pivot[col] * 1000
                
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        for col in COLUNAS_DRE:
            if col in df_pivot.columns:
                df_pivot[f'{col}_ytd'] = df_pivot[col]
                df_pivot = df_pivot.drop(columns=[col])
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia']
        cols += [f'{col}_ytd' for col in COLUNAS_DRE if f'{col}_ytd' in df_pivot.columns]
        cols += ['ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida', 'quantidade_acoes']
        
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        
        if 'trimestre' in df_final.columns: df_final['trimestre'] = df_final['trimestre'].astype(int)
        if 'ano' in df_final.columns: df_final['ano'] = df_final['ano'].astype(int)
        if 'quantidade_acoes' in df_final.columns: df_final['quantidade_acoes'] = df_final['quantidade_acoes'].astype('Int64')
            
        df_final = df_final.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        return df_final
        
    except Exception as e:
        print(f"❌ Erro ano {ano} {tipo_doc}: {e}")
        return pd.DataFrame()

def calcular_colunas_q(df):
    print("🧮 Calculando colunas _q (desacumulador)...")
    df = df.sort_values(['ticker', 'ano', 'data_referencia']).reset_index(drop=True)
    
    for col_base in COLUNAS_DRE:
        col_ytd = f'{col_base}_ytd'
        col_q = f'{col_base}_q'
        if col_ytd not in df.columns: continue
        
        grupo = df['ticker'].astype(str) + '_' + df['ano'].astype(str)
        df[col_q] = df.groupby(grupo)[col_ytd].diff()
        df[col_q] = df[col_q].fillna(df[col_ytd])
        df.loc[df[col_ytd] < 0, col_q] = np.nan
        df.loc[df[col_ytd] < 0, col_ytd] = np.nan

    print(f"✅ Colunas _q calculadas para {len(df)} registros.")
    return df

def main():
    print("🔄 Iniciando carga de fundamentos (Regex Blindado por Código de Conta)...")
    mapa_tickers, mapa_acoes = obter_dados_empresas()
    if not mapa_tickers: return

    todos_registros = []
    print(f"📅 Processando anos de {ANO_INICIAL} a {ANO_FINAL}...")
    
    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        print(f"\n📊 Processando {ano}...")
        df_dfp = processar_ano(ano, 'DFP', mapa_tickers, mapa_acoes)
        if not df_dfp.empty:
            todos_registros.append(df_dfp)
            print(f"  ✅ DFP {ano}: {len(df_dfp)} registros")
            
        df_itr = processar_ano(ano, 'ITR', mapa_tickers, mapa_acoes)
        if not df_itr.empty:
            todos_registros.append(df_itr)
            print(f"  ✅ ITR {ano}: {len(df_itr)} registros")
    
    if not todos_registros: return
    
    df_consolidado = pd.concat(todos_registros, ignore_index=True)
    df_consolidado = calcular_colunas_q(df_consolidado)
    
    print("💾 Salvando no Supabase...")
    df_consolidado = df_consolidado.replace({np.nan: None, pd.NaT: None})
    registros = df_consolidado.to_dict('records')
    
    total_salvos = 0
    for i in range(0, len(registros), 100):
        supabase.table("fundamentos_trimestrais").upsert(registros[i:i+100], on_conflict="ticker,ano,trimestre").execute()
        total_salvos += len(registros[i:i+100])
    
    print(f"\n🏆 CONCLUÍDO! {total_salvos} registros salvos.")

if __name__ == "__main__":
    main()
