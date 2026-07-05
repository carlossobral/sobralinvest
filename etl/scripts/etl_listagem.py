from datetime import datetime
import pandas as pd
import requests
from io import BytesIO
from etl.database.supabase_client import supabase

# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

URL_CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"

# ==========================================================
# DOWNLOAD
# ==========================================================

print("Baixando cadastro CVM...")

r = requests.get(URL_CVM)
r.raise_for_status()

df = pd.read_csv(
    BytesIO(r.content),
    sep=";",
    encoding="latin1"
)

print(f"{len(df)} registros encontrados.")

# ==========================================================
# FILTROS
# ==========================================================

df = df[
    (df["TP_MERC"] == "BOLSA") &
    (df["SIT"] == "ATIVO")
].copy()

# ==========================================================
# NORMALIZA DATA DE REGISTRO
# ==========================================================

df["cd_cvm"] = df["CD_CVM"].astype(str).str.strip()

df["data_registro_cvm"] = pd.to_datetime(
    df["DT_REG"],
    format="%Y-%m-%d",
    errors="coerce"
)

# ==========================================================
# EMPRESAS SUPABASE
# ==========================================================

print("Carregando empresas...")

empresas = (
    supabase
    .table("empresas")
    .select("id,cd_cvm")
    .execute()
)

empresas_df = pd.DataFrame(empresas.data)

empresas_df["cd_cvm"] = empresas_df["cd_cvm"].astype(str).str.strip()

# ==========================================================
# MERGE POR CD_CVM
# ==========================================================

merge = empresas_df.merge(
    df[[
        "cd_cvm",
        "data_registro_cvm"
    ]],
    on="cd_cvm",
    how="left"
)

print(f"{len(merge)} empresas conciliadas.")

# ==========================================================
# UPDATE
# ==========================================================

total = 0

for _, row in merge.iterrows():

    if pd.isna(row["data_registro_cvm"]):
        continue

    supabase.table("empresas").update({
        "data_registro_cvm": row["data_registro_cvm"].strftime("%Y-%m-%d")
    }).eq("id", row["id"]).execute()

    total += 1

print(f"{total} empresas atualizadas.")
