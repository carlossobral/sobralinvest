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

def buscar_fundamentos() -> pd.DataFrame:
    print("Buscando fundamentos (todos os trimestres)...")

    data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("fundamentos_trimestrais")
            .select("*")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)

    num_cols = [
        "receita_liquida_ytd", "lucro_bruto_ytd", "ebit_ytd", "ebitda_ytd",
        "lucro_liquido_ytd", "receita_liquida_q", "lucro_bruto_q",
        "ebit_q", "ebitda_q", "lucro_liquido_q",
        "ativo_total", "ativo_circulante", "passivo_circulante",
        "patrimonio_liquido", "caixa", "divida_bruta", "divida_liquida",
        "quantidade_acoes", "ano", "trimestre",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["data_referencia"] = pd.to_datetime(df["data_referencia"], errors="coerce")
    df = df.sort_values(["ticker", "data_referencia"])

    # ebitda_q nulo -> estima como ebit_q
    if "ebitda_q" in df.columns and "ebit_q" in df.columns:
        mask = df["ebitda_q"].isna() & df["ebit_q"].notna()
        df.loc[mask, "ebitda_q"] = df.loc[mask, "ebit_q"]

    resultados = []

    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("data_referencia", ascending=False)
        
        # Pega os últimos 5 trimestres (para ter o PL de 1 ano atrás)
        ultimos = grp.head(5)
        # Os últimos 4 para o LTM
        ultimos4 = ultimos.head(4)

        if len(ultimos4) < 1:
            continue

        mais_recente = ultimos4.iloc[0]

        def ltm(col):
            if col not in ultimos4.columns:
                return None
            vals = pd.to_numeric(ultimos4[col], errors="coerce").dropna()
            return float(vals.sum()) if len(vals) >= 1 else None

        def bal(col):
            v = mais_recente.get(col)
            return safe_float(v)

        def bal_1_ano(col):
            if len(ultimos) >= 5:
                v = ultimos.iloc[4].get(col)
                return safe_float(v)
            return None

        row = {
            "ticker": ticker,
            "ano": int(mais_recente["ano"]) if pd.notna(mais_recente["ano"]) else None,
            "trimestre": int(mais_recente["trimestre"]) if pd.notna(mais_recente["trimestre"]) else None,
            "data_referencia": mais_recente["data_referencia"],
            "trimestres_ltm": len(ultimos4),
            "receita_liquida_ltm": ltm("receita_liquida_q"),
            "lucro_bruto_ltm": ltm("lucro_bruto_q"),
            "ebit_ltm": ltm("ebit_q"),
            "ebitda_ltm": ltm("ebitda_q"),
            "lucro_liquido_ltm": ltm("lucro_liquido_q"),
            # Dados Trimestrais Isolados (Q)
            "receita_liquida_q": bal("receita_liquida_q"),
            "lucro_bruto_q": bal("lucro_bruto_q"),
            "ebit_q": bal("ebit_q"),
            "ebitda_q": bal("ebitda_q"),
            "lucro_liquido_q": bal("lucro_liquido_q"),
            # Balanço Patrimonial
            "ativo_total": bal("ativo_total"),
            "ativo_circulante": bal("ativo_circulante"),
            "passivo_circulante": bal("passivo_circulante"),
            "patrimonio_liquido": bal("patrimonio_liquido"),
            "patrimonio_liquido_1a": bal_1_ano("patrimonio_liquido"),
            "caixa": bal("caixa"),
            "divida_bruta": bal("divida_bruta"),
            "divida_liquida": bal("divida_liquida"),
        }
        resultados.append(row)

    df_out = pd.DataFrame(resultados)

    mask = (
        df_out["receita_liquida_ltm"].notna() &
        (df_out["receita_liquida_ltm"] > 0) &
        df_out["patrimonio_liquido"].notna() &
        (df_out["patrimonio_liquido"] != 0)
    )
    df_out = df_out[mask].copy()
    print(f"  {len(df_out)} tickers com LTM válido.")
    return df_out

def buscar_cotacoes() -> pd.DataFrame:
    print("Buscando cotacoes (ultimos 60 dias)...")

    data_limite = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("cotacoes")
            .select("ticker, data, fechamento, volume")
            .gte("data", data_limite)
            .range(offset, offset + 999)
            .execute()
            .data
        )
        data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    if not data:
        print("  Nenhuma cotacao encontrada.")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["fechamento"] = pd.to_numeric(df["fechamento"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df["data"] = pd.to_datetime(df["data"])
    df["volume_financeiro"] = df["volume"] * df["fechamento"]

    preco = (
        df.sort_values("data")
        .drop_duplicates(subset=["ticker"], keep="last")[["ticker", "fechamento"]]
        .rename(columns={"fechamento": "preco_atual"})
    )
    vol_medio = (
        df.groupby("ticker")["volume_financeiro"]
        .mean()
        .reset_index()
        .rename(columns={"volume_financeiro": "volume_medio_diario"})
    )

    result = preco.merge(vol_medio, on="ticker", how="inner")
    print(f"  {len(result)} cotacoes processadas.")
    return result

def buscar_dividendos() -> pd.DataFrame:
    print("Buscando dividendos (ultimos 7 anos)...")

    data_limite = (datetime.now() - timedelta(days=365 * 7)).strftime("%Y-%m-%d")

    data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("dividendos")
            .select("ticker, data_pagamento, valor")
            .gte("data_pagamento", data_limite)
            .range(offset, offset + 999)
            .execute()
            .data
        )
        data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["data_pagamento"] = pd.to_datetime(df["data_pagamento"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0)
    print(f"  {len(df)} eventos de dividendos carregados.")
    return df

def calcular_dividendos(df_div: pd.DataFrame):
    empty = pd.DataFrame(columns=["ticker"])
    if df_div.empty:
        return empty.assign(dividendos_12m=None), empty.assign(dividendos_6a_media=None)

    hoje = datetime.now()

    div_12m = (
        df_div[df_div["data_pagamento"] >= hoje - timedelta(days=365)]
        .groupby("ticker")["valor"].sum()
        .reset_index()
        .rename(columns={"valor": "dividendos_12m"})
    )

    div_6a = df_div[df_div["data_pagamento"] >= hoje - timedelta(days=365 * 6)].copy()
    div_6a["ano_div"] = div_6a["data_pagamento"].dt.year
    media_6a = (
        div_6a.groupby(["ticker", "ano_div"])["valor"].sum()
        .groupby("ticker").mean()
        .reset_index()
        .rename(columns={"valor": "dividendos_6a_media"})
    )

    return div_12m, media_6a

def calcular_cagr(df_fund: pd.DataFrame) -> pd.DataFrame:
    print("Calculando CAGR 5 anos (base T4 - otimizado)...")

    data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("fundamentos_trimestrais")
            .select("ticker, ano, trimestre, receita_liquida_ytd, lucro_liquido_ytd")
            .eq("trimestre", 4)
            .range(offset, offset + 999)
            .execute()
            .data
        )
        data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    if not data:
        return pd.DataFrame(columns=["ticker", "cagr_receita_5a", "cagr_lucro_5a"])

    df = pd.DataFrame(data)
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
    df["receita_liquida_ytd"] = pd.to_numeric(df["receita_liquida_ytd"], errors="coerce")
    df["lucro_liquido_ytd"] = pd.to_numeric(df["lucro_liquido_ytd"], errors="coerce")

    df = df.sort_values(["ticker", "ano"]).reset_index(drop=True)

    df["rec_5a_ago"] = df.groupby("ticker")["receita_liquida_ytd"].shift(5)
    df["luc_5a_ago"] = df.groupby("ticker")["lucro_liquido_ytd"].shift(5)

    df_latest = df.loc[df.groupby("ticker")["ano"].idxmax()].copy()

    mask_rec = (df_latest["rec_5a_ago"] > 0) & (df_latest["receita_liquida_ytd"].notna()) & (df_latest["rec_5a_ago"].notna())
    mask_luc = (df_latest["luc_5a_ago"] > 0) & (df_latest["lucro_liquido_ytd"].notna()) & (df_latest["luc_5a_ago"].notna())

    df_latest["cagr_receita_5a"] = np.where(
        mask_rec,
        (df_latest["receita_liquida_ytd"] / df_latest["rec_5a_ago"]) ** (1 / 5) - 1,
        np.nan
    )

    df_latest["cagr_lucro_5a"] = np.where(
        mask_luc,
        (df_latest["lucro_liquido_ytd"] / df_latest["luc_5a_ago"]) ** (1 / 5) - 1,
        np.nan
    )

    result = df_latest[["ticker", "cagr_receita_5a", "cagr_lucro_5a"]].copy()
    
    result["cagr_receita_5a"] = result["cagr_receita_5a"].apply(safe_float)
    result["cagr_lucro_5a"] = result["cagr_lucro_5a"].apply(safe_float)

    print(f"  CAGR calculado para {len(result)} tickers.")
    return result

def sd(a, b):
    """Divisão segura: retorna None se denominador for 0, None ou NaN."""
    try:
        if b is None or (isinstance(b, float) and (math.isnan(b) or b == 0)):
            return None
        r = a / b
        return safe_float(r)
    except Exception:
        return None

def calcular_e_savar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr):
    if df_cot.empty:
        print("Sem cotacoes. Abortando.")
        return

    print("Calculando indicadores...")

    # Buscar dados cadastrais (qtd_acoes_totais e segmento)
    print("Buscando dados cadastrais (empresas)...")
    empresas_data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("empresas")
            .select("ticker, segmento, qtd_acoes_totais")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        empresas_data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    
    df_empresas = pd.DataFrame(empresas_data)
    df_empresas["qtd_acoes_totais"] = pd.to_numeric(df_empresas["qtd_acoes_totais"], errors="coerce")
    
    # Merge inicial
    df = (
        df_fund
        .merge(df_cot, on="ticker", how="inner")
        .merge(df_div_12m, on="ticker", how="left")
        .merge(df_div_6a, on="ticker", how="left")
        .merge(df_empresas[["ticker", "segmento", "qtd_acoes_totais"]], on="ticker", how="left")
    )

    if not df_cagr.empty:
        df = df.merge(df_cagr, on="ticker", how="left")
    else:
        df["cagr_receita_5a"] = None
        df["cagr_lucro_5a"] = None

    for col in ["dividendos_12m", "dividendos_6a_media", "volume_medio_diario",
                "ativo_total", "ativo_circulante", "passivo_circulante",
                "patrimonio_liquido", "patrimonio_liquido_1a", "caixa", "divida_bruta", "divida_liquida",
                "qtd_acoes_totais", "preco_atual"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["dividendos_12m"] = df["dividendos_12m"].fillna(0)
    df["dividendos_6a_media"] = df["dividendos_6a_media"].fillna(0)
    df["volume_medio_diario"] = df["volume_medio_diario"].fillna(0)
    df["divida_liquida"] = df["divida_liquida"].fillna(0)

    df["data_calculo"] = datetime.now(UTC).date().isoformat()
    df["data_balanco"] = pd.to_datetime(
        df["data_referencia"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    df = df.rename(columns={
        "receita_liquida_ltm": "receita_liquida",
        "lucro_liquido_ltm": "lucro_liquido",
        "ebit_ltm": "ebit",
    })

    registros_saida = []

    # Bancos e Seguradoras (Regra CS Score)
    tickers_finan_especificos = {"WIZC3", "CXSE3", "BBSE3"}
    tickers_itau = {"ITSA3", "ITSA4"}

    for _, row in df.iterrows():
        t = row.get
        p = safe_float(t("preco_atual"))
        
        ticker_atual = row["ticker"]
        segmento_atual = t("segmento")
        
        # Qtd de ações total (Consolidada) para Market Cap, LPA e VPA
        qty_total = safe_float(t("qtd_acoes_totais"))
        
        pl = safe_float(t("patrimonio_liquido"))
        pl_1a = safe_float(t("patrimonio_liquido_1a"))
        
        # Cálculo do PL Médio para ROE
        pl_medio = None
        if pl is not None and pl_1a is not None:
            pl_medio = (pl + pl_1a) / 2.0
        elif pl is not None:
            pl_medio = pl # Fallback caso não tenha 1 ano de histórico
            
        at = safe_float(t("ativo_total"))
        ac = safe_float(t("ativo_circulante"))
        pc = safe_float(t("passivo_circulante"))
        div_liq = safe_float(t("divida_liquida")) or 0.0
        
        # Valores LTM
        rec_ltm = safe_float(t("receita_liquida"))
        ll_ltm = safe_float(t("lucro_liquido"))
        ebit_ltm = safe_float(t("ebit"))
        ebitda_ltm = safe_float(t("ebitda_ltm"))
        lb_ltm = safe_float(t("lucro_bruto_ltm"))
        
        # Valores Trimestrais Isolados (Q) - para Margens
        rec_q = safe_float(t("receita_liquida_q"))
        lb_q = safe_float(t("lucro_bruto_q"))
        ebit_q = safe_float(t("ebit_q"))
        ebitda_q = safe_float(t("ebitda_q"))
        ll_q = safe_float(t("lucro_liquido_q"))
        
        div12m = safe_float(t("dividendos_12m")) or 0.0
        div6a = safe_float(t("dividendos_6a_media")) or 0.0

        # Market Cap usa qtd_total (Consolidada)
        mc = (p * qty_total) if (p and qty_total) else None
        ev = (mc + div_liq) if mc is not None else None
        
        # LPA e VPA usam qtd_total
        lpa = sd(ll_ltm, qty_total)
        vpa = sd(pl, qty_total)
        
        cap_giro = (ac - pc) if (ac is not None and pc is not None) else None
        cap_inv = (pl + div_liq) if pl is not None else None

        # Lógica Banco/Seguradora
        is_banco = segmento_atual == "Bancos" and ticker_atual not in tickers_itau
        is_seguradora = segmento_atual == "Seguradoras" or ticker_atual in tickers_finan_especificos
        is_financeira = is_banco or is_seguradora

        div_liq_ebitda_val = sd(div_liq, ebitda_ltm)
        div_liq_ebit_val = sd(div_liq, ebit_ltm)

        if is_financeira:
            div_liq_ebitda_val = None
            div_liq_ebit_val = None

        rec_dict = {
            "ticker": ticker_atual,
            "ano": row.get("ano"),
            "data_calculo": row["data_calculo"],
            "data_balanco": row["data_balanco"],
            "preco_atual": p,
            "dy_atual": sd(div12m, p),
            "p_l": sd(p, lpa),
            "p_vp": sd(p, vpa),
            "p_receita": sd(mc, rec_ltm), # Market Cap Consolidado / Receita LTM
            "p_ativo": sd(mc, at),
            "p_cap_giro": sd(mc, cap_giro),
            "p_ativo_circ_liq": sd(mc, cap_giro),
            "p_ebit": sd(mc, ebit_ltm),
            "p_ebitda": sd(mc, ebitda_ltm),
            "ev_ebit": sd(ev, ebit_ltm),
            "ev_ebitda": sd(ev, ebitda_ltm),
            "roe": sd(ll_ltm, pl_medio), # ROE com PL Médio
            "roa": sd(ll_ltm, at),
            "roic": sd(ebit_ltm * (1 - TAXA_IMPOSTO) if ebit_ltm else None, cap_inv),
            "giro_ativos": sd(rec_ltm, at),
            # MARGENS ALTERADAS PARA TRIMESTRAL (_q)
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

        # Graham upside
        for metodo, campo in [
            ("graham", "graham"),
            ("graham_br", "graham_br"),
            ("bazin", "bazin"),
        ]:
            pj = rec_dict.get(campo)
            rec_dict[f"{metodo}_upside"] = sd((pj / p - 1) * 100 if (pj and p) else None, 1)

        # AGF
        pt = rec_dict.get("agf")
        rec_dict["agf_upside"] = sd(((pt / p - 1) * 100) if (pt and p) else None, 1)

        registros_saida.append(limpar_registro(rec_dict))

    print(f"Salvando {len(registros_saida)} registros...")

    lote = 100
    erros = 0
    salvos = 0
    for i in range(0, len(registros_saida), lote):
        try:
            supabase.table("indicadores").upsert(
                registros_saida[i: i + lote],
                on_conflict="ticker,data_calculo",
            ).execute()
            salvos += len(registros_saida[i: i + lote])
        except Exception as e:
            erros += 1
            print(f"  Erro no lote {i}: {e}")

    print(f"Concluido. {salvos} registros salvos, {erros} lotes com erro.")

def main():
    print("Iniciando calculo de indicadores (LTM + Margens Q + ROE Médio)...")

    df_fund = buscar_fundamentos()
    if df_fund.empty:
        print("Sem fundamentos. Abortando.")
        return

    df_cot = buscar_cotacoes()
    df_div = buscar_dividendos()
    df_div_12m, df_div_6a = calcular_dividendos(df_div)
    df_cagr = calcular_cagr(df_fund)

    calcular_e_savar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr)

    print("\n========== FINAL ==========")
    print("Indicadores calculados com sucesso.")

if __name__ == "__main__":
    main()
