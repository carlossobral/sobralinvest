import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

ANO_INICIAL = 2025
ANO_FINAL = datetime.now().year

# Contas validadas
MAPEAMENTO_DRE = {
    'receita_liquida': r'^3\.01$',
    'custo':           r'^3\.02$',
    'ebit':            r'^3\.05$',
}

# CORREÇÃO: Removido 'caixa' do MAPEAMENTO_BPA (agora usa função específica com prioridade)
MAPEAMENTO_BPA = {
    'ativo_total':      r'^1$',
    'ativo_circulante': r'^1\.01$',
}

# CORREÇÃO: Dívida Bruta captura apenas 2.02.01 e 2.02.02 (Empréstimos e Debêntures)
MAPEAMENTO_BPP = {
    'passivo_circulante': r'^2\.01$',
    'divida_bruta':       r'^2\.02\.0[12]',
    'passivo_total':      r'^2$',
}

COLUNAS_DRE = ['receita_liquida', 'custo', 'lucro_bruto', 'ebit', 'ebitda', 'lucro_liquido']
COLUNAS_BAL = ['ativo_total', 'ativo_circulante', 'passivo_circulante',
               'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida', 'passivo_total']


def registrar_carga(status, registros, mensagem):
    try:
        supabase.table("etl_cargas").insert({
            "processo": "etl_fundamentos_cvm",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }).execute()
    except Exception as e:
        print(f"Erro ao registrar carga: {e}")


def obter_dados_empresas():
    print("Buscando empresas...")
    data = (
        supabase.table("empresas")
        .select("ticker, cd_cvm, quantidade_acoes")
        .not_.is_("cd_cvm", "null")
        .execute()
        .data
    )

    mapa_tickers, mapa_acoes = {}, {}
    for e in data:
        if e.get('cd_cvm'):
            key = str(int(float(e['cd_cvm'])))
            mapa_tickers[key] = e['ticker']
            mapa_acoes[key] = int(e['quantidade_acoes']) if e.get('quantidade_acoes') else None

    print(f"  {len(mapa_tickers)} tickers mapeados.")
    return mapa_tickers, mapa_acoes


def extrair_lucro_liquido(df):
    df311 = df[df['CD_CONTA'].str.fullmatch(r'^3\.11$', na=False)].copy()
    df309 = df[df['CD_CONTA'].str.fullmatch(r'^3\.09$', na=False)].copy()

    df311_agg = df311.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
    df311_agg.columns = ['CD_CVM', 'DT_REFER', 'lucro_liquido']

    df309_agg = df309.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
    df309_agg.columns = ['CD_CVM', 'DT_REFER', 'lucro_liquido_309']

    merged = df311_agg.merge(df309_agg, on=['CD_CVM', 'DT_REFER'], how='outer')
    merged['lucro_liquido'] = merged['lucro_liquido'].combine_first(merged['lucro_liquido_309'])
    return merged[['CD_CVM', 'DT_REFER', 'lucro_liquido']].set_index(['CD_CVM', 'DT_REFER'])


def extrair_caixa(df):
    """
    CORREÇÃO CRÍTICA: Extrai caixa com prioridade para evitar dupla contagem.
    
    Prioridade 1: Conta exata 1.01.01 (Caixa e Equivalentes de Caixa)
                  Existe em 99,5% das empresas (427 de 429)
    
    Prioridade 2: Se não existir, soma as subcontas 1.01.01.*
                  (apenas para os 0,5% restantes)
    """
    df = df.copy()
    df['CD_CONTA_STR'] = df['CD_CONTA'].astype(str).str.strip()
    
    # PRIORIDADE 1: Conta exata 1.01.01
    df_mae = df[df['CD_CONTA_STR'] == '1.01.01'].copy()
    
    if not df_mae.empty:
        # Agrega por empresa e data, pegando o primeiro valor
        agg = df_mae.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        agg.columns = ['CD_CVM', 'DT_REFER', 'caixa']
        return agg.set_index(['CD_CVM', 'DT_REFER'])
    
    # PRIORIDADE 2: Se não existir 1.01.01, soma as subcontas 1.01.01.*
    df_filhas = df[df['CD_CONTA_STR'].str.startswith('1.01.01.', na=False)].copy()
    
    if not df_filhas.empty:
        # Soma todas as subcontas
        agg = df_filhas.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
        agg.columns = ['CD_CVM', 'DT_REFER', 'caixa']
        return agg.set_index(['CD_CVM', 'DT_REFER'])
    
    # PRIORIDADE 3: Se não existir nada, retorna DataFrame vazio
    return pd.DataFrame()


def extrair_patrimonio_liquido(df):
    """
    Extrai PL com lógica simplificada:
    - 2.03: verifica descrição (empresas normais)
    - 2.08, 2.07, 2.07.01+2.07.02: NÃO verifica descrição (sempre PL em bancos)
    """
    df = df.copy()
    df['CD_CONTA_STR'] = df['CD_CONTA'].astype(str).str.strip()
    
    resultados = []
    
    # PASSO 1: 2.03 COM verificação de descrição (empresas normais)
    mask_pl_desc = (
        df['DS_CONTA'].astype(str).str.contains('patrimonio', case=False, na=False) |
        df['DS_CONTA'].astype(str).str.contains('patrimônio', case=False, na=False)
    )
    mask_203 = (df['CD_CONTA_STR'] == '2.03') & mask_pl_desc
    if df[mask_203].shape[0] > 0:
        res = df[mask_203].groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        res['prioridade'] = 1
        resultados.append(res)
    
    # PASSO 2: 2.08 SEM verificação de descrição (bancos grandes como ITUB4)
    mask_208 = df['CD_CONTA_STR'] == '2.08'
    if df[mask_208].shape[0] > 0:
        res = df[mask_208].groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        res['prioridade'] = 2
        resultados.append(res)
    
    # PASSO 3: 2.07 SEM verificação de descrição (bancos médios)
    mask_207 = df['CD_CONTA_STR'] == '2.07'
    if df[mask_207].shape[0] > 0:
        res = df[mask_207].groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        res['prioridade'] = 3
        resultados.append(res)
    
    # PASSO 4: 2.07.01 + 2.07.02 SEM verificação de descrição (soma)
    mask_sub = df['CD_CONTA_STR'].isin(['2.07.01', '2.07.02'])
    if df[mask_sub].shape[0] > 0:
        res = df[mask_sub].groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
        res['prioridade'] = 4
        resultados.append(res)
    
    if not resultados:
        return pd.DataFrame()
    
    df_pl = pd.concat(resultados, ignore_index=True)
    df_pl = df_pl.sort_values(['CD_CVM', 'DT_REFER', 'prioridade'])
    df_pl = df_pl.drop_duplicates(subset=['CD_CVM', 'DT_REFER'], keep='first')
    
    return df_pl[['CD_CVM', 'DT_REFER', 'VL_CONTA']].rename(columns={'VL_CONTA': 'patrimonio_liquido'}).set_index(['CD_CVM', 'DT_REFER'])


def extrair_divida_bruta(df):
    """
    Extrai Dívida Bruta do BPP.
    Soma apenas contas de dívida financeira real:
    - 2.02.01: Empréstimos e Financiamentos
    - 2.02.02: Debêntures
    
    NÃO inclui:
    - 2.02.03: Tributos Diferidos
    - 2.02.04: Provisões
    - 2.02.05: Passivos sobre Ativos Não-Correntes
    - 2.02.06: Lucros e Receitas a Apropriar
    """
    df = df.copy()
    df['CD_CONTA_STR'] = df['CD_CONTA'].astype(str).str.strip()
    
    # Filtra apenas contas de dívida financeira real
    mask_divida = (
        df['CD_CONTA_STR'].str.startswith('2.02.01', na=False) |
        df['CD_CONTA_STR'].str.startswith('2.02.02', na=False)
    )
    
    df_divida = df[mask_divida].copy()
    
    if df_divida.empty:
        return pd.DataFrame()
    
    # Soma todas as contas de dívida
    agg = df_divida.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
    agg.columns = ['CD_CVM', 'DT_REFER', 'divida_bruta']
    
    return agg.set_index(['CD_CVM', 'DT_REFER'])


def extrair_depreciacao_amortizacao(df):
    """
    CORREÇÃO: D&A - Busca pela descrição da conta, não pelo código.
    Inclui 'deprecia', 'amortiza', 'exaustão' e 'depleção' (para PETR4).
    """
    df = df.copy()
    df['CD_CONTA_STR'] = df['CD_CONTA'].astype(str).str.strip()
    
    # Filtra apenas contas da seção 6.01.01 (ajustes do DFC método indireto)
    df_ajustes = df[df['CD_CONTA_STR'].str.startswith('6.01.01', na=False)].copy()
    
    if df_ajustes.empty:
        return pd.DataFrame()
    
    # Busca pela DESCRIÇÃO que contenha palavras-chave de D&A
    mask_da = (
        df_ajustes['DS_CONTA'].astype(str).str.contains('deprecia', case=False, na=False) |
        df_ajustes['DS_CONTA'].astype(str).str.contains('amortiza', case=False, na=False) |
        df_ajustes['DS_CONTA'].astype(str).str.contains('exaustão', case=False, na=False) |
        df_ajustes['DS_CONTA'].astype(str).str.contains('exaustao', case=False, na=False) |
        df_ajustes['DS_CONTA'].astype(str).str.contains('depleção', case=False, na=False) |
        df_ajustes['DS_CONTA'].astype(str).str.contains('deplecao', case=False, na=False)
    )
    
    df_da = df_ajustes[mask_da].copy()
    
    if df_da.empty:
        return pd.DataFrame()
    
    # Soma TODAS as contas que contêm D&A na descrição
    agg = df_da.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
    agg.columns = ['CD_CVM', 'DT_REFER', 'depreciacao_amortizacao']
    
    # Garante que seja positivo (abs)
    agg['depreciacao_amortizacao'] = agg['depreciacao_amortizacao'].abs()
    
    return agg.set_index(['CD_CVM', 'DT_REFER'])


def processar_csv_dre(df_csv, mapeamento):
    frames = {}
    for conta, regex in mapeamento.items():
        mask = df_csv['CD_CONTA'].astype(str).str.strip().str.fullmatch(regex, na=False)
        sub = df_csv[mask]
        if sub.empty:
            continue
        agg = sub.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        agg.columns = ['CD_CVM', 'DT_REFER', conta]
        frames[conta] = agg.set_index(['CD_CVM', 'DT_REFER'])
    return frames


def processar_ano(ano, tipo_doc, mapa_tickers, mapa_acoes):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"

    try:
        r = httpx.get(url, timeout=180, follow_redirects=True)
        if r.status_code != 200:
            print(f"  {tipo_doc} {ano}: HTTP {r.status_code}")
            return pd.DataFrame()

        resultado = {}

        with ZipFile(BytesIO(r.content)) as z:
            csvs_con = [n for n in z.namelist() if '_con_' in n.lower() and n.endswith('.csv')]

            dre_csv  = [n for n in csvs_con if '_DRE_' in n.upper()]
            bpa_csv  = [n for n in csvs_con if '_BPA_' in n.upper()]
            bpp_csv  = [n for n in csvs_con if '_BPP_' in n.upper()]
            dfc_csv  = [n for n in csvs_con if '_DFC_MI_' in n.upper()]

            # 1. Processar DRE
            for nome in dre_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()

                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']

                frames = processar_csv_dre(df, MAPEAMENTO_DRE)
                for conta, frame in frames.items():
                    if conta not in resultado:
                        resultado[conta] = frame
                    else:
                        resultado[conta] = resultado[conta].combine_first(frame)

                ll = extrair_lucro_liquido(df)
                if 'lucro_liquido' not in resultado:
                    resultado['lucro_liquido'] = ll
                else:
                    resultado['lucro_liquido'] = resultado['lucro_liquido'].combine_first(ll)

            # 2. Processar BPA
            for nome in bpa_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()
                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']
                
                frames = processar_csv_dre(df, MAPEAMENTO_BPA)
                
                # CORREÇÃO: Usar combine_first em vez de sobrescrever
                for conta, frame in frames.items():
                    if conta not in resultado:
                        resultado[conta] = frame
                    else:
                        resultado[conta] = resultado[conta].combine_first(frame)
                
                # CORREÇÃO: Extrair caixa com função específica (prioridade)
                caixa = extrair_caixa(df)
                if not caixa.empty:
                    if 'caixa' not in resultado:
                        resultado['caixa'] = caixa
                    else:
                        resultado['caixa'] = resultado['caixa'].combine_first(caixa)

            # 3. Processar BPP
            for nome in bpp_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()
                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']
                
                frames = processar_csv_dre(df, MAPEAMENTO_BPP)
                
                # CORREÇÃO: Usar combine_first em vez de sobrescrever
                for conta, frame in frames.items():
                    if conta not in resultado:
                        resultado[conta] = frame
                    else:
                        resultado[conta] = resultado[conta].combine_first(frame)
                
                # Extrair Patrimônio Líquido com a lógica robusta de descrição + código
                pl = extrair_patrimonio_liquido(df)
                if not pl.empty:
                    if 'patrimonio_liquido' not in resultado:
                        resultado['patrimonio_liquido'] = pl
                    else:
                        resultado['patrimonio_liquido'] = resultado['patrimonio_liquido'].combine_first(pl)
                
                # CORREÇÃO: Extrair Dívida Bruta apenas de contas de dívida financeira real
                div = extrair_divida_bruta(df)
                if not div.empty:
                    if 'divida_bruta' not in resultado:
                        resultado['divida_bruta'] = div
                    else:
                        resultado['divida_bruta'] = resultado['divida_bruta'].combine_first(div)

            # 4. Processar DFC_MI
            for nome in dfc_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()
                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']
                
                da = extrair_depreciacao_amortizacao(df)
                if not da.empty:
                    if 'depreciacao_amortizacao' not in resultado:
                        resultado['depreciacao_amortizacao'] = da
                    else:
                        resultado['depreciacao_amortizacao'] = resultado['depreciacao_amortizacao'].combine_first(da)

        if not resultado:
            return pd.DataFrame()

        df_final = pd.concat(resultado.values(), axis=1).reset_index()

        # ==========================================================
        # ORDEM DE OPERAÇÕES CORRIGIDA
        # ==========================================================
        
        # 1. Cálculos derivados iniciais (ainda em milhares)
        if 'receita_liquida' in df_final.columns and 'custo' in df_final.columns:
            df_final['lucro_bruto'] = df_final['receita_liquida'] + df_final['custo']

        if 'ebit' in df_final.columns:
            da = df_final.get('depreciacao_amortizacao', pd.Series(0, index=df_final.index)).fillna(0)
            df_final['ebitda'] = df_final['ebit'] + da

        # 2. Escala: Converte TODAS as colunas de DRE e BAL de MILHARES para REAIS
        for col in [c for c in COLUNAS_DRE + COLUNAS_BAL if c in df_final.columns]:
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce') * 1000

        # Escala também a D&A explicitamente
        if 'depreciacao_amortizacao' in df_final.columns:
            df_final['depreciacao_amortizacao'] = pd.to_numeric(df_final['depreciacao_amortizacao'], errors='coerce') * 1000

        # 3. Cálculo da Dívida Líquida (após a escala, usando valores já em reais)
        div = df_final.get('divida_bruta', pd.Series(0, index=df_final.index)).fillna(0)
        cxa = df_final.get('caixa', pd.Series(0, index=df_final.index)).fillna(0)
        df_final['divida_liquida'] = div - cxa
        
        # ==========================================================

        # Mapear ticker
        df_final['CD_CVM_STR'] = df_final['CD_CVM'].astype(str)
        df_final['ticker'] = df_final['CD_CVM_STR'].map(mapa_tickers)
        df_final['quantidade_acoes'] = df_final['CD_CVM_STR'].map(mapa_acoes)
        df_final = df_final.dropna(subset=['ticker'])

        if df_final.empty:
            return pd.DataFrame()

        df_final['DT_REFER'] = pd.to_datetime(df_final['DT_REFER'], errors='coerce')
        df_final['ano'] = df_final['DT_REFER'].dt.year
        df_final['data_referencia'] = df_final['DT_REFER'].dt.strftime('%Y-%m-%d')

        if tipo_doc == 'ITR':
            df_final['trimestre'] = df_final['DT_REFER'].dt.month.map({3: 1, 6: 2, 9: 3})
            df_final = df_final.dropna(subset=['trimestre'])
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        else:
            df_final['trimestre'] = 4

        for col in COLUNAS_DRE:
            if col in df_final.columns:
                df_final[f'{col}_ytd'] = df_final[col]
                df_final = df_final.drop(columns=[col])

        cols_saida = (
            ['ticker', 'ano', 'trimestre', 'data_referencia']
            + [f'{c}_ytd' for c in COLUNAS_DRE if f'{c}_ytd' in df_final.columns]
            + [c for c in COLUNAS_BAL if c in df_final.columns]
            + ['depreciacao_amortizacao']
            + ['quantidade_acoes']
        )

        df_out = df_final[[c for c in cols_saida if c in df_final.columns]].copy()
        df_out['ano'] = df_out['ano'].astype(int)
        df_out['trimestre'] = df_out['trimestre'].astype(int)
        if 'quantidade_acoes' in df_out.columns:
            df_out['quantidade_acoes'] = pd.to_numeric(df_out['quantidade_acoes'], errors='coerce').astype('Int64')

        df_out['fonte'] = tipo_doc
        df_out = df_out.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        return df_out

    except Exception as e:
        print(f"  Erro {tipo_doc} {ano}: {e}")
        return pd.DataFrame()


def calcular_colunas_q(df):
    print("Calculando colunas _q...")
    df = df.sort_values(['ticker', 'ano', 'data_referencia']).reset_index(drop=True)

    for col_base in COLUNAS_DRE:
        col_ytd = f'{col_base}_ytd'
        col_q = f'{col_base}_q'
        if col_ytd not in df.columns:
            continue

        grupo = df['ticker'].astype(str) + '_' + df['ano'].astype(str)
        df[col_q] = df.groupby(grupo)[col_ytd].diff()
        df[col_q] = df[col_q].fillna(df[col_ytd])

    print(f"  {len(df)} registros processados.")
    return df


def main():
    print("Iniciando ETL de fundamentos CVM...")
    mapa_tickers, mapa_acoes = obter_dados_empresas()
    if not mapa_tickers:
        print("Nenhum ticker. Abortando.")
        return

    todos_dfp = []
    todos_itr = []

    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        print(f"\nAno {ano}...")

        df_dfp = processar_ano(ano, 'DFP', mapa_tickers, mapa_acoes)
        if not df_dfp.empty:
            todos_dfp.append(df_dfp)
            print(f"  DFP: {len(df_dfp)} registros")

        df_itr = processar_ano(ano, 'ITR', mapa_tickers, mapa_acoes)
        if not df_itr.empty:
            todos_itr.append(df_itr)
            print(f"  ITR: {len(df_itr)} registros")

    if not todos_dfp and not todos_itr:
        print("Nenhum dado extraído.")
        registrar_carga("ERRO", 0, "Nenhum dado extraído")
        return

    if todos_dfp and todos_itr:
        df_dfp_all = pd.concat(todos_dfp, ignore_index=True)
        df_itr_all = pd.concat(todos_itr, ignore_index=True)
        
        df_dfp_all = df_dfp_all.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        df_itr_all = df_itr_all.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        
        df_final = df_dfp_all.copy()
        
        df_itr_somente = df_itr_all.merge(
            df_dfp_all[['ticker', 'ano', 'trimestre']],
            on=['ticker', 'ano', 'trimestre'],
            how='left',
            indicator=True
        )
        df_itr_somente = df_itr_somente[df_itr_somente['_merge'] == 'left_only'].drop(columns=['_merge'])
        
        print(f"\nPriorização: {len(df_dfp_all)} DFP + {len(df_itr_somente)} ITR (exclusivos)")
        df_final = pd.concat([df_final, df_itr_somente], ignore_index=True)
        
    elif todos_dfp:
        df_final = pd.concat(todos_dfp, ignore_index=True)
    else:
        df_final = pd.concat(todos_itr, ignore_index=True)

    if 'fonte' in df_final.columns:
        df_final = df_final.drop(columns=['fonte'])

    df_final = calcular_colunas_q(df_final)

    df_final = df_final.replace({np.nan: None, pd.NaT: None})
    registros = df_final.to_dict('records')

    print(f"\nSalvando {len(registros)} registros...")
    total = 0
    erros = 0
    for i in range(0, len(registros), 100):
        try:
            supabase.table("fundamentos_trimestrais").upsert(
                registros[i:i + 100],
                on_conflict="ticker,ano,trimestre"
            ).execute()
            total += len(registros[i:i + 100])
        except Exception as e:
            erros += 1
            print(f"  Erro lote {i}: {e}")

    registrar_carga("SUCESSO", total, f"{total} registros, {erros} erros")
    print(f"\n========== FINAL ==========")
    print(f"Registros salvos : {total}")
    print(f"Lotes com erro   : {erros}")


if __name__ == "__main__":
    main()
