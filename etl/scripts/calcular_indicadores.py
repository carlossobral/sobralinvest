from datetime import datetime, UTC, timedelta
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
                return None
            vals = pd.to_numeric(ultimos4[col], errors="coerce").dropna()
            return float(vals.sum()) if len(vals) >= 1 else None

        def bal(col):
            v = mais_recente.get(col)
            return safe_float(v)

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
            "ativo_total": bal("ativo_total"),
            "ativo_circulante": bal("ativo_circulante"),
            "passivo_circulante": bal("passivo_circulante"),
            "patrimonio_liquido": bal("patrimonio_liquido"),
            "caixa": bal("caixa"),
            "divida_bruta": bal("divida_bruta"),
            "divida_liquida": bal("divida_liquida"),
            "quantidade_acoes": bal("quantidade_acoes"),
        }
        resultados.append(row)

    df_out = pd.DataFrame(resultados)

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
    """
    Cálculo de CAGR otimizado usando operações vetorizadas do Pandas (shift e np.where)
    em vez de iteração linha a linha, garantindo muito mais performance.
    """
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

    # Ordenar para garantir que o shift(5) pegue exatamente 5 anos atrás
    df = df.sort_values(["ticker", "ano"]).reset_index(drop=True)

    # Criar colunas com os valores de 5 anos atrás usando groupby e shift
    df["rec_5a_ago"] = df.groupby("ticker")["receita_liquida_ytd"].shift(5)
    df["luc_5a_ago"] = df.groupby("ticker")["lucro_liquido_ytd"].shift(5)

    # Manter apenas o ano mais recente de cada ticker
    df_latest = df.loc[df.groupby("ticker")["ano"].idxmax()].copy()

    # Calcular CAGR de forma vetorizada (muito mais rápido que loop)
    # Condição: base > 0 e valores não nulos
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
    
    # Aplicar safe_float para garantir limpeza dos dados
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

    df = (
        df_fund
        .merge(df_cot, on="ticker", how="inner")
        .merge(df_div_12m, on="ticker", how="left")
        .merge(df_div_6a, on="ticker", how="left")
    )

    if not df_cagr.empty:
        df = df.merge(df_cagr, on="ticker", how="left")
    else:
        df["cagr_receita_5a"] = None
        df["cagr_lucro_5a"] = None

    for col in ["dividendos_12m", "dividendos_6a_media", "volume_medio_diario",
                "ativo_total", "ativo_circulante", "passivo_circulante",
                "patrimonio_liquido", "caixa", "divida_bruta", "divida_liquida",
                "quantidade_acoes", "preco_atual"]:
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

    # ============================================================
    # MUDANÇA CRÍTICA: Calcular quantidade total de ações por CD_CVM
    # ============================================================
    print("Calculando quantidade total de ações por CD_CVM...")
    
    # Buscar todos os tickers e suas quantidades de ações da tabela empresas
    empresas_data = []
    offset = 0
    while True:
        chunk = (
            supabase.table("empresas")
            .select("ticker, cd_cvm, quantidade_acoes")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        empresas_data.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    
    df_empresas = pd.DataFrame(empresas_data)
    df_empresas["quantidade_acoes"] = pd.to_numeric(df_empresas["quantidade_acoes"], errors="coerce")
    
    # Agrupar por CD_CVM e somar as quantidades de ações
    acoes_por_cdcvm = (
        df_empresas.groupby("cd_cvm")["quantidade_acoes"]
        .sum()
        .reset_index()
        .rename(columns={"quantidade_acoes": "quantidade_acoes_consolidada"})
    )
    
    # Criar mapa ticker -> quantidade_acoes_consolidada
    ticker_para_cdcvm = df_empresas[["ticker", "cd_cvm"]].drop_duplicates()
    ticker_para_acoes_consolidada = ticker_para_cdcvm.merge(
        acoes_por_cdcvm, on="cd_cvm", how="left"
    )
    
    # Converter para dicionário para acesso rápido
    mapa_acoes_consolidadas = dict(
        zip(ticker_para_acoes_consolidada["ticker"], 
            ticker_para_acoes_consolidada["quantidade_acoes_consolidada"])
    )
    
    print(f"  Total de ações consolidadas calculado para {len(mapa_acoes_consolidadas)} tickers.")
    # ============================================================

    registros_saida = []

    for _, row in df.iterrows():
        t = row.get
        p = safe_float(t("preco_atual"))
        
        # USAR QUANTIDADE CONSOLIDADA DO CD_CVM PARA LPA E VPA
        ticker_atual = row["ticker"]
        qty_consolidada = safe_float(mapa_acoes_consolidadas.get(ticker_atual))
        
        # Manter quantidade individual para Market Cap e outros cálculos
        qty_individual = safe_float(t("quantidade_acoes"))
        
        pl = safe_float(t("patrimonio_liquido"))
        at = safe_float(t("ativo_total"))
        ac = safe_float(t("ativo_circulante"))
        pc = safe_float(t("passivo_circulante"))
        div_liq = safe_float(t("divida_liquida")) or 0.0
        rec = safe_float(t("receita_liquida"))
        ll = safe_float(t("lucro_liquido"))
        ebit = safe_float(t("ebit"))
        ebitda = safe_float(t("ebitda_ltm"))
        lb = safe_float(t("lucro_bruto_ltm"))
        div12m = safe_float(t("dividendos_12m")) or 0.0
        div6a = safe_float(t("dividendos_6a_media")) or 0.0

        # Market Cap usa quantidade individual do ticker
        mc = (p * qty_individual) if (p and qty_individual) else None
        
        ev = (mc + div_liq) if mc is not None else None
        
        # LPA e VPA usam quantidade consolidada do CD_CVM (VALORES EXATOS, SEM ARREDONDAMENTO)
        lpa = sd(ll, qty_consolidada)
        vpa = sd(pl, qty_consolidada)
        
        cap_giro = (ac - pc) if (ac is not None and pc is not None) else None
        cap_inv = (pl + div_liq) if pl is not None else None

        rec_dict = {
            "ticker": row["ticker"],
            "ano": row.get("ano"),
            "data_calculo": row["data_calculo"],
            "data_balanco": row["data_balanco"],
            "preco_atual": p,
            "dy_atual": sd(div12m, p),
            "p_l": sd(p, lpa),
            "p_vp": sd(p, vpa),
            "p_receita": sd(mc, safe_float(t("receita_liquida"))),
            "p_ativo": sd(mc, at),
            "p_cap_giro": sd(mc, cap_giro),
            "p_ativo_circ_liq": sd(mc, cap_giro),
            "p_ebit": sd(mc, ebit),
            "p_ebitda": sd(mc, ebitda),
            "ev_ebit": sd(ev, ebit),
            "ev_ebitda": sd(ev, ebitda),
            "roe": sd(ll, pl),
            "roa": sd(ll, at),
            "roic": sd(ebit * (1 - TAXA_IMPOSTO) if ebit else None, cap_inv),
            "giro_ativos": sd(safe_float(t("receita_liquida")), at),
            "margem_bruta": sd(lb, safe_float(t("receita_liquida"))),
            "margem_ebit": sd(ebit, safe_float(t("receita_liquida"))),
            "margem_ebitda": sd(ebitda, safe_float(t("receita_liquida"))),
            "margem_liquida": sd(ll, safe_float(t("receita_liquida"))),
            "liquidez_corrente": sd(ac, pc),
            "passivos_ativos": sd((at - pl) if (at and pl) else None, at),
            "pl_ativos": sd(pl, at),
            "div_liq_ativos": sd(div_liq, at),
            "div_liq_pl": sd(div_liq, pl),
            "div_liq_ebit": sd(div_liq, ebit),
            "div_liq_ebitda": sd(div_liq, ebitda),
            "cagr_receita_5a": safe_float(t("cagr_receita_5a")),
            "cagr_lucro_5a": safe_float(t("cagr_lucro_5a")),
            "receita_liquida": safe_float(t("receita_liquida")),
            "lucro_liquido": ll,
            "ebit": ebit,
            "lpa": lpa,
            "vpa": vpa,
            "preco_justo_graham": safe_float(
                math.sqrt(max(0, 22.5 * (lpa or 0) * (vpa or 0))) if (lpa and lpa > 0 and vpa and vpa > 0) else None
            ),
            "preco_justo_graham_br": safe_float(
                math.sqrt(max(0, 15 * (lpa or 0) * (vpa or 0))) if (lpa and lpa > 0 and vpa and vpa > 0) else None
            ),
            "preco_justo_bazin": (div12m / 0.06) if div12m > 0 else None,
            "preco_teto_medio": (div6a / 0.06) if div6a > 0 else None,
            "preco_justo_lynch": None,  # calculado abaixo
            "dividendos_12m": div12m,
            "dividendos_6a_media": div6a,
            "pl_absoluto": pl,
            "volume_medio_diario": safe_float(t("volume_medio_diario")),
        }

        # Graham upside
        for metodo, campo in [
            ("graham", "preco_justo_graham"),
            ("graham_br", "preco_justo_graham_br"),
            ("bazin", "preco_justo_bazin"),
        ]:
            pj = rec_dict.get(campo)
            rec_dict[f"{metodo}_upside"] = sd((pj / p - 1) * 100 if (pj and p) else None, 1)

        # Lynch
        cagr_luc = safe_float(t("cagr_lucro_5a"))
        if cagr_luc and 0 < cagr_luc <= 0.50 and lpa:
            rec_dict["preco_justo_lynch"] = safe_float(lpa * (cagr_luc * 100))
            
        rec_dict["lynch_upside"] = sd(
            ((rec_dict["preco_justo_lynch"] / p - 1) * 100
             if rec_dict["preco_justo_lynch"] and p else None),
            1
        )

        # AGF
        pt = rec_dict.get("preco_teto_medio")
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
    print("Iniciando calculo de indicadores (LTM)...")

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
