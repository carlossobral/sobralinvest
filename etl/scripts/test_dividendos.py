import httpx

from etl.database.supabase_client import supabase

URL = "https://mfinance.com.br/api/v1/stocks/dividends"


def main():

    empresas = (
        supabase
        .table("empresas")
        .select("ticker")
        .limit(50)
        .execute()
        .data
    )

    sucesso = 0
    vazio = 0
    null = 0
    erro = 0

    erros = []

    for i, empresa in enumerate(empresas, start=1):

        ticker = empresa["ticker"]

        print(f"[{i}/{len(empresas)}] {ticker}")

        try:

            response = httpx.get(
                f"{URL}/{ticker}",
                timeout=30
            )

            if response.status_code != 200:
                vazio += 1
                print(f"  -> HTTP {response.status_code}")
                continue

            dados = response.json()

            dividendos = dados.get("dividends")

            if dividendos is None:
                null += 1
                print("  -> dividends = None")
                continue

            if len(dividendos) == 0:
                vazio += 1
                print("  -> sem dividendos")
                continue

            # teste de duplicidade
            vistos = set()
            duplicados = 0

            for item in dividendos:

                chave = (
                    item.get("date"),
                    item.get("type"),
                    item.get("value")
                )

                if chave in vistos:
                    duplicados += 1

                vistos.add(chave)

            print(
                f"  -> {len(dividendos)} eventos "
                f"({duplicados} duplicados)"
            )

            sucesso += 1

        except Exception as e:

            erro += 1

            erros.append(
                {
                    "ticker": ticker,
                    "erro": str(e)
                }
            )

            print(f"  -> ERRO: {e}")

    print("\n===== RESULTADO =====")
    print(f"Sucesso : {sucesso}")
    print(f"Null    : {null}")
    print(f"Vazio   : {vazio}")
    print(f"Erro    : {erro}")

    if erros:

        print("\n===== DETALHE DOS ERROS =====")

        for item in erros:
            print(
                f"{item['ticker']} -> {item['erro']}"
            )


if __name__ == "__main__":
    main()
