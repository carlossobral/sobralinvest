from etl.database.supabase_client import supabase


def raiz_ticker(ticker: str):

    return "".join(
        c for c in ticker
        if c.isalpha()
    )


def main():

    resultado = (
        supabase
        .table("empresas")
        .select(
            "ticker,cd_cvm"
        )
        .execute()
    )

    empresas = resultado.data

    mapa = {}

    for empresa in empresas:

        cd_cvm = empresa["cd_cvm"]

        if not cd_cvm:
            continue

        ticker = empresa["ticker"]

        raiz = raiz_ticker(
            ticker
        )

        mapa[raiz] = cd_cvm

    total = 0

    for empresa in empresas:

        ticker = empresa["ticker"]

        raiz = raiz_ticker(
            ticker
        )

        cd_cvm = mapa.get(
            raiz
        )

        if not cd_cvm:
            continue

        (
            supabase
            .table("ticker_empresa")
            .upsert(
                {
                    "ticker": ticker,
                    "cd_cvm": cd_cvm,
                }
            )
            .execute()
        )

        total += 1

    print()
    print("========== FINAL ==========")
    print(
        f"Tickers mapeados: {total}"
    )


if __name__ == "__main__":
    main()
