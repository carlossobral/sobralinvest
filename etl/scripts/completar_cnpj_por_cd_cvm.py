from io import BytesIO

import httpx
import pandas as pd

from etl.database.supabase_client import supabase


URL_CVM = (
    "https://dados.cvm.gov.br/dados/"
    "CIA_ABERTA/CAD/DADOS/"
    "cad_cia_aberta.csv"
)


def carregar_cadastro_cvm():

    print("Baixando cadastro CVM...")

    response = httpx.get(
        URL_CVM,
        timeout=300,
        follow_redirects=True,
    )

    response.raise_for_status()

    return pd.read_csv(
        BytesIO(response.content),
        sep=";",
        encoding="latin1",
        low_memory=False,
    )


def carregar_empresas():

    resultado = (
        supabase
        .table("empresas")
        .select(
            "ticker,cd_cvm"
        )
        .not_.is_("cd_cvm", "null")
        .execute()
    )

    return resultado.data


def main():

    empresas = carregar_empresas()

    cadastro = carregar_cadastro_cvm()

    cadastro["CD_CVM"] = pd.to_numeric(
        cadastro["CD_CVM"],
        errors="coerce"
    )

    atualizados = 0

    for empresa in empresas:

        ticker = empresa["ticker"]

        cd_cvm = empresa["cd_cvm"]

        linha = cadastro[
            cadastro["CD_CVM"] == cd_cvm
        ]

        if linha.empty:
            continue

        cnpj = str(
            linha.iloc[0]["CNPJ_CIA"]
        )

        (
            supabase
            .table("empresas")
            .update(
                {
                    "cnpj": cnpj
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
            f"{ticker} -> {cnpj}"
        )

    print()
    print("========== FINAL ==========")
    print(
        f"CNPJs atualizados: {atualizados}"
    )


if __name__ == "__main__":
    main()
