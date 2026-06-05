from datetime import datetime, UTC
from io import BytesIO
from zipfile import ZipFile

import httpx
import pandas as pd

from etl.database.supabase_client import supabase


ANO_INICIAL = 2024
ANO_FINAL = 2024
##ANO_FINAL = datetime.now().year


BASE_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"
)


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "etl_cvm",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def salvar_dataframe(df, tabela):

    if df.empty:
        return 0

    registros = df.to_dict(orient="records")

    lote = 1000

    total = 0

    for i in range(0, len(registros), lote):

        chunk = registros[i:i+lote]

        (
            supabase
            .table(tabela)
            .insert(chunk)
            .execute()
        )

        total += len(chunk)

    return total


def tratar_df(df):

    colunas = {
        "CNPJ_CIA": "cnpj_cia",
        "CD_CVM": "cd_cvm",
        "DENOM_CIA": "empresa",
        "DT_REFER": "dt_referencia",
        "VERSAO": "versao",
        "GRUPO_DFP": "grupo_dfp",
        "CD_CONTA": "codigo_conta",
        "DS_CONTA": "descricao_conta",
        "VL_CONTA": "valor",
    }

    existentes = [
        c
        for c in colunas
        if c in df.columns
    ]

    df = df[existentes].copy()

    df.columns = [
        colunas[c]
        for c in existentes
    ]

if "dt_referencia" in df.columns:
    df["dt_referencia"] = (
        pd.to_datetime(
            df["dt_referencia"],
            errors="coerce"
        )
        .dt.strftime("%Y-%m-%d")
    )


def processar_zip(ano):

    url = f"{BASE_URL}/dfp_cia_aberta_{ano}.zip"

    print()
    print(f"Baixando {ano}")

    response = httpx.get(
        url,
        timeout=300
    )

    if response.status_code != 200:
        print("Arquivo não encontrado")
        return 0

    total = 0

    with ZipFile(BytesIO(response.content)) as z:

        arquivos = z.namelist()

        for nome in arquivos:

            try:

                if "DRE_con" in nome:

                    print(f"DRE: {nome}")

                    df = pd.read_csv(
                        z.open(nome),
                        sep=";",
                        decimal=",",
                        encoding="latin1"
                    )

                    total += salvar_dataframe(
                        tratar_df(df),
                        "cvm_dre"
                    )

                elif "BPA_con" in nome:

                    print(f"BPA: {nome}")

                    df = pd.read_csv(
                        z.open(nome),
                        sep=";",
                        decimal=",",
                        encoding="latin1"
                    )

                    total += salvar_dataframe(
                        tratar_df(df),
                        "cvm_bpa"
                    )

                elif "BPP_con" in nome:

                    print(f"BPP: {nome}")

                    df = pd.read_csv(
                        z.open(nome),
                        sep=";",
                        decimal=",",
                        encoding="latin1"
                    )

                    total += salvar_dataframe(
                        tratar_df(df),
                        "cvm_bpp"
                    )

                elif "DFC_MI_con" in nome:

                    print(f"DFC: {nome}")

                    df = pd.read_csv(
                        z.open(nome),
                        sep=";",
                        decimal=",",
                        encoding="latin1"
                    )

                    total += salvar_dataframe(
                        tratar_df(df),
                        "cvm_dfc"
                    )

            except Exception as e:

                print(
                    f"Erro arquivo {nome}: {e}"
                )

    return total


def main():

    total = 0

    try:

        for ano in range(
            ANO_INICIAL,
            ANO_FINAL + 1
        ):

            total += processar_zip(ano)

        registrar_carga(
            "SUCESSO",
            total,
            f"{total} registros CVM carregados"
        )

        print()
        print("========== FINAL ==========")
        print(f"Registros: {total}")

    except Exception as e:

        registrar_carga(
            "ERRO",
            0,
            str(e)
        )

        raise


if __name__ == "__main__":
    main()
