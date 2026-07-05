"""
etl_listagem.py

Atualiza:
- data_registro_cvm
- anos_listagem

Origem:
https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
"""

from datetime import datetime
import pandas as pd
import requests
from io import BytesIO
from supabase import create_client

# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

SUPABASE_URL = ""
SUPABASE_KEY = ""

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
# NORMALIZA CNPJ
# ==========================================================

df["cnpj"] = (
    df["CNPJ_CIA"]
    .str.replace(".", "", regex=False)
    .str.replace("/", "", regex=False)
    .str.replace("-", "", regex=False)
    .str.zfill(14)
)

df["data_registro_cvm"] = pd.to_datetime(
    df["DT_REG"],
    dayfirst=True,
    errors="coerce"
)

hoje = datetime.today()

df["anos_listagem"] = (
    (hoje - df["data_registro_cvm"]).dt.days // 365
)

# ==========================================================
# EMPRESAS SUPABASE
# ==========================================================

print("Carregando empresas...")

empresas = (
    supabase
    .table("empresas")
    .select("id,cnpj")
    .execute()
)

empresas_df = pd.DataFrame(empresas.data)

empresas_df["cnpj"] = empresas_df["cnpj"].astype(str).str.zfill(14)

# ==========================================================
# MERGE
# ==========================================================

merge = empresas_df.merge(
    df[[
        "cnpj",
        "data_registro_cvm",
        "anos_listagem"
    ]],
    on="cnpj",
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

        "data_registro_cvm": row["data_registro_cvm"].strftime("%Y-%m-%d"),
        "anos_listagem": int(row["anos_listagem"])

    }).eq("id", row["id"]).execute()

    total += 1

print(f"{total} empresas atualizadas.")
