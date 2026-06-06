from io import BytesIO
from zipfile import ZipFile

import httpx
import pandas as pd

from etl.database.supabase_client import supabase


ANOS = [2024]


BASE_URL = (
    "https://dados.cvm.gov.br/dados/"
    "CIA_ABERTA/DOC/ITR/DADOS"
)


CONTA_RECEITA = "3.01"
CONTA_LUCRO = "3.11"

CONTA_ATIVO_TOTAL = "1"
CONTA_ATIVO_CIRC = "1.01"

CONTA_PASSIVO_TOTAL = "2"
CONTA_PASSIVO_CIRC = "2.01"

CONTA_PL = "2.03"


def baixar_zip(ano: int):

    url = f"{BASE_URL}/itr_cia_aberta_{ano}.zip"

    response = httpx.get(
        url,
        timeout=300,
        follow_redirects=True,
    )

    response.raise_for_status()

    return ZipFile(BytesIO(response.content))


def carregar_csv(zip_file, nome):

    with zip_file.open(nome) as f:

        return pd.read_csv(
            f,
            sep=";",
            encoding="latin1",
            low_memory=False,
        )


def normalizar_nome(nome):

    if pd.isna(nome):
        return ""

    return (
        str(nome)
        .upper()
        .strip()
    )


def carregar_empresas():

    resultado = (
        supabase
        .table("empresas")
        .select("ticker,nome")
        .execute()
    )

    mapa = {}

    for item in resultado.data:

        nome = normalizar_nome(
            item["nome"]
        )

        mapa[nome] = item["ticker"]

    return mapa


def obter_valor(df, conta):

    linha = df[
        df["CD_CONTA"] == conta
    ]

    if linha.empty:
        return None

    try:
        return float(
            linha.iloc[0]["VL_CONTA"]
        )

    except Exception:
        return None


def processar_empresa(
    ticker,
    ano,
    trimestre,
    dre_empresa,
    bpa_empresa,
    bpp_empresa,
):

    receita = obter_valor(
        dre_empresa,
        CONTA_RECEITA,
    )

    lucro = obter_valor(
        dre_empresa,
        CONTA_LUCRO,
    )

    ativo_total = obter_valor(
        bpa_empresa,
        CONTA_ATIVO_TOTAL,
    )

    ativo_circ = obter_valor(
        bpa_empresa,
        CONTA_ATIVO_CIRC,
    )

    passivo_total = obter_valor(
        bpp_empresa,
        CONTA_PASSIVO_TOTAL,
    )

    passivo_circ = obter_valor(
        bpp_empresa,
        CONTA_PASSIVO_CIRC,
    )

    pl = obter_valor(
        bpp_empresa,
        CONTA_PL,
    )

    registro = {

        "ticker": ticker,

        "ano": ano,

        "trimestre": trimestre,

        "receita_liquida": receita,

        "lucro_liquido": lucro,

        "ativo_total": ativo_total,

        "ativo_circulante": ativo_circ,

        "passivo_total": passivo_total,

        "passivo_circulante": passivo_circ,

        "patrimonio_liquido": pl,
    }

    (
        supabase
        .table(
            "fundamentos_trimestrais"
        )
        .upsert(
            registro,
            on_conflict=(
                "ticker,ano,trimestre"
            )
        )
        .execute()
    )


def processar_ano(ano):

    print()
    print(f"Baixando ITR {ano}")

    zip_file = baixar_zip(ano)

    dre = carregar_csv(
        zip_file,
        f"itr_cia_aberta_DRE_con_{ano}.csv"
    )

    bpa = carregar_csv(
        zip_file,
        f"itr_cia_aberta_BPA_con_{ano}.csv"
    )

    bpp = carregar_csv(
        zip_file,
        f"itr_cia_aberta_BPP_con_{ano}.csv"
    )

    empresas = carregar_empresas()

    total = 0

    nomes_cvm = (
        dre["DENOM_CIA"]
        .dropna()
        .unique()
    )

    for nome_cia in nomes_cvm:

        ticker = empresas.get(
            normalizar_nome(
                nome_cia
            )
        )

        if not ticker:
            continue

        dre_empresa = dre[
            dre["DENOM_CIA"]
            == nome_cia
        ]

        bpa_empresa = bpa[
            bpa["DENOM_CIA"]
            == nome_cia
        ]

        bpp_empresa = bpp[
            bpp["DENOM_CIA"]
            == nome_cia
        ]

        datas = (
            dre_empresa["DT_REFER"]
            .dropna()
            .unique()
        )

        for data_ref in datas:

            try:

                data_ref = pd.to_datetime(
                    data_ref
                )

                trimestre = (
                    (data_ref.month - 1)
                    // 3
                ) + 1

                dre_trim = dre_empresa[
                    dre_empresa["DT_REFER"]
                    == str(
                        data_ref.date()
                    )
                ]

                bpa_trim = bpa_empresa[
                    bpa_empresa["DT_REFER"]
                    == str(
                        data_ref.date()
                    )
                ]

                bpp_trim = bpp_empresa[
                    bpp_empresa["DT_REFER"]
                    == str(
                        data_ref.date()
                    )
                ]

                processar_empresa(
                    ticker=ticker,
                    ano=ano,
                    trimestre=trimestre,
                    dre_empresa=dre_trim,
                    bpa_empresa=bpa_trim,
                    bpp_empresa=bpp_trim,
                )

                total += 1

            except Exception as e:

                print(
                    f"{ticker}: {e}"
                )

    return total


def main():

    total = 0

    for ano in ANOS:

        total += processar_ano(
            ano
        )

    print()
    print(
        "========== FINAL =========="
    )

    print(
        f"Fundamentos: {total}"
    )


if __name__ == "__main__":
    main()
