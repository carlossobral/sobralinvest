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
    hoje = date.today().isoformat()

    try:
        tickers = obter_tickers()
        print(f"Empresas encontradas: {len(tickers)}")

        for i, ticker in enumerate(tickers, start=1):
            try:
                print(f"[{i}/{len(tickers)}] {ticker}", end=" ")

                response = httpx.get(
                    BASE_URL,
                    params={
                        "symbols": ticker,
                        "range": "5d",
                        "interval": "1d",
                        "token": BRAPI_TOKEN,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()

                resultados = payload.get("results", [])
                if not resultados:
                    print("Sem dados.")
                    continue

                historico = resultados[0].get("data", {}).get("historicalDataPrice", [])
                if not historico:
                    print("Sem histórico.")
                    continue

                # Pega só o registro mais recente
                ultimo = historico[-1]
                adjusted_close = ultimo.get("adjustedClose")
                volume = ultimo.get("volume", 0) or 0
                data_pregao = date.fromtimestamp(ultimo["date"]).isoformat()

                if not adjusted_close:
                    print("adjustedClose ausente.")
                    continue

                volume_financeiro = float(adjusted_close) * float(volume)

                supabase.table("cotacoes").upsert(
                    {
                        "ticker": ticker,
                        "data": data_pregao,
                        "fechamento": adjusted_close,
                        "volume": volume,
                        "volume_financeiro": volume_financeiro,
                    },
                    on_conflict="ticker,data"
                ).execute()

                total_registros += 1
                print(f"✅ {data_pregao} | R$ {adjusted_close} | vol {volume:,}")

            except Exception as erro:
                print(f"ERRO: {erro}")

        registrar_carga("SUCESSO", total_registros, "Carga de cotações concluída")
        print(f"\n✅ Total: {total_registros} registros atualizados.")

    except Exception as erro:
        registrar_carga("ERRO", 0, str(erro))
        raise

if __name__ == "__main__":
    main()
