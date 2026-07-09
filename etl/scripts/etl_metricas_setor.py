"""
ETL - Métricas Setoriais

Calcula as medianas por setor utilizadas pelo CS Score.

Origem:
- empresas
- indicadores

Destino:
- metricas_score
"""

from datetime import date

import pandas as pd

from etl.database.supabase_client import supabase

# ==========================================================
# CARREGA EMPRESAS
# ==========================================================

print("Carregando empresas...")

empresas = (
    supabase
    .table("empresas")
    .select("ticker,setor")
    .execute()
)

empresas_df = pd.DataFrame(empresas.data)

# ==========================================================
# CARREGA INDICADORES
# ==========================================================

print("Carregando indicadores...")

indicadores = (
    supabase
    .table("indicadores")
    .select(
        """
        ticker,
        pl,
        pvp,
        ev_ebit,
        roe,
        roic,
        dy_atual,
        div_liq_ebitda
        """
    )
    .execute()
)

indicadores_df = pd.DataFrame(indicadores.data)

# ==========================================================
# MERGE
# ==========================================================

df = indicadores_df.merge(
    empresas_df,
    on="ticker",
    how="inner"
)

print(f"{len(df)} empresas carregadas.")

# ==========================================================
# CONVERTE PARA NUMÉRICO
# ==========================================================

colunas = [
    "pl",
    "pvp",
    "ev_ebit",
    "roe",
    "roic",
    "dy_atual",
    "div_liq_ebitda"
]

for coluna in colunas:
    df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

# ==========================================================
# FUNÇÃO MEDIANA
# ==========================================================

def mediana_positiva(serie):

    serie = serie.dropna()
    serie = serie[serie > 0]

    if len(serie) == 0:
        return None

    return float(serie.median())

# ==========================================================
# CALCULA MÉTRICAS POR SETOR
# ==========================================================

print("Calculando métricas...")

resultado = []

for setor, grupo in df.groupby("setor"):

    registro = {

        "setor": setor,

        "pl_mediano":
            mediana_positiva(grupo["pl"]),

        "pvp_mediano":
            mediana_positiva(grupo["pvp"]),

        "ev_ebit_mediano":
            mediana_positiva(grupo["ev_ebit"]),

        "roe_mediano":
            mediana_positiva(grupo["roe"]),

        "roic_mediano":
            mediana_positiva(grupo["roic"]),

        "dy_mediano":
            mediana_positiva(grupo["dy_atual"]),

        "div_liq_ebitda_mediano":
            mediana_positiva(grupo["div_liq_ebitda"]),

        "empresas_setor":
            int(len(grupo)),

        "data_atualizacao":
            date.today().isoformat()

    }

    resultado.append(registro)

metricas_df = pd.DataFrame(resultado)

print(metricas_df)

# ==========================================================
# UPSERT
# ==========================================================

print("Atualizando metricas_score...")

dados = metricas_df.to_dict(orient="records")

(
    supabase
    .table("metricas_score")
    .upsert(
        dados,
        on_conflict="setor"
    )
    .execute()
)

print(f"{len(metricas_df)} setores atualizados.")

print("Concluído.")
