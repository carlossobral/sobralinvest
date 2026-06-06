from io import BytesIO
from zipfile import ZipFile

import httpx
import pandas as pd

from etl.database.supabase_client import supabase


URL_CVM = (
    "https://dados.cvm.gov.br/dados/"
    "CIA_ABERTA/CAD/DADOS/"
    "cad_cia_aberta.csv"
)


def normalizar(texto):

    if texto is None:
        return ""

    texto = str(texto)

    texto = texto.upper()

    texto = texto.replace(" S.A.", "")
    texto = texto.replace(" SA", "")
    texto = texto.replace(".", "")
    texto = texto.replace(",", "")
    texto = texto.replace("-", " ")
    texto = texto.replace("/", " ")

    texto = " ".join(texto.split())

    return texto


def carregar_empresas():

    resultado = (
        supabase
        .table("empresas")
        .select("id,ticker,nome")
        .execute()
    )

    return resultado.data


def carregar_cadastro_cvm():

    print("Baixando cadastro CVM...")

    response = httpx.get(
        URL_CVM,
        timeout=300,
        follow_redirects=True,
    )

    response.raise_for_status()

    df = pd.read_csv(
        BytesIO(response.content),
        sep=";",
        encoding="latin1",
        low_memory=False,
    )

    return df


def main():

    empresas = carregar_empresas()

    df_cvm = carregar_cadastro_cvm()

    print(
        f"Empresas banco: {len(empresas)}"
    )

    print(
        f"Empresas CVM: {len(df_cvm)}"
    )

    atualizados = 0

    nao_encontrados = 0

    for empresa in empresas:

        ticker = empresa["ticker"]

        nome = normalizar(
            empresa["nome"]
        )

        match = df_cvm[
            df_cvm["DENOM_SOCIAL"]
            .fillna("")
            .apply(normalizar)
            == nome
        ]

        if match.empty:

            nao_encontrados += 1

            continue

        linha = match.iloc[0]

        cd_cvm = int(
            linha["CD_CVM"]
        )

        (
            supabase
            .table("empresas")
            .update(
                {
                    "cd_cvm": cd_cvm
                }
            )
            .eq(
                "ticker",
                ticker
            )
            .execute()
        )

        atualizados += 1

        print(
            f"{ticker} -> {cd_cvm}"
        )

    print()
    print(
        "========== FINAL =========="
    )

    print(
        f"Atualizados   : {atualizados}"
    )

    print(
        f"Não encontrados: {nao_encontrados}"
    )


if __name__ == "__main__":
    main()
