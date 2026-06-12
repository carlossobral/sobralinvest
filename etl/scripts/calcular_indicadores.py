from datetime import datetime, UTC, timedelta

import numpy as np
import pandas as pd

from etl.database.supabase_client import supabase

TAXA_IMPOSTO = 0.34


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

    # ebitda_q nulo → estima como ebit_q
    if "ebitda_q" in df.columns and "ebit_q" in df.columns:
        mask = df["ebitda_q"].isna() & df["ebit_q"].notna()
        df.loc[mask, "ebitda_q"] = df.loc[mask, "ebit_q"]

    resultados = []

    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("data_referencia", ascending=False)
        ultimos4 = grp.head(4)

        if len(ultimos4) < 1:
            continue

        mais_recente = ultimos4.iloc[0]

        def ltm(col):
            if col not in ultimos4.columns:
                return np.nan
            vals = pd.to_numeric(ultimos4[col], errors="coerce")
            nao_nulos = vals.dropna()
            return nao_nulos.sum() if len(nao_nulos) >= 1 else np.nan

        row = {
            "ticker": ticker,
            "ano": int(mais_recente["ano"]) if pd.notna(mais_recente["ano"]) else None,
            "trimestre": int(mais_recente["trimestre"]) if pd.notna(mais_recente["trimestre"]) else None,
            "data_referencia": mais_recente["data_referencia"],
            "trimestres_ltm": len(ultimos4),
            # DRE LTM — soma dos _q disponíveis
            "receita_liquida_ltm": ltm("receita_liquida_q"),
            "lucro_bruto_ltm": ltm("lucro_bruto_q"),
            "ebit_ltm": ltm("ebit_q"),
            "ebitda_ltm": ltm("ebitda_q"),
            "lucro_liquido_ltm": ltm("lucro_liquido_q"),
            # Balanco — trimestre mais recente
            "ativo_total": mais_recente.get("ativo_total"),
            "ativo_circulante": mais_recente.get("ativo_circulante"),
            "passivo_circulante": mais_recente.get("passivo_circulante"),
            "patrimonio_liquido": mais_recente.get("patrimonio_liquido"),
            "caixa": mais_recente.get("caixa"),
            "divida_bruta": mais_recente.get("divida_bruta"),
            "divida_liquida": mais_recente.get("divida_liquida"),
            "quantidade_acoes": mais_recente.get("quantidade_acoes"),
        }
        resultados.append(row)

    df_out = pd.DataFrame(resultados)

    for col in ["receita_liquida_ltm", "ativo_total", "patrimonio_liquido",
                "quantidade_acoes", "ebit_ltm"]:
        if col in df_out.columns:
            df_out[col] = pd.to_numeric(df_out[col], errors="coerce")

    # Filtro mínimo: precisa de receita LTM positiva, PL e quantidade de ações
    mask = (
        df_out["receita_liquida_ltm"].notna() &
        (df_out["receita_liquida_ltm"] > 0) &
        df_out["patrimonio_liquido"].notna() &
        (df_out["patrimonio_liquido"] != 0) &
        df_out["quantidade_acoes"].notna() &
        (df_out["quantidade_acoes"] > 0)
    )
    df_out = df_out[mask].copy()

    print(f"  {len(df_out)} tickers com LTM válido.")
    return df_out


def buscar_cotacoes() -> pd.DataFrame:
    print("Buscando cotacoes (ultimos 30 dias)...")

    data_limite = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

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
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
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
    print("Calculando CAGR 5 anos (base T4)...")

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

    rows = []
    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("ano")
        ano_max = grp["ano"].max()
        base = grp[grp["ano"] == ano_max - 5]

        if base.empty:
            continue

        atual = grp[grp["ano"] == ano_max].iloc[0]
        b = base.iloc[0]

        rec_cagr = (
            (atual["receita_liquida_ytd"] / b["receita_liquida_ytd"]) ** (1 / 5) - 1
            if pd.notna(b["receita_liquida_ytd"]) and b["receita_liquida_ytd"] > 0
            and pd.notna(atual["receita_liquida_ytd"])
            else np.nan
        )
        luc_cagr = (
            (atual["lucro_liquido_ytd"] / b["lucro_liquido_ytd"]) ** (1 / 5) - 1
            if pd.notna(b["lucro_liquido_ytd"]) and b["lucro_liquido_ytd"] > 0
            and pd.notna(atual["lucro_liquido_ytd"])
            else np.nan
        )

        rows.append({"ticker": ticker, "cagr_receita_5a": rec_cagr, "cagr_lucro_5a": luc_cagr})

    result = pd.DataFrame(rows)
    print(f"  CAGR calculado para {len(result)} tickers.")
    return result


def calcular_e_salvar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr):
    if df_cot.empty:
        print("Sem cotacoes. Abortando.")
        return

    print("Calculando indicadores...")

    df = (
        df_fund
        .merge(df_cot, on="ticker", how="inner")
        .merge(df_div_12m, on="ticker", how="left")
        .merge(df_div_6a, on="ticker", how="left")
    )

    if not df_cagr.empty:
        df = df.merge(df_cagr, on="ticker", how="left")
    else:
        df["cagr_receita_5a"] = np.nan
        df["cagr_lucro_5a"] = np.nan

    df["dividendos_12m"] = pd.to_numeric(df["dividendos_12m"], errors="coerce").fillna(0)
    df["dividendos_6a_media"] = pd.to_numeric(df["dividendos_6a_media"], errors="coerce").fillna(0)
    df["volume_medio_diario"] = pd.to_numeric(df["volume_medio_diario"], errors="coerce").fillna(0)

    for col in ["ativo_total", "ativo_circulante", "passivo_circulante",
                "patrimonio_liquido", "caixa", "divida_bruta", "divida_liquida",
                "quantidade_acoes", "preco_atual"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Por ação
    df["lpa"] = df["lucro_liquido_ltm"] / df["quantidade_acoes"]
    df["vpa"] = df["patrimonio_liquido"] / df["quantidade_acoes"]

    mc = df["preco_atual"] * df["quantidade_acoes"]
    div_liq = df["divida_liquida"].fillna(0)
    ev = mc + div_liq

    # Múltiplos — divisão segura
    def safe_div(a, b):
        result = a / b.replace(0, np.nan)
        return result.where(b.notna() & (b != 0))

    df["p_l"] = safe_div(mc, df["lucro_liquido_ltm"])
    df["p_vp"] = df["preco_atual"] / df["vpa"].replace(0, np.nan)
    df["p_receita"] = safe_div(mc, df["receita_liquida_ltm"])
    df["p_ativo"] = safe_div(mc, df["ativo_total"])
    cap_giro = df["ativo_circulante"] - df["passivo_circulante"]
    df["p_cap_giro"] = safe_div(mc, cap_giro)
    df["p_ativo_circ_liq"] = df["p_cap_giro"]
    df["p_ebit"] = safe_div(mc, df["ebit_ltm"])
    df["p_ebitda"] = safe_div(mc, df["ebitda_ltm"])
    df["ev_ebit"] = safe_div(ev, df["ebit_ltm"])
    df["ev_ebitda"] = safe_div(ev, df["ebitda_ltm"])

    # Rentabilidade
    df["roe"] = safe_div(df["lucro_liquido_ltm"], df["patrimonio_liquido"])
    df["roa"] = safe_div(df["lucro_liquido_ltm"], df["ativo_total"])
    cap_inv = df["patrimonio_liquido"] + div_liq
    df["roic"] = safe_div(df["ebit_ltm"] * (1 - TAXA_IMPOSTO), cap_inv)
    df["giro_ativos"] = safe_div(df["receita_liquida_ltm"], df["ativo_total"])

    # Margens
    rec = df["receita_liquida_ltm"].replace(0, np.nan)
    df["margem_bruta"] = df["lucro_bruto_ltm"] / rec
    df["margem_ebit"] = df["ebit_ltm"] / rec
    df["margem_ebitda"] = df["ebitda_ltm"] / rec
    df["margem_liquida"] = df["lucro_liquido_ltm"] / rec

    # Endividamento
    df["div_liq_ativos"] = safe_div(div_liq, df["ativo_total"])
    df["div_liq_pl"] = safe_div(div_liq, df["patrimonio_liquido"])
    df["div_liq_ebit"] = safe_div(div_liq, df["ebit_ltm"])
    df["div_liq_ebitda"] = safe_div(div_liq, df["ebitda_ltm"])
    df["liquidez_corrente"] = safe_div(df["ativo_circulante"], df["passivo_circulante"])
    df["passivos_ativos"] = safe_div(df["ativo_total"] - df["patrimonio_liquido"], df["ativo_total"])
    df["pl_ativos"] = safe_div(df["patrimonio_liquido"], df["ativo_total"])

    # DY
    df["dy_atual"] = df["dividendos_12m"] / df["preco_atual"].replace(0, np.nan)

    # Valuation
    df["preco_justo_graham"] = np.sqrt(
        np.maximum(0, 22.5 * df["lpa"].clip(lower=0) * df["vpa"].clip(lower=0))
    )
    df["preco_justo_graham_br"] = np.sqrt(
        np.maximum(0, 15 * df["lpa"].clip(lower=0) * df["vpa"].clip(lower=0))
    )
    df["preco_justo_bazin"] = df["dividendos_12m"] / 0.06
    df["preco_teto_medio"] = df["dividendos_6a_media"] / 0.06

    df["preco_justo_lynch"] = np.where(
        df["cagr_lucro_5a"].notna() & (df["cagr_lucro_5a"] > 0) & (df["cagr_lucro_5a"] <= 0.50),
        df["lpa"] * (df["cagr_lucro_5a"] * 100),
        np.nan,
    )

    for metodo in ["graham", "graham_br", "bazin", "lynch"]:
        col_pj = f"preco_justo_{metodo}"
        df[f"{metodo}_upside"] = np.where(
            df["preco_atual"].notna() & (df["preco_atual"] > 0) & df[col_pj].notna(),
            (df[col_pj] / df["preco_atual"] - 1) * 100,
            np.nan,
        )
    df["agf_upside"] = np.where(
        df["preco_atual"].notna() & (df["preco_atual"] > 0) & df["preco_teto_medio"].notna(),
        (df["preco_teto_medio"] / df["preco_atual"] - 1) * 100,
        np.nan,
    )

    df["pl_absoluto"] = df["patrimonio_liquido"]
    df["data_calculo"] = datetime.now(UTC).date().isoformat()
    df["data_balanco"] = pd.to_datetime(df["data_referencia"], errors="coerce").dt.strftime("%Y-%m-%d")

    df = df.rename(columns={
        "receita_liquida_ltm": "receita_liquida",
        "lucro_liquido_ltm": "lucro_liquido",
        "ebit_ltm": "ebit",
    })

    cols_saida = [
        "ticker", "ano", "data_calculo", "data_balanco", "preco_atual",
        "dy_atual", "p_l", "p_vp", "p_receita", "p_ativo", "p_cap_giro",
        "p_ativo_circ_liq", "p_ebit", "p_ebitda", "ev_ebit", "ev_ebitda",
        "roe", "roa", "roic", "giro_ativos",
        "margem_bruta", "margem_ebit", "margem_ebitda", "margem_liquida",
        "liquidez_corrente", "passivos_ativos", "pl_ativos",
        "div_liq_ativos", "div_liq_pl", "div_liq_ebit", "div_liq_ebitda",
        "cagr_receita_5a", "cagr_lucro_5a",
        "receita_liquida", "lucro_liquido", "ebit",
        "lpa", "vpa",
        "preco_justo_graham", "graham_upside",
        "preco_justo_graham_br", "graham_br_upside",
        "preco_justo_bazin", "bazin_upside",
        "preco_justo_lynch", "lynch_upside",
        "preco_teto_medio", "agf_upside",
        "pl_absoluto", "dividendos_12m", "dividendos_6a_media",
        "volume_medio_diario",
    ]

    df_out = df[[c for c in cols_saida if c in df.columns]].copy()
    df_out = df_out.replace({np.inf: None, -np.inf: None})

    # Converte NaN para None (JSON serializável)
    for col in df_out.select_dtypes(include=[np.number]).columns:
        df_out[col] = df_out[col].where(df_out[col].notna(), other=None)

    df_out = df_out.drop_duplicates(subset=["ticker"], keep="last")

    registros = df_out.to_dict("records")
    print(f"Salvando {len(registros)} registros...")

    lote = 100
    erros = 0
    salvos = 0
    for i in range(0, len(registros), lote):
        try:
            supabase.table("indicadores").upsert(
                registros[i: i + lote],
                on_conflict="ticker,data_calculo",
            ).execute()
            salvos += len(registros[i: i + lote])
        except Exception as e:
            erros += 1
            print(f"  Erro no lote {i}: {e}")

    print(f"Concluido. {salvos} registros salvos, {erros} lotes com erro.")


def main():
    print("Iniciando calculo de indicadores (LTM)...")

    df_fund = buscar_fundamentos()
    if df_fund.empty:
        print("Sem fundamentos. Abortando.")
        return

    df_cot = buscar_cotacoes()
    df_div = buscar_dividendos()
    df_div_12m, df_div_6a = calcular_dividendos(df_div)
    df_cagr = calcular_cagr(df_fund)

    calcular_e_salvar(df_fund, df_cot, df_div_12m, df_div_6a, df_cagr)

    print("\n========== FINAL ==========")
    print("Indicadores calculados com sucesso.")


if __name__ == "__main__":
    main()
