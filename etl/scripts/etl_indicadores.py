from datetime import datetime, timedelta, UTC
import math
import numpy as np
import pandas as pd
from etl.database.supabase_client import supabase

TAXA_IMPOSTO = 0.34

def safe_float(v):
    """Converte valor para float limpo ou None."""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None

def limpar_registro(rec: dict) -> dict:
    """Garante que todos os valores float são serializáveis."""
    return {k: safe_float(v) if isinstance(v, (float, np.floating)) else v
            for k, v in rec.items()}

def sd(a, b):
    """Divisão segura: retorna None se denominador for 0, None ou NaN."""
    try:
        if b is None or (isinstance(b, float) and (math.isnan(b) or b == 0)):
            return None
        r = a / b
        return safe_float(r)
    except Exception:
        return None

def main():
    print("Iniciando calculo de indicadores HISTÓRICOS...")
    
    print("Buscando todos os dados do Supabase (pode demorar)...")
    
    # 1. Buscar Fundamentos
    fund_data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("fundamentos_trimestrais")
            .select("*")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        fund_data.extend(chunk)
        if len(chunk) < 1000: break
        offset += 1000
    df_fund = pd.DataFrame(fund_data)
    if df_fund.empty:
        print("Sem fundamentos. Abortando.")
        return
        
    # 2. Buscar Empresas
    emp_data = supabase.table("empresas").select("ticker, segmento, qtd_acoes_totais").execute().data
    df_emp = pd.DataFrame(emp_data)
    
    # 3. Buscar Cotações
    cot_data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("cotacoes")
            .select("ticker, data, fechamento, volume")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        cot_data.extend(chunk)
        if len(chunk) < 1000: break
        offset += 1000
    df_cot = pd.DataFrame(cot_data)
    
    # 4. Buscar Dividendos
    div_data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("dividendos")
            .select("ticker, data_pagamento, valor")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        div_data.extend(chunk)
        if len(chunk) < 1000: break
        offset += 1000
    df_div = pd.DataFrame(div_data)

    # --- PREPARAÇÃO DOS DADOS ---
    print("Processando dados históricos no Pandas...")
    
    # Fundamentos
    num_cols = [
        "receita_liquida_ytd", "lucro_bruto_ytd", "ebit_ytd", "ebitda_ytd",
        "lucro_liquido_ytd", "receita_liquida_q", "lucro_bruto_q",
        "ebit_q", "ebitda_q", "lucro_liquido_q",
        "ativo_total", "ativo_circulante", "passivo_circulante",
        "patrimonio_liquido", "caixa", "divida_bruta", "divida_liquida",
        "quantidade_acoes", "ano", "trimestre",
    ]
    for col in num_cols:
        if col in df_fund.columns:
            df_fund[col] = pd.to_numeric(df_fund[col], errors="coerce")
            
    df_fund["data_referencia"] = pd.to_datetime(df_fund["data_referencia"], errors="coerce")
    df_fund = df_fund.sort_values(["ticker", "data_referencia"]).reset_index(drop=True)
    
    # Calcular LTM (soma dos últimos 4Q) usando rolling
    ltm_map = {
        'receita_liquida_q': 'receita_liquida_ltm',
        'lucro_bruto_q': 'lucro_bruto_ltm',
        'ebit_q': 'ebit_ltm',
        'ebitda_q': 'ebitda_ltm',
        'lucro_liquido_q': 'lucro_liquido_ltm'
    }
    for q_col, ltm_col in ltm_map.items():
        df_fund[ltm_col] = df_fund.groupby('ticker')[q_col].rolling(window=4, min_periods=1).sum().reset_index(level=0, drop=True)
        
    # Calcular PL de 1 ano atrás (shift 4)
    df_fund['patrimonio_liquido_1a'] = df_fund.groupby('ticker')['patrimonio_liquido'].shift(4)
    
    # Pre-calcular CAGR (apenas para T4)
    df_t4 = df_fund[df_fund['trimestre'] == 4].copy()
    df_t4['rec_5a_ago'] = df_t4.groupby('ticker')['receita_liquida_ytd'].shift(5)
    df_t4['luc_5a_ago'] = df_t4.groupby('ticker')['lucro_liquido_ytd'].shift(5)
    
    mask_rec = (df_t4["rec_5a_ago"] > 0) & (df_t4["receita_liquida_ytd"].notna()) & (df_t4["rec_5a_ago"].notna())
    mask_luc = (df_t4["luc_5a_ago"] > 0) & (df_t4["lucro_liquido_ytd"].notna()) & (df_t4["luc_5a_ago"].notna())
    
    df_t4['cagr_receita_5a'] = np.where(mask_rec, (df_t4['receita_liquida_ytd'] / df_t4['rec_5a_ago']) ** (1/5) - 1, np.nan)
    df_t4['cagr_lucro_5a'] = np.where(mask_luc, (df_t4['lucro_liquido_ytd'] / df_t4['luc_5a_ago']) ** (1/5) - 1, np.nan)
    
    df_fund = df_fund.merge(df_t4[['ticker', 'ano', 'cagr_receita_5a', 'cagr_lucro_5a']], on=['ticker', 'ano'], how='left')
    
    # Empresas
    df_emp["qtd_acoes_totais"] = pd.to_numeric(df_emp["qtd_acoes_totais"], errors="coerce")
    df_fund = df_fund.merge(df_emp[['ticker', 'segmento', 'qtd_acoes_totais']], on='ticker', how='left')
    
    # Cotações - Merge AsOf (Pega a cotação na data do balanço ou a anterior mais próxima)
    if not df_cot.empty:
        df_cot["data"] = pd.to_datetime(df_cot["data"], errors="coerce")
        df_cot["fechamento"] = pd.to_numeric(df_cot["fechamento"], errors="coerce")
        df_cot["volume"] = pd.to_numeric(df_cot["volume"], errors="coerce").fillna(0)
        df_cot["volume_financeiro"] = df_cot["volume"] * df_cot["fechamento"]
        
        # Calcula volume médio dos ultimos 30 dias historicos
        df_cot['volume_medio_30d'] = df_cot.groupby('ticker')['volume_financeiro'].rolling(window=30, min_periods=1).mean().reset_index(level=0, drop=True)
        
        # Limpeza crítica para o merge_asof: Remover NaT e ordenar
        df_cot = df_cot.dropna(subset=['data']).sort_values(['ticker', 'data']).reset_index(drop=True)
        df_fund = df_fund.dropna(subset=['data_referencia']).sort_values(['ticker', 'data_referencia']).reset_index(drop=True)
        
        df_merged = pd.merge_asof(
            df_fund, 
            df_cot[['ticker', 'data', 'fechamento', 'volume_medio_30d']], 
            left_on='data_referencia', 
            right_on='data', 
            by='ticker',
            direction='backward'
        )
        df_merged.rename(columns={'fechamento': 'preco_atual', 'volume_medio_30d': 'volume_medio_diario'}, inplace=True)
    else:
        df_merged = df_fund.copy()
        df_merged['preco_atual'] = np.nan
        df_merged['volume_medio_diario'] = 0.0

    # Dividendos - Agrupar para consulta rápida
    if not df_div.empty:
        df_div["data_pagamento"] = pd.to_datetime(df_div["data_pagamento"])
        df_div["valor"] = pd.to_numeric(df_div["valor"], errors="coerce").fillna(0)
        div_grouped = {t: g for t, g in df_div.groupby('ticker')}
    else:
        div_grouped = {}

    # Limpeza e Filtros
    df = df_merged.copy()
    df = df[df['preco_atual'].notna() & (df['preco_atual'] > 0)]
    df = df[df['receita_liquida_ltm'].notna() & (df['receita_liquida_ltm'] > 0)]
    df = df[df['patrimonio_liquido'].notna() & (df['patrimonio_liquido'] != 0)]
    
    print(f"Calculando indicadores para {len(df)} registros históricos...")

    tickers_finan_especificos = {"WIZC3", "CXSE3", "BBSE3"}
    tickers_itau = {"ITSA3", "ITSA4"}
    
    registros_saida = []
    
    for _, row in df.iterrows():
        t = row.get
        p = safe_float(t("preco_atual"))
        
        ticker_atual = row["ticker"]
        segmento_atual = t("segmento")
        qty_total = safe_float(t("qtd_acoes_totais"))
        
        # DY 12m histórico
        div12m = 0.0
        if ticker_atual in div_grouped:
            df_t_div = div_grouped[ticker_atual]
            mask = (df_t_div['data_pagamento'] <= row['data_referencia']) & (df_t_div['data_pagamento'] >= row['data_referencia'] - pd.Timedelta(days=365))
            div12m = safe_float(df_t_div.loc[mask, 'valor'].sum()) or 0.0
            
        # Dividendo 6a médio histórico
        div6a = 0.0
        if ticker_atual in div_grouped:
            df_t_div = div_grouped[ticker_atual]
            mask_6a = (df_t_div['data_pagamento'] <= row['data_referencia']) & (df_t_div['data_pagamento'] >= row['data_referencia'] - pd.Timedelta(days=365*6))
            if not df_t_div.loc[mask_6a].empty:
                df_6a = df_t_div.loc[mask_6a].copy()
                df_6a['ano_div'] = df_6a['data_pagamento'].dt.year
                div6a = safe_float(df_6a.groupby('ano_div')['valor'].sum().mean()) or 0.0

        pl = safe_float(t("patrimonio_liquido"))
        pl_1a = safe_float(t("patrimonio_liquido_1a"))
        
        pl_medio = None
        if pl is not None and pl_1a is not None:
            pl_medio = (pl + pl_1a) / 2.0
        elif pl is not None:
            pl_medio = pl
            
        at = safe_float(t("ativo_total"))
        ac = safe_float(t("ativo_circulante"))
        pc = safe_float(t("passivo_circulante"))
        div_liq = safe_float(t("divida_liquida")) or 0.0
        
        rec_ltm = safe_float(t("receita_liquida_ltm"))
        ll_ltm = safe_float(t("lucro_liquido_ltm"))
        ebit_ltm = safe_float(t("ebit_ltm"))
        ebitda_ltm = safe_float(t("ebitda_ltm"))
        lb_ltm = safe_float(t("lucro_bruto_ltm"))
        
        rec_q = safe_float(t("receita_liquida_q"))
        lb_q = safe_float(t("lucro_bruto_q"))
        ebit_q = safe_float(t("ebit_q"))
        ebitda_q = safe_float(t("ebitda_q"))
        ll_q = safe_float(t("lucro_liquido_q"))

        mc = (p * qty_total) if (p and qty_total) else None
        ev = (mc + div_liq) if mc is not None else None
        
        lpa = sd(ll_ltm, qty_total)
        vpa = sd(pl, qty_total)
        
        cap_giro = (ac - pc) if (ac is not None and pc is not None) else None
        cap_inv = (pl + div_liq) if pl is not None else None

        is_banco = segmento_atual == "Bancos" and ticker_atual not in tickers_itau
        is_seguradora = segmento_atual == "Seguradoras" or ticker_atual in tickers_finan_especificos
        is_financeira = is_banco or is_seguradora

        div_liq_ebitda_val = sd(div_liq, ebitda_ltm)
        div_liq_ebit_val = sd(div_liq, ebit_ltm)

        if is_financeira:
            div_liq_ebitda_val = None
            div_liq_ebit_val = None

        data_bal = row['data_referencia'].strftime("%Y-%m-%d") if pd.notna(row['data_referencia']) else None

        rec_dict = {
            "ticker": ticker_atual,
            "ano": int(row["ano"]) if pd.notna(row["ano"]) else None,
            "data_calculo": datetime.now(UTC).date().isoformat(),
            "data_balanco": data_bal,
            "preco_atual": p,
            "dy_atual": sd(div12m, p),
            "p_l": sd(p, lpa),
            "p_vp": sd(p, vpa),
            "p_receita": sd(mc, rec_ltm),
            "p_ativo": sd(mc, at),
            "p_cap_giro": sd(mc, cap_giro),
            "p_ativo_circ_liq": sd(mc, cap_giro),
            "p_ebit": sd(mc, ebit_ltm),
            "p_ebitda": sd(mc, ebitda_ltm),
            "ev_ebit": sd(ev, ebit_ltm),
            "ev_ebitda": sd(ev, ebitda_ltm),
            "roe": sd(ll_ltm, pl_medio),
            "roa": sd(ll_ltm, at),
            "roic": sd(ebit_ltm * (1 - TAXA_IMPOSTO) if ebit_ltm else None, cap_inv),
            "giro_ativos": sd(rec_ltm, at),
            "margem_bruta": sd(lb_q, rec_q),
            "margem_ebit": sd(ebit_q, rec_q),
            "margem_ebitda": sd(ebitda_q, rec_q),
            "margem_liquida": sd(ll_q, rec_q),
            "liquidez_corrente": sd(ac, pc),
            "passivos_ativos": sd((at - pl) if (at and pl) else None, at),
            "pl_ativos": sd(pl, at),
            "div_liq_ativos": sd(div_liq, at),
            "div_liq_pl": sd(div_liq, pl),
            "div_liq_ebit": div_liq_ebit_val,
            "div_liq_ebitda": div_liq_ebitda_val,
            "cagr_receita_5a": safe_float(t("cagr_receita_5a")),
            "cagr_lucro_5a": safe_float(t("cagr_lucro_5a")),
            "receita_liquida": rec_ltm,
            "lucro_liquido": ll_ltm,
            "ebit": ebit_ltm,
            "lpa": lpa,
            "vpa": vpa,
            "graham": safe_float(
                math.sqrt(max(0, 22.5 * (lpa or 0) * (vpa or 0))) if (lpa and lpa > 0 and vpa and vpa > 0) else None
            ),
            "graham_br": safe_float(
                math.sqrt(max(0, 15 * (lpa or 0) * (vpa or 0))) if (lpa and lpa > 0 and vpa and vpa > 0) else None
            ),
            "bazin": (div12m / 0.06) if div12m > 0 else None,
            "agf": (div6a / 0.06) if div6a > 0 else None,
            "dividendos_12m": div12m,
            "dividendos_6a_media": div6a,
            "pl_absoluto": pl,
            "volume_medio_diario": safe_float(t("volume_medio_diario")),
        }

        for metodo, campo in [
            ("graham", "graham"),
            ("graham_br", "graham_br"),
            ("bazin", "bazin"),
        ]:
            pj = rec_dict.get(campo)
            rec_dict[f"{metodo}_upside"] = sd((pj / p - 1) * 100 if (pj and p) else None, 1)

        pt = rec_dict.get("agf")
        rec_dict["agf_upside"] = sd(((pt / p - 1) * 100) if (pt and p) else None, 1)

        registros_saida.append(limpar_registro(rec_dict))

    print(f"Salvando {len(registros_saida)} registros no Supabase...")

    lote = 500
    erros = 0
    salvos = 0
    for i in range(0, len(registros_saida), lote):
        try:
            supabase.table("indicadores").upsert(
                registros_saida[i: i + lote],
                on_conflict="ticker,data_balanco",
            ).execute()
            salvos += len(registros_saida[i: i + lote])
        except Exception as e:
            erros += 1
            print(f"  Erro no lote {i}: {e}")

    print(f"Concluido. {salvos} registros salvos, {erros} lotes com erro.")

if __name__ == "__main__":
    main()
