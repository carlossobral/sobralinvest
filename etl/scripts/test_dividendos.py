import httpx

from etl.database.supabase_client import supabase


URL_BASE = "https://mfinance.com.br/api/v1/stocks/dividends"


def main():
    empresas = (
        supabase
        .table("empresas")
        .select("ticker")
        .limit(50)
        .execute()
    )

    tickers = [e["ticker"] for e in empresas.data]

    sucesso = 0
    vazio = 0
    null = 0
    erro404 = 0
    erro = 0

    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] {ticker}")

        try:
            response = httpx.get(
                f"{URL_BASE}/{ticker}",
                timeout=30
            )

            if response.status_code == 404:
                erro404 += 1
                continue

            response.raise_for_status()

            dados = response.json()

            if dados is None:
                null += 1
                continue

            dividendos = dados.get("dividends")

            if dividendos is None:
                null += 1
                continue

            if len(dividendos) == 0:
                vazio += 1
                continue

            sucesso += 1

        except Exception as e:
            print(f"Erro em {ticker}: {e}")
            erro += 1

    print("\n===== RESULTADO =====")
    print(f"Sucesso : {sucesso}")
    print(f"404     : {erro404}")
    print(f"Null    : {null}")
    print(f"Vazio   : {vazio}")
    print(f"Erro    : {erro}")


if __name__ == "__main__":
    main()
