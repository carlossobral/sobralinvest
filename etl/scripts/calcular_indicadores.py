import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from etl.database.supabase_client import supabase

TAXA_IMPOSTO = 0.34  # IRPJ + CSLL marginal

def buscar_fundamentos():
    """Busca dados anuais consolidados (T4)"""
    print("🔄 Buscando fundamentos anuais (T4)...")
    data = supabase.table("fundamentos_trimestrais").select("*").eq("trimestre", 4).execute().data
    df = pd.DataFrame(data)
    
    cols_numericas = ['receita_liquida', 'lucro_bruto', 'ebit', 'ebitda', 'lucro_liquido', 
                      'ativo_total', 'ativo_circulante', 'passivo_circulante', 'patrimonio_liquido', 
                      'divida_liquida', 'quantidade_acoes']
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    print(f"✅ {len(df)} registros anuais carregados.")
    return df

def buscar_cotacoes():
    """Busca preço atual e volume médio via RPC"""
    print("🔄 Buscando dados de mercado via RPC...")
    try:
        data = supabase.rpc('get_latest_market_data').execute().data
        df = pd.DataFrame(data)
        print(f"✅ {len(df)} cotações mapeadas.")
        return df
    except Exception as e:
        print(f"❌ Erro na RPC: {e}")
        return pd.DataFrame()

def buscar_dividendos():
    """Busca histórico de dividendos e JCP (últimos 7 anos)"""
    print(" Buscando dividendos...")
    data_limite = (datetime.now() - timedelta(days=365 * 7)).strftime('%Y-%m-%d')
    data = supabase.table("dividendos").select("ticker, data_pagamento, valor").gte("data_pagamento", data_limite).execute().data
    df = pd.DataFrame(data)
    df['data_pagamento'] = pd.to_datetime(df['data_pagamento'])
    df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
    print(f"✅ {len(df)} proventos carregados.")
    return df

def calcular_agregacoes_dividendos(df_div):
    """Calcula Dividendos 12m e Média 6 anos"""
    hoje = datetime.now()
    um_ano_atras = hoje - timedelta(days=365)
    seis_anos_atras = hoje - timedelta(days=365 * 6)

    div_12m = df_div[df_div['data_pagamento'] >= um_ano_atras].groupby('ticker')['valor'].sum().reset_index()
    div_12m.columns = ['ticker', 'dividendos_12m']

    div_6a = df_div[df_div['data_pagamento'] >= seis_anos_atras].copy()
    div_6a['ano'] = div_6a['data_pagamento'].dt.year
    soma_anual = div_6a.groupby(['ticker', 'ano'])['valor'].sum().reset_index()
    media_6a = soma_anual.groupby('ticker')['valor'].mean().reset_index()
    media_6a.columns = ['ticker', 'dividendos_6a_media']

    return div_12m, media_6a

def calcular_cagr(df_fund):
    """Calcula CAGR de 5 anos para Receita e Lucro"""
    print("🔄 Calculando CAGR 5 anos...")
    df_anual = df_fund[['ticker', 'ano', 'receita_liquida', 'lucro_liquido']].copy()
    cagr_data = []
    
    for ticker in df_anual['ticker'].unique():
        df_ticker = df_anual[df_anual['ticker'] == ticker].sort_values('ano')
        if len(df_ticker) < 2: continue
        
        ano_atual = df_ticker['ano'].max()
        ano_base = ano_atual - 5
        
        reg_atual = df_ticker[df_ticker['ano'] == ano_atual].iloc[0]
        reg_base = df_ticker[df_ticker['ano'] == ano_base]
        
        if reg_base.empty: continue
        
        rec_atual, rec_base = reg_atual['receita_liquida'], reg_base.iloc[0]['receita_liquida']
        luc_atual, luc_base = reg_atual['lucro_liquido'], reg_base.iloc[0]['lucro_liquido']
        
        cagr_rec = (rec_atual / rec_base) ** (1/5) - 1 if rec_base > 0 else np.nan
        cagr_luc = (luc_atual / luc_base) ** (1/5) - 1 if luc_base > 0 else np.nan
        
        cagr_data.append({'ticker': ticker, 'ano': ano_atual, 'cagr_receita_5a': cagr_rec, 'cagr_lucro_5a': cagr_luc})
        
    return pd.DataFrame(cagr_data)

def calcular_e_salvar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr):
    print("🧮 Calculando indicadores e valuations...")
    
    # Merge de dados
    df = df_fund.merge(df_cot, on='ticker', how='left')
    df = df.merge(df_div_12m, on='ticker', how='left')
    df = df.merge(df_div_6a, on='ticker', how='left')
    df = df.merge(df_cagr, on=['ticker', 'ano'], how='left')
    
    df['volume_medio_diario'] = df['volume_medio_diario'].fillna(0)
    
    # 1. Por Ação
    df['lpa'] = df['lucro_liquido'] / df['quantidade_acoes']
    df['vpa'] = df['patrimonio_liquido'] / df['quantidade_acoes']
    
    # 2. Múltiplos de Mercado
    mc = df['preco_atual'] * df['quantidade_acoes']
    df['p_l'] = df['preco_atual'] / df['lpa']
    df['p_vp'] = df['preco_atual'] / df['vpa']
    df['p_receita'] = mc / df['receita_liquida']
    df['p_ativo'] = mc / df['ativo_total']
    df['p_cap_giro'] = mc / (df['ativo_circulante'] - df['passivo_circulante'])
    df['p_ativo_circ_liq'] = df['p_cap_giro']
    df['p_ebit'] = mc / df['ebit']
    df['p_ebitda'] = mc / df['ebitda']
    
    ev = mc + df['divida_liquida']
    df['ev_ebit'] = ev / df['ebit']
    df['ev_ebitda'] = ev / df['ebitda']
    
    # 3. Rentabilidade e Margens
    df['roe'] = df['lucro_liquido'] / df['patrimonio_liquido']
    df['roa'] = df['lucro_liquido'] / df['ativo_total']
    df['roic'] = (df['ebit'] * (1 - TAXA_IMPOSTO)) / (df['patrimonio_liquido'] + df['divida_liquida'])
    df['giro_ativos'] = df['receita_liquida'] / df['ativo_total']
    
    df['margem_bruta'] = df['lucro_bruto'] / df['receita_liquida']
    df['margem_ebit'] = df['ebit'] / df['receita_liquida']
    df['margem_ebitda'] = df['ebitda'] / df['receita_liquida']
    df['margem_liquida'] = df['lucro_liquido'] / df['receita_liquida']
    
    # 4. Endividamento e Liquidez
    df['div_liq_ativos'] = df['divida_liquida'] / df['ativo_total']
    df['div_liq_pl'] = df['divida_liquida'] / df['patrimonio_liquido']
    df['div_liq_ebit'] = df['divida_liquida'] / df['ebit']
    df['div_liq_ebitda'] = df['divida_liquida'] / df['ebitda']
    df['liquidez_corrente'] = df['ativo_circulante'] / df['passivo_circulante']
    df['passivos_ativos'] = (df['ativo_total'] - df['patrimonio_liquido']) / df['ativo_total']
    df['pl_ativos'] = df['patrimonio_liquido'] / df['ativo_total']
    
    # 5. Dividend Yield
    df['dy_atual'] = df['dividendos_12m'] / df['preco_atual']
    
    # 6. Valuation (Preços Justos)
    df['preco_justo_graham'] = np.sqrt(22.5 * df['lpa'] * df['vpa'])
    df['preco_justo_graham_br'] = np.sqrt(15 * df['lpa'] * df['vpa'])
    df['preco_justo_bazin'] = df['dividendos_12m'] / 0.06
    
    # Lynch (PEG): Proteção para CAGR entre 0 e 50%
    df['preco_justo_lynch'] = np.where(
        (df['cagr_lucro_5a'] > 0) & (df['cagr_lucro_5a'] <= 0.50),
        df['lpa'] * (df['cagr_lucro_5a'] * 100),
        np.nan
    )
    
    # AGF (Barsi)
    df['preco_teto_medio'] = df['dividendos_6a_media'] / 0.06
    
    # 7. Upsides (%)
    for metodo in ['graham', 'graham_br', 'bazin', 'lynch']:
        df[f'{metodo}_upside'] = ((df[f'preco_justo_{metodo}'] / df['preco_atual']) - 1) * 100
    df['agf_upside'] = ((df['preco_teto_medio'] / df['preco_atual']) - 1) * 100
    
    # 8. Dados Absolutos e Metadados
    df['pl_absoluto'] = df['patrimonio_liquido']
    df['data_calculo'] = datetime.now().date()
    df['data_balanco'] = pd.to_datetime(df['data_referencia']).dt.date if 'data_referencia' in df.columns else None
    
    # Limpeza para o Supabase
    cols_finais = [
        'ticker', 'ano', 'data_calculo', 'data_balanco',
        'dy_atual', 'p_l', 'p_vp', 'p_receita', 'p_ativo', 'p_cap_giro', 
        'p_ativo_circ_liq', 'p_ebit', 'p_ebitda', 'ev_ebit', 'ev_ebitda',
        'roe', 'roa', 'roic', 'giro_ativos', 'margem_bruta', 'margem_ebit', 
        'margem_ebitda', 'margem_liquida', 'liquidez_corrente', 'passivos_ativos', 
        'pl_ativos', 'div_liq_ativos', 'div_liq_pl', 'div_liq_ebit', 'div_liq_ebitda',
        'cagr_receita_5a', 'cagr_lucro_5a', 'receita_liquida', 'lucro_liquido', 'ebit',
        'lpa', 'vpa', 'preco_justo_graham', 'graham_upside', 'preco_justo_graham_br', 
        'graham_br_upside', 'preco_justo_bazin', 'bazin_upside', 'preco_justo_lynch', 
        'lynch_upside', 'preco_teto_medio', 'agf_upside', 'pl_absoluto', 
        'dividendos_12m', 'dividendos_6a_media', 'volume_medio_diario'
    ]
    
    df_saida = df[[c for c in cols_finais if c in df.columns]].replace({np.inf: None, -np.inf: None, np.nan: None})
    registros = df_saida.to_dict('records')
    
    print(f"💾 Salvando {len(registros)} registros no Supabase...")
    if registros:
        lote = 100
        for i in range(0, len(registros), lote):
            supabase.table("indicadores").upsert(
                registros[i:i+lote], 
                on_conflict="ticker" # Ajuste para 'ticker,data_calculo' se quiser histórico
            ).execute()
        print("✅ Salvamento concluído.")

def main():
    print("🚀 Iniciando Motor de Indicadores (Fase 2)...")
    
    df_fund = buscar_fundamentos()
    if df_fund.empty:
        print("❌ Sem fundamentos. Abortando.")
        return
        
    df_cot = buscar_cotacoes()
    df_div = buscar_dividendos()
    
    df_div_12m, df_div_6a = calcular_agregacoes_dividendos(df_div)
    df_cagr = calcular_cagr(df_fund)
    
    calcular_e_salvar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr)
    
    print("\n CONCLUÍDO! Fase 2 finalizada.")

if __name__ == "__main__":
    main()
