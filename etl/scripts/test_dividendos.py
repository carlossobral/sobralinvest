import httpx

from etl.database.supabase_client import supabase

URL = "https://mfinance.com.br/api/v1/stocks/dividends"


def main():

    empresas = (
        supabase.table("empresas")
        .select("ticker")
        .limit(50)
        .execute()
        .data
    )

    sucesso = 0
    vazio = 0
    erro = 0
    null = 0

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
                continue

            dados = response.json()

            dividendos = dados.get("dividends")

            if dividendos is None:
                null += 1
                continue

            if len(dividendos) == 0:
                vazio += 1
                continue

            # remove duplicados do próprio MFinance
            vistos = set()
            registros = []

            for item in dividendos:

                chave = (
                    item.get("date"),
                    item.get("type"),
                    item.get("value")
                )

                if chave in vistos:
                    continue

                vistos.add(chave)

                registros.append(
                    {
                        "ticker": ticker,
                        "data_pagamento": item["date"][:10],
                        "tipo": item["type"],
                        "valor": item["value"],
                    }
                )

            sucesso += 1

        except Exception:
            erro += 1

    print("\n===== RESULTADO =====")
    print("Sucesso :", sucesso)
    print("Null    :", null)
    print("Vazio   :", vazio)
    print("Erro    :", erro)


if __name__ == "__main__":
    main()
