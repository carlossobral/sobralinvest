from collections import Counter

import httpx

from etl.database.supabase_client import supabase


BASE_URL = "https://mfinance.com.br/api/v1/stocks/historicals"


def obter_tickers():
    resposta = (
        supabase
        .table("empresas")
        .select("ticker")
        .execute()
    )

    return [x["ticker"] for x in resposta.data]


def main():

    tickers = obter_tickers()[:50]

    estatisticas = Counter()

    for i, ticker in enumerate(tickers, start=1):

        print(f"[{i}/50] {ticker}")

        try:

            response = httpx.get(
                f"{BASE_URL}/{ticker}",
                timeout=30
            )

            if response.status_code == 404:
                estatisticas["404"] += 1
                continue

            response.raise_for_status()

            payload = response.json()

            historicos = payload.get("historicals")

            if historicos is None:
                estatisticas["null"] += 1
                continue

            if len(historicos) == 0:
                estatisticas["vazio"] += 1
                continue

            estatisticas["sucesso"] += 1

        except Exception as erro:

            print(f"Erro em {ticker}: {erro}")

            estatisticas["erro"] += 1

    print("\n===== RESULTADO =====")
    print(f"Sucesso : {estatisticas['sucesso']}")
    print(f"404     : {estatisticas['404']}")
    print(f"Null    : {estatisticas['null']}")
    print(f"Vazio   : {estatisticas['vazio']}")
    print(f"Erro    : {estatisticas['erro']}")


if __name__ == "__main__":
    main()
