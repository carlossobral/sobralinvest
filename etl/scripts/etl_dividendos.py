from datetime import datetime, UTC

import httpx

from etl.database.supabase_client import supabase


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
                    f"https://mfinance.com.br/api/v1/stocks/dividends/{ticker}",
                    timeout=30,
                )

                if response.status_code != 200:
                    continue

                dados = response.json()

                dividendos = dados.get("dividends")

                if not dividendos:
                    continue

                registros_unicos = {}

                for item in dividendos:

                    chave = (
                        ticker,
                        item["date"][:10],
                        item["type"],
                        float(item["value"]),
                    )

                    registros_unicos[chave] = {
                        "ticker": ticker,
                        "data_pagamento": item["date"][:10],
                        "tipo": item["type"],
                        "valor": item["value"],
                    }

                registros = list(registros_unicos.values())

                if registros:

                    (
                        supabase.table("dividendos")
                        .upsert(
                            registros,
                            on_conflict="ticker,data_pagamento,tipo,valor"
                        )
                        .execute()
                    )

                    total_dividendos += len(registros)

            except Exception as e:

                print(f"Erro em {ticker}: {e}")

        registrar_carga(
            status="SUCESSO",
            registros=total_dividendos,
            mensagem=f"{total_dividendos} dividendos carregados",
        )

        print("\n========== FINAL ==========")
        print(f"Dividendos carregados: {total_dividendos}")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e),
        )

        raise


if __name__ == "__main__":
    main()
