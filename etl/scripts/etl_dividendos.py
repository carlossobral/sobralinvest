from datetime import datetime, UTC

import httpx

from etl.database.supabase_client import supabase


URL = "https://mfinance.com.br/api/v1/stocks/dividends"


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "etl_dividendos",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def main():

    total_dividendos = 0
    total_empresas = 0
    total_erros = 0

    try:

        empresas = (
            supabase.table("empresas")
            .select("ticker")
            .execute()
            .data
        )

        print(f"Empresas encontradas: {len(empresas)}")

        for i, empresa in enumerate(empresas, start=1):

            ticker = empresa["ticker"]

            print(f"[{i}/{len(empresas)}] {ticker}")

            try:

                response = httpx.get(
                    f"{URL}/{ticker}",
                    timeout=30,
                )

                if response.status_code == 404:
                    continue

                response.raise_for_status()

                dados = response.json()

                dividendos = dados.get("dividends")

                if not dividendos:
                    continue

                registros_unicos = {}

                for item in dividendos:

                    if not item:
                        continue

                    data = item.get("date")
                    tipo = item.get("type")
                    valor = item.get("value")

                    if (
                        data is None
                        or tipo is None
                        or valor is None
                    ):
                        continue

                    chave = (
                        ticker,
                        data[:10],
                        tipo,
                        float(valor),
                    )

                    registros_unicos[chave] = {
                        "ticker": ticker,
                        "data_pagamento": data[:10],
                        "tipo": tipo,
                        "valor": valor,
                    }

                registros = list(registros_unicos.values())

                if not registros:
                    continue

                (
                    supabase.table("dividendos")
                    .upsert(
                        registros,
                        on_conflict="ticker,data_pagamento,tipo,valor"
                    )
                    .execute()
                )

                total_dividendos += len(registros)
                total_empresas += 1

            except Exception as e:

                total_erros += 1

                print(
                    f"Erro em {ticker}: "
                    f"{type(e).__name__}: {e}"
                )

        registrar_carga(
            status="SUCESSO",
            registros=total_dividendos,
            mensagem=(
                f"{total_dividendos} dividendos "
                f"carregados em {total_empresas} empresas"
            ),
        )

        print()
        print("========== FINAL ==========")
        print(f"Empresas processadas : {len(empresas)}")
        print(f"Empresas com dados   : {total_empresas}")
        print(f"Dividendos gravados  : {total_dividendos}")
        print(f"Erros                : {total_erros}")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e),
        )

        raise


if __name__ == "__main__":
    main()
