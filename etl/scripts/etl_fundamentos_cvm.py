import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

ANO_INICIAL = 2019  
ANO_FINAL = datetime.now().year  

# MAPEAMENTO DEFINITIVO (Validado com arquivos CVM 2025)
# DRE
MAPEAMENTO_DRE = {
    'receita_liquida': r'^3\.01$',      # Receita Líquida (conta raiz, sem subcontas)
    'custo': r'^3\.02$',                # Custo dos Bens/Serviços Vendidos (CMV/CPV/CSV)
    'ebit': r'^3\.05$',                 # Resultado Antes do RF e Tributos (EBIT)
    'lucro_liquido': r'^3\.(09|11)$'    # Lucro Líquido (3.09 para bancos, 3.11 para empresas)
}

# Balanço Patrimonial
MAPEAMENTO_BPA = {
    'ativo_total': r'^1$',              # Ativo Total (conta raiz)
    'ativo_circulante': r'^1\.01$',     # Ativo Circulante
    'caixa': r'^1\.01\.01\.01$'         # Caixa e Equivalentes
}

MAPEAMENTO_BPP = {
    'passivo_circulante': r'^2\.01$',   # Passivo Circulante
    'divida_bruta': r'^2\.02$',         # Dívida Bruta (Empréstimos e Financiamentos)
    'patrimonio_liquido': r'^2\.03$'    # Patrimônio Líquido Consolidado
}

# Combina todos os mapeamentos para DRE/BPA/BPP
MAPEAMENTO = {**MAPEAMENTO_DRE, **MAPEAMENTO_BPA, **MAPEAMENTO_BPP}

# Colunas que precisam ser desacumuladas (DRE)
COLUNAS_DRE = ['receita_liquida', 'custo', 'lucro_bruto', 'ebit', 'ebitda', 'lucro_liquido']

# Colunas financeiras (multiplicadas por 1000)
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

def processar_dfc(ano, tipo_doc, mapa_tickers):
    """
    Processa o arquivo DFC (Demonstração do Fluxo de Caixa - Método Indireto)
    para extrair Depreciação, Amortização e Exaustão.
    """
    if ano > ANO_FINAL:
        return pd.DataFrame()

    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFC_MD/DADOS/dfc_md_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200:
            return pd.DataFrame()
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            arquivos_consolidados = [n for n in z.namelist() if '_con_' in n.lower() or 'consolidado' in n.lower()]
            if not arquivos_consolidados:
                return pd.DataFrame()

            for nome in arquivos_consolidados:
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                # Filtra contas no grupo 6.01.01 que contenham depreciação/amortização/exaustão no nome
                df_filtrado = df[
                    (df['CD_CONTA'].astype(str).str.startswith('6.01.01')) &
                    (df['DS_CONTA'].str.contains(r'(?i)deprecia|amortiza|exaust', na=False))
                ]
                
                if not df_filtrado.empty:
                    agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                    agg['conta'] = 'depreciacao_amortizacao'
                    dados_finais.append(agg)
        
        if not dados_finais:
            return pd.DataFrame()
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(
            index=['CD_CVM', 'DT_REFER'], 
            columns='conta', 
            values='valor', 
            aggfunc='sum'
        ).reset_index()
        
        df_pivot['CD_CVM_STR'] = df_pivot['CD_CVM'].astype(str)
        df_pivot['ticker'] = df_pivot['CD_CVM_STR'].map(mapa_tickers)
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
        df_pivot['depreciacao_amortizacao'] = df_pivot['depreciacao_amortizacao'] * 1000
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'depreciacao_amortizacao']
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        
        if 'trimestre' in df_final.columns:
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        if 'ano' in df_final.columns:
            df_final['ano'] = df_final['ano'].astype(int)
        
        df_final = df_final.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        return df_final
        
    except Exception as e:
        print(f"❌ Erro DFC {ano} {tipo_doc}: {e}")
        return pd.DataFrame()

def processar_ano(ano, tipo_doc, mapa_tickers, mapa_acoes):
    if ano > ANO_FINAL:
        return pd.DataFrame()

    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200:
            return pd.DataFrame()
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            arquivos_consolidados = [n for n in z.namelist() if '_con_' in n.lower() or 'consolidado' in n.lower()]
            if not arquivos_consolidados:
                return pd.DataFrame()

            for nome in arquivos_consolidados:
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    # Match estrito no código da conta (apenas conta raiz, sem subcontas)
                    df_filtrado = df[df['CD_CONTA'].astype(str).str.match(regex, na=False)]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais:
            return pd.DataFrame()
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(
            index=['CD_CVM', 'DT_REFER'], 
            columns='conta', 
            values='valor', 
            aggfunc='sum'
        ).reset_index()
        
        # Calcular Lucro Bruto = Receita Líquida + Custo (custo é negativo)
        if 'receita_liquida' in df_pivot.columns and 'custo' in df_pivot.columns:
            df_pivot['lucro_bruto'] = df_pivot['receita_liquida'] + df_pivot['custo']
        
        # EBITDA será calculado depois, quando integrarmos com o DFC
            
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
            if col in df_pivot.columns and col != 'lucro_bruto':  # lucro_bruto já calculado
                df_pivot[col] = df_pivot[col] * 1000
                
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        # Renomear colunas DRE para _ytd
        for col in COLUNAS_DRE:
            if col in df_pivot.columns:
                df_pivot[f'{col}_ytd'] = df_pivot[col]
                df_pivot = df_pivot.drop(columns=[col])
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia']
        cols += [f'{col}_ytd' for col in COLUNAS_DRE if f'{col}_ytd' in df_pivot.columns]
        cols += ['ativo_total', 'ativo_circulante', 'passivo_circulante', 
                 'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida', 'quantidade_acoes']
        
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        
        if 'trimestre' in df_final.columns:
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        if 'ano' in df_final.columns:
            df_final['ano'] = df_final['ano'].astype(int)
        if 'quantidade_acoes' in df_final.columns:
            df_final['quantidade_acoes'] = df_final['quantidade_acoes'].astype('Int64')
            
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
        if col_ytd not in df.columns:
            continue
        
        grupo = df['ticker'].astype(str) + '_' + df['ano'].astype(str)
        df[col_q] = df.groupby(grupo)[col_ytd].diff()
        df[col_q] = df[col_q].fillna(df[col_ytd])
        df.loc[df[col_ytd] < 0, col_q] = np.nan
        df.loc[df[col_ytd] < 0, col_ytd] = np.nan

    print(f"✅ Colunas _q calculadas para {len(df)} registros.")
    return df

def integrar_dfc(df_dre, df_dfc):
    """
    Integra os dados de Depreciação/Amortização do DFC com o DataFrame principal.
    Calcula EBITDA = EBIT + Depreciação/Amortização
    """
    if df_dfc.empty:
        print("⚠️ Nenhum dado de DFC disponível. EBITDA não será calculado.")
        return df_dre
    
    print("🔗 Integrando dados de DFC (Depreciação/Amortização)...")
    
    # Merge por ticker, ano e trimestre
    df_merged = df_dre.merge(
        df_dfc[['ticker', 'ano', 'trimestre', 'depreciacao_amortizacao']],
        on=['ticker', 'ano', 'trimestre'],
        how='left'
    )
    
    # Calcular EBITDA = EBIT + Depreciação/Amortização
    if 'ebit_ytd' in df_merged.columns and 'depreciacao_amortizacao' in df_merged.columns:
        df_merged['ebitda_ytd'] = df_merged['ebit_ytd'] + df_merged['depreciacao_amortizacao'].fillna(0)
        
        # Também calcular para _q
        if 'ebit_q' in df_merged.columns:
            # Para _q, precisamos calcular a depreciação trimestral
            # Como o DFC é anual, vamos usar o valor anual para o T4 e dividir por 4 para os outros
            # (aproximação conservadora)
            df_merged['depreciacao_amortizacao_q'] = df_merged['depreciacao_amortizacao'] / 4
            df_merged['ebitda_q'] = df_merged['ebit_q'] + df_merged['depreciacao_amortizacao_q'].fillna(0)
    
    dfc_count = df_merged['depreciacao_amortizacao'].notna().sum()
    print(f"✅ {dfc_count} registros integrados com dados de DFC.")
    
    return df_merged

def main():
    print("🔄 Iniciando carga de fundamentos (Mapeamento Definitivo + DFC)...")
    mapa_tickers, mapa_acoes = obter_dados_empresas()
    if not mapa_tickers:
        return

    todos_registros = []
    todos_dfc = []
    print(f"📅 Processando anos de {ANO_INICIAL} a {ANO_FINAL}...")
    
    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        print(f"\n📊 Processando {ano}...")
        
        # Processar DRE/BPA/BPP
        df_dfp = processar_ano(ano, 'DFP', mapa_tickers, mapa_acoes)
        if not df_dfp.empty:
            todos_registros.append(df_dfp)
            print(f"  ✅ DFP {ano}: {len(df_dfp)} registros")
            
        df_itr = processar_ano(ano, 'ITR', mapa_tickers, mapa_acoes)
        if not df_itr.empty:
            todos_registros.append(df_itr)
            print(f"  ✅ ITR {ano}: {len(df_itr)} registros")
        
        # Processar DFC (Método Indireto)
        df_dfc_dfp = processar_dfc(ano, 'DFP', mapa_tickers)
        if not df_dfc_dfp.empty:
            todos_dfc.append(df_dfc_dfp)
            print(f"  ✅ DFC DFP {ano}: {len(df_dfc_dfp)} registros")
            
        df_dfc_itr = processar_dfc(ano, 'ITR', mapa_tickers)
        if not df_dfc_itr.empty:
            todos_dfc.append(df_dfc_itr)
            print(f"  ✅ DFC ITR {ano}: {len(df_dfc_itr)} registros")
    
    if not todos_registros:
        print("❌ Nenhum registro extraído. Abortando.")
        return
    
    # Consolidar dados principais
    df_consolidado = pd.concat(todos_registros, ignore_index=True)
    
    # Consolidar DFC
    if todos_dfc:
        df_dfc_consolidado = pd.concat(todos_dfc, ignore_index=True)
        df_consolidado = integrar_dfc(df_consolidado, df_dfc_consolidado)
    
    # Calcular colunas _q
    df_consolidado = calcular_colunas_q(df_consolidado)
    
    # Adicionar coluna depreciacao_amortizacao_q se existir
    if 'depreciacao_amortizacao' in df_consolidado.columns:
        df_consolidado['depreciacao_amortizacao_ytd'] = df_consolidado['depreciacao_amortizacao']
    
    print("💾 Salvando no Supabase...")
    df_consolidado = df_consolidado.replace({np.nan: None, pd.NaT: None})
    registros = df_consolidado.to_dict('records')
    
    total_salvos = 0
    for i in range(0, len(registros), 100):
        supabase.table("fundamentos_trimestrais").upsert(
            registros[i:i+100], 
            on_conflict="ticker,ano,trimestre"
        ).execute()
        total_salvos += len(registros[i:i+100])
    
    print(f"\n🏆 CONCLUÍDO! {total_salvos} registros salvos.")

if __name__ == "__main__":
    main()
