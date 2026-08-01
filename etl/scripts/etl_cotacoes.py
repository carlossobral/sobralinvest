from datetime import datetime, date, UTC
import httpx

from etl.database.supabase_client import supabase
from etl.config.settings import settings

BRAPI_TOKEN = settings.brapi_token
BASE_URL = "https://brapi.dev/api/v2/stocks/historical"


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert({
        "processo": "etl_cotacoes",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status,
        "registros": registros,
        "mensagem": mensagem,
    }).execute()


def obter_tickers():
    resposta = supabase.table("empresas").select("ticker").execute()
    return [x["ticker"] for x in resposta.data]


def main():
    total_registros = 0

    try:
        tickers = obter_tickers()
        print(f"{len(tickers)} empresas encontradas.\n")

        with httpx.Client(timeout=60) as client:

            for i, ticker in enumerate(tickers, start=1):

                try:

                    print(f"[{i}/{len(tickers)}] {ticker}")

                    response = client.get(
                        BASE_URL,
                        params={
                            "symbols": ticker,
                            "range": "3mo",
                            "interval": "1d",
                            "token": BRAPI_TOKEN,
                        },
                    )

                    response.raise_for_status()

                    payload = response.json()

                    resultados = payload.get("results", [])

                    if not resultados:
                        print("   Sem retorno.")
                        continue

                    historico = resultados[0].get("data", {}).get("historicalDataPrice", [])

                    if not historico:
                        print("   Sem histórico.")
                        continue

                    registros = []

                    for candle in historico:

                        fechamento = candle.get("adjustedClose")

                        if fechamento is None:
                            continue

                        volume = candle.get("volume", 0) or 0

                        registros.append({
                            "ticker": ticker,
                            "data": date.fromtimestamp(candle["date"]).isoformat(),
                            "fechamento": float(fechamento),
                            "volume": int(volume),
                            "volume_financeiro": float(fechamento) * float(volume),
                        })

                    if not registros:
                        print("   Nenhum registro válido.")
                        continue

                    supabase.table("cotacoes").upsert(
                        registros,
                        on_conflict="ticker,data"
                    ).execute()

                    total_registros += len(registros)

                    print(f"   {len(registros)} pregões atualizados.")

                except Exception as erro:
                    print(f"   ERRO: {erro}")

        registrar_carga(
            "SUCESSO",
            total_registros,
            f"{total_registros} cotações processadas."
        )

        print(f"\nConcluído. {total_registros} registros gravados/atualizados.")

    except Exception as erro:

        registrar_carga(
            "ERRO",
            total_registros,
            str(erro)
        )

        raise


if __name__ == "__main__":
    main()
