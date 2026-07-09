"""
ETL - Métricas Setoriais
Calcula as medianas dos indicadores por setor para o CS Score 2.0.
"""

from datetime import date
import pandas as pd
from etl.database.supabase_client import supabase

# ==========================================================
# 1. BUSCAR A DATA DO ÚLTIMO CÁLCULO
# ==========================================================
print("Buscando data do último cálculo de indicadores...")
resp_data = (
    supabase.table("indicadores")
    .select("data_calculo")
    .order("data_calculo", desc=True)
    .limit(1)
    .execute()
    .data
)

if not resp_data:
    print("❌ Nenhum indicador encontrado. Rode o cálculo de indicadores primeiro.")
    exit()

data_calculo = resp_data[0]["data_calculo"]
print(f"Calculando medianas para a data: {data_calculo}")

# ==========================================================
# 2. BUSCAR EMPRESAS (Paginado)
# ==========================================================
print("Carregando empresas...")
empresas_data = []
offset = 0
while True:
    chunk = (
        supabase.table("empresas")
        .select("ticker, setor, segmento")  # Adicionei segmento para a regra de Bancos
        .range(offset, offset + 999)
        .execute()
        .data
    )
    empresas_data.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

empresas_df = pd.DataFrame(empresas_data)

# ==========================================================
# 3. BUSCAR INDICADORES (Paginado e Filtrado pela Data)
# ==========================================================
print("Carregando indicadores...")
indicadores_data = []
offset = 0
while True:
    chunk = (
        supabase.table("indicadores")
        .select("ticker, p_l, p_vp, ev_ebit, roe, roic, dy_atual, div_liq_ebitda")
        .eq("data_calculo", data_calculo)  # FILTRO CRITICAL: Só o último cálculo!
        .range(offset, offset + 999)
        .execute()
        .data
    )
    indicadores_data.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

indicadores_df = pd.DataFrame(indicadores_data)

# ==========================================================
# 4. MERGE E LIMPEZA
# ==========================================================
df = empresas_df.merge(indicadores_df, on="ticker", how="inner")
print(f"{len(df)} empresas com indicadores válidos encontradas.")

colunas = ["p_l", "p_vp", "ev_ebit", "roe", "roic", "dy_atual", "div_liq_ebitda"]
for coluna in colunas:
    df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

# ==========================================================
# 5. CÁLCULO DAS MEDIANAS
# ==========================================================
def mediana_positiva(serie):
    serie = serie.dropna()
    serie = serie[serie > 0]
    if serie.empty:
        return None
    return round(float(serie.median()), 4)

print("Calculando métricas por setor...")
resultado = []

for setor, grupo in df.groupby("setor"):
    # Evitar calcular mediana para setores com menos de 3 empresas (dado muito frágil)
    if len(grupo) < 3:
        continue 
        
    registro = {
        "setor": setor,
        "pl_mediano": mediana_positiva(grupo["p_l"]),
        "pvp_mediano": mediana_positiva(grupo["p_vp"]),
        "ev_ebit_mediano": mediana_positiva(grupo["ev_ebit"]),
        "roe_mediano": mediana_positiva(grupo["roe"]),
        "roic_mediano": mediana_positiva(grupo["roic"]),
        "dy_mediano": mediana_positiva(grupo["dy_atual"]),
        "div_liq_ebitda_mediano": mediana_positiva(grupo["div_liq_ebitda"]),
        "empresas_setor": len(grupo),
        "data_atualizacao": date.today().isoformat()
    }
    resultado.append(registro)

metricas_df = pd.DataFrame(resultado)

# ==========================================================
# 6. UPSERT NO SUPABASE
# ==========================================================
if not metricas_df.empty:
    print(f"Atualizando metricas_score para {len(metricas_df)} setores...")
    (
        supabase
        .table("metricas_score")
        .upsert(
            metricas_df.to_dict(orient="records"),
            on_conflict="setor"
        )
        .execute()
    )
    print("✅ Concluído.")
else:
    print("❌ Nenhuma métrica calculada.")
