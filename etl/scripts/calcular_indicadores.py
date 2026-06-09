import pandas as pd
import numpy as np
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

def registrar_carga(status, registros, mensagem):
    supabase.table("etl_cargas").insert({
        "processo": "calcular_indicadores",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status, "registros": registros, "mensagem": mensagem
    }).execute()

def main():
    print("🔄 Extraindo dados para cálculo...")
    # Busca dados do Supabase
    fund = pd.DataFrame(supabase.table("fundamentos_trimestrais").select("*").execute().data)
    cot = pd.DataFrame(supabase.table("cotacoes").select("ticker, data, fechamento").execute().data)
    div = pd.DataFrame(supabase.table("dividendos").select("ticker, data_pagamento, valor").execute().data)
    emp = pd.DataFrame(supabase.table("empresas").select("ticker").execute().data)
    
    if fund.empty:
        print("❌ Tabela fundamentos_trimestrais vazia. Rode o etl_fundamentos_cvm.py primeiro!")
        return

    # 1. Preparar Cotações (Pegar o último preço de cada ticker)
    cot['data'] = pd.to_datetime(cot['data'])
    cot_ultimas = cot.sort_values('data').groupby('ticker').tail(1)[['ticker', 'fechamento']]
    cot_ultimas.rename(columns={'fechamento': 'preco_atual'}, inplace=True)
    
    # 2. Preparar Dividendos (Calcular DY dos últimos 12 meses)
    div['data_pagamento'] = pd.to_datetime(div['data_pagamento'])
    div['valor'] = pd.to_numeric(div['valor'], errors='coerce').fillna(0)
    data_limite = datetime.now() - pd.DateOffset(years=1)
    div_12m = div[div['data_pagamento'] >= data_limite].groupby('ticker')['valor'].sum().reset_index()
    div_12m.rename(columns={'valor': 'div_12m'}, inplace=True)

    # 3. Filtrar apenas o último balanço anual (DFP) ou trimestral mais recente de cada empresa
    fund['data_referencia'] = pd.to_datetime(fund['data_referencia'])
    fund_ultimos = fund.sort_values('data_referencia').groupby('ticker').tail(1)
    
    # Para indicadores de DRE (Receita, Lucro, EBIT), precisamos do acumulado de 12 meses (LTM)
    # Simplificação: Usar o último dado anual (trimestre 4) ou somar os 4 últimos trimestres
    fund_anual = fund[fund['trimestre'] == 4].sort_values('data_referencia').groupby('ticker').tail(1)
    
    # Merge de tudo
    df_ind = pd.merge(emp, cot_ultimas, on='ticker', how='inner')
    df_ind = pd.merge(df_ind, div_12m, on='ticker', how='left')
    df_ind = pd.merge(df_ind, fund_anual[['ticker', 'receita_liquida', 'lucro_bruto', 'ebit', 'lucro_liquido']], on='ticker', how='left', suffixes=('', '_dre'))
    df_ind = pd.merge(df_ind, fund_ultimos[['ticker', 'ativo_total', 'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida']], on='ticker', how='left', suffixes=('', '_bal'))
    
    # Preencher nulos com 0 para evitar erros de divisão
    numeric_cols = df_ind.select_dtypes(include=[np.number]).columns
    df_ind[numeric_cols] = df_ind[numeric_cols].fillna(0)
    
    print(f"🧮 Calculando indicadores para {len(df_ind)} empresas...")
    
    # --- CÁLCULOS FINANCEIROS (Fórmulas CFA) ---
    # Evitar divisão por zero
    df_ind['roe'] = np.where(df_ind['patrimonio_liquido'] != 0, df_ind['lucro_liquido'] / df_ind['patrimonio_liquido'], np.nan)
    df_ind['roa'] = np.where(df_ind['ativo_total'] != 0, df_ind['lucro_liquido'] / df_ind['ativo_total'], np.nan)
    df_ind['margem_liquida'] = np.where(df_ind['receita_liquida'] != 0, df_ind['lucro_liquido'] / df_ind['receita_liquida'], np.nan)
    df_ind['margem_ebit'] = np.where(df_ind['receita_liquida'] != 0, df_ind['ebit'] / df_ind['receita_liquida'], np.nan)
    df_ind['margem_bruta'] = np.where(df_ind['receita_liquida'] != 0, df_ind['lucro_bruto'] / df_ind['receita_liquida'], np.nan)
    
    df_ind['liq_corrente'] = np.where(df_ind['passivo_circulante'] != 0, df_ind['ativo_circulante'] / df_ind['passivo_circulante'], np.nan)
    df_ind['div_liq_pl'] = np.where(df_ind['patrimonio_liquido'] != 0, df_ind['divida_liquida'] / df_ind['patrimonio_liquido'], np.nan)
    df_ind['div_liq_ativos'] = np.where(df_ind['ativo_total'] != 0, df_ind['divida_liquida'] / df_ind['ativo_total'], np.nan)
    df_ind['pl_ativos'] = np.where(df_ind['ativo_total'] != 0, df_ind['patrimonio_liquido'] / df_ind['ativo_total'], np.nan)
    
    # Dividend Yield
    df_ind['dy_atual'] = np.where(df_ind['preco_atual'] != 0, df_ind['div_12m'] / df_ind['preco_atual'], np.nan)
    
    # Nota sobre P/L e P/VP: Exigem 'quantidade_acoes' ou 'market_cap'. 
    # Como não temos market_cap no banco, deixaremos nulo por enquanto, ou o usuário pode ajustar.
    df_ind['p_l'] = np.nan 
    df_ind['p_vp'] = np.nan
    df_ind['ev_ebitda'] = np.nan
    
    # Preparar para inserção
    df_ind['data_calculo'] = datetime.now(UTC).date().isoformat()
    
    cols_finais = [
        'ticker', 'data_calculo', 'dy_atual', 'p_l', 'p_vp', 'roe', 'roa', 
        'margem_bruta', 'margem_ebit', 'margem_liquida', 'liq_corrente', 
        'div_liq_pl', 'div_liq_ativos', 'pl_ativos'
    ]
    
    # Adicionar colunas que existem no banco mas não calculamos (para não dar erro de schema)
    for col in ['p_receita', 'p_ativo', 'p_cap_giro', 'p_ativo_circ_liq', 'p_ebit', 'p_ebitda', 'ev_ebit', 'giro_ativos', 'margem_ebitda', 'div_liq_ebit']:
        df_ind[col] = np.nan
        
    cols_finais = [c for c in cols_finais if c in df_ind.columns]
    df_insert = df_ind[cols_finais].replace({np.nan: None})
    
    registros = df_insert.to_dict('records')
    
    if registros:
        print(f"🚀 Inserindo {len(registros)} indicadores no Supabase...")
        # Upsert em lotes para não estourar limite da API do Supabase
        lote = 100
        for i in range(0, len(registros), lote):
            supabase.table("indicadores").upsert(
                registros[i:i+lote], 
                on_conflict="ticker,data_calculo"
            ).execute()
            
        registrar_carga("SUCESSO", len(registros), "Indicadores Gold calculados")
        print("✅ Concluído! Tabela indicadores populada.")
    else:
        print("Nenhum indicador gerado.")

if __name__ == "__main__":
    main()
