"""
ETL - Score CS 2.0

Calcula o Score CS para todas as empresas.

Fluxo:

indicadores
+
empresas
+
metricas_score
=
score_cs
"""

import pandas as pd

from etl.database.supabase_client import supabase


# ==========================================================
# BUSCAR ÚLTIMO CÁLCULO
# ==========================================================

print("Buscando data do último cálculo...")

resp = (
    supabase.table("indicadores")
    .select("data_calculo")
    .order("data_calculo", desc=True)
    .limit(1)
    .execute()
)

if not resp.data:
    raise Exception("Nenhum cálculo encontrado.")

data_calculo = resp.data[0]["data_calculo"]

print(f"Data encontrada: {data_calculo}")


# ==========================================================
# INDICADORES
# ==========================================================

print("Carregando indicadores...")

dados = []
offset = 0

while True:

    chunk = (
        supabase
        .table("indicadores")
        .select("*")
        .eq("data_calculo", data_calculo)
        .range(offset, offset + 999)
        .execute()
        .data
    )

    dados.extend(chunk)

    if len(chunk) < 1000:
        break

    offset += 1000

indicadores = pd.DataFrame(dados)

print(f"{len(indicadores)} indicadores carregados.")


# ==========================================================
# EMPRESAS
# ==========================================================

print("Carregando empresas...")

dados = []
offset = 0

while True:

    chunk = (
        supabase
        .table("empresas")
        .select(
            "ticker,"
            "setor,"
            "segmento,"
            "anos_listagem"
        )
        .range(offset, offset + 999)
        .execute()
        .data
    )

    dados.extend(chunk)

    if len(chunk) < 1000:
        break

    offset += 1000

empresas = pd.DataFrame(dados)

print(f"{len(empresas)} empresas carregadas.")


# ==========================================================
# MÉTRICAS SETORIAIS
# ==========================================================

print("Carregando métricas setoriais...")

metricas = pd.DataFrame(

    supabase
    .table("metricas_score")
    .select("*")
    .execute()
    .data

)

print(f"{len(metricas)} setores carregados.")


# ==========================================================
# MERGE
# ==========================================================

df = indicadores.merge(
    empresas,
    on="ticker",
    how="left"
)

df = df.merge(
    metricas,
    on="setor",
    how="left"
)

print(f"{len(df)} empresas prontas para cálculo.")

# ==========================================================
# FUNÇÕES DE PONTUAÇÃO
# ==========================================================

def score_roe(roe):

    if pd.isna(roe):
        return 0

    if roe >= 25:
        return 10
    elif roe >= 20:
        return 8
    elif roe >= 15:
        return 6
    elif roe >= 10:
        return 4
    elif roe >= 5:
        return 2
    return 0


def score_roic(roic):

    if pd.isna(roic):
        return 0

    if roic >= 20:
        return 7
    elif roic >= 15:
        return 5
    elif roic >= 10:
        return 3
    elif roic >= 5:
        return 1
    return 0


def score_margem(margem):

    if pd.isna(margem):
        return 0

    if margem >= 20:
        return 5
    elif margem >= 15:
        return 4
    elif margem >= 10:
        return 2
    elif margem >= 5:
        return 1
    return 0


def score_crescimento(valor):

    if pd.isna(valor):
        return 0

    if valor >= 20:
        return 10
    elif valor >= 15:
        return 8
    elif valor >= 10:
        return 6
    elif valor >= 5:
        return 3
    return 0


def score_divida(valor):

    if pd.isna(valor):
        return 0

    if valor < 1:
        return 10
    elif valor < 2:
        return 8
    elif valor < 3:
        return 5
    elif valor < 4:
        return 2
    return 0


def score_liquidez(valor):

    if pd.isna(valor):
        return 0

    if valor >= 2:
        return 5
    elif valor >= 1.5:
        return 4
    elif valor >= 1.2:
        return 3
    elif valor >= 1:
        return 2
    elif valor >= 0.5:
        return 1
    return 0


def score_dy_atual(valor):

    if pd.isna(valor):
        return 0

    if valor >= 8:
        return 5
    elif valor >= 6:
        return 4
    elif valor >= 4:
        return 3
    elif valor >= 2:
        return 2
    return 0


def score_dy_medio(valor):

    if pd.isna(valor):
        return 0

    if valor >= 8:
        return 7
    elif valor >= 6:
        return 6
    elif valor >= 5:
        return 5
    elif valor >= 4:
        return 3
    elif valor >= 2:
        return 1
    return 0


def score_listagem(anos):

    if pd.isna(anos):
        return 0

    if anos >= 20:
        return 5
    elif anos >= 15:
        return 4
    elif anos >= 10:
        return 3
    elif anos >= 5:
        return 2
    return 0

# ==========================================================
# CONSISTÊNCIA DO ROE (5 ANOS)
# ==========================================================

print("Calculando histórico do ROE...")

historico = (
    supabase
    .table("indicadores")
    .select("ticker,ano,roe")
    .order("ano")
    .execute()
)

historico_df = pd.DataFrame(historico.data)


def score_consistencia_roe(ticker):

    hist = historico_df[
        historico_df["ticker"] == ticker
    ].sort_values("ano")

    hist = hist.tail(5)

    qtd = (hist["roe"] >= 10).sum()

    if qtd >= 5:
        return 3
    elif qtd == 4:
        return 2
    elif qtd == 3:
        return 1

    return 0


# ==========================================================
# HISTÓRICO DE DIVIDENDOS
# ==========================================================

print("Calculando histórico de dividendos...")

dividendos = (
    supabase
    .table("dividendos")
    .select("ticker,ano,valor")
    .execute()
)

dividendos_df = pd.DataFrame(dividendos.data)


def score_historico_dividendos(ticker):

    hist = dividendos_df[
        dividendos_df["ticker"] == ticker
    ]

    if hist.empty:
        return 0

    anos = sorted(hist["ano"].unique())

    if len(anos) == 0:
        return 0

    anos = anos[-6:]

    pagos = 0

    for ano in anos:

        total = hist.loc[
            hist["ano"] == ano,
            "valor"
        ].sum()

        if total > 0:
            pagos += 1

    if pagos == 6:
        return 8
    elif pagos == 5:
        return 6
    elif pagos == 4:
        return 4
    elif pagos == 3:
        return 2

    return 0


# ==========================================================
# VALUATION
# ==========================================================

def score_pl(pl, mediana):

    if pd.isna(pl):
        return 0

    if pl <= 0:
        return 0

    pontos = 0

    if pl < 15:
        pontos += 3

    if not pd.isna(mediana):

        if pl < mediana:
            pontos += 3

    return pontos


def score_pvp(pvp, mediana):

    if pd.isna(pvp):
        return 0

    if pvp <= 0:
        return 0

    pontos = 0

    if pvp < 2:
        pontos += 3

    if not pd.isna(mediana):

        if pvp < mediana:
            pontos += 3

    return pontos


def score_ev_ebit(ev, mediana):

    if pd.isna(ev):
        return 0

    if ev <= 0:
        return 0

    if pd.isna(mediana):
        return 0

    if ev < mediana:
        return 3

    return 0


# ==========================================================
# REGRA ESPECIAL
# BANCOS E SEGURADORAS
# ==========================================================

def eh_banco_ou_seguradora(segmento):

    if pd.isna(segmento):
        return False

    segmento = segmento.upper()

    palavras = [

        "BANCO",

        "BANCOS",

        "INTERMEDIÁRIOS FINANCEIROS",

        "INTERMEDIARIOS FINANCEIROS",

        "SEGURADORA",

        "SEGUROS"

    ]

    for palavra in palavras:

        if palavra in segmento:

            return True

    return False

# ==========================================================
# CÁLCULO DO SCORE
# ==========================================================

print("Calculando Score CS...")

resultado = []

for _, row in df.iterrows():

    # ======================================================
    # RENTABILIDADE (25)
    # ======================================================

    rentabilidade = (
        score_roe(row["roe"])
        + score_roic(row["roic"])
        + score_margem(row["margem_liquida"])
        + score_consistencia_roe(row["ticker"])
    )

    # ======================================================
    # CRESCIMENTO (25)
    # ======================================================

    crescimento = (
        score_crescimento(row["cagr_receita_5a"])
        + score_crescimento(row["cagr_lucro_5a"])
        + score_listagem(row["anos_listagem"])
    )

    # ======================================================
    # DIVIDENDOS (20)
    # ======================================================

    dividendos = (
        score_historico_dividendos(row["ticker"])
        + score_dy_atual(row["dy_atual"])
        + score_dy_medio(row["dividendos_6a_media"])
    )

    # ======================================================
    # SEGURANÇA FINANCEIRA
    # ======================================================

    if eh_banco_ou_seguradora(row["segmento"]):

        # redistribuição definida
        seguranca = (
            score_liquidez(row["liquidez_corrente"])
        )

        rentabilidade += 5
        crescimento += 5
        dividendos += 5

    else:

        seguranca = (
            score_divida(row["div_liq_ebitda"])
            + score_liquidez(row["liquidez_corrente"])
        )

    # ======================================================
    # VALUATION
    # ======================================================

    valuation = (

        score_pl(
            row["p_l"],
            row["pl_mediano"]
        )

        +

        score_pvp(
            row["p_vp"],
            row["pvp_mediano"]
        )

        +

        score_ev_ebit(
            row["ev_ebit"],
            row["ev_ebit_mediano"]
        )

    )

    # ======================================================
    # SCORE FINAL
    # ======================================================

    score = (

        rentabilidade

        + crescimento

        + seguranca

        + dividendos

        + valuation

    )

    if score > 100:
        score = 100

    resultado.append({

        "ticker": row["ticker"],

        "score_cs": round(score, 2)

    })

resultado_df = pd.DataFrame(resultado)

print("Atualizando Score CS...")

for _, row in resultado_df.iterrows():

    (
        supabase
        .table("indicadores")
        .update({

            "score_cs": row["score_cs"]

        })
        .eq("ticker", row["ticker"])
        .eq("data_calculo", data_calculo)
        .execute()
    )

print("✅ Score CS atualizado com sucesso.")
