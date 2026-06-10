from datetime import datetime, UTC

import httpx
import pandas as pd

from etl.database.supabase_client import supabase


BASE_URL = "https://mfinance.com.br/api/v1/stocks/historicals"


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "etl_cotacoes",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def obter_tickers():
    resposta = (
        supabase
        .table("empresas")
        .select("ticker")
        .execute()
    )

    return [x["ticker"] for x in resposta.data]


def main():

    total_registros = 0

    try:

        tickers = obter_tickers()

        print(f"Empresas encontradas: {len(tickers)}")

        for i, ticker in enumerate(tickers, start=1):

            try:

                print(f"[{i}/{len(tickers)}] {ticker}")

                response = httpx.get(
                    f"{BASE_URL}/{ticker}",
                    timeout=60
                )

                response.raise_for_status()

                payload = response.json()

                historicos = payload.get("historicals", [])

                registros = []

                for item in historicos:
                    # Pré-calcula o volume financeiro na ingestão
                    volume = item.get("volume", 0) or 0
                    fechamento = item.get("close", 0) or 0
                    
                    # Converte para float para garantir cálculo correto
                    try:
                        volume_num = float(volume)
                        fechamento_num = float(fechamento)
                        volume_financeiro = volume_num * fechamento_num
                    except (ValueError, TypeError):
                        volume_financeiro = 0

                    registros.append(
                        {
                            "ticker": ticker,
                            "data": item["date"][:10],
                            "abertura": item.get("open"),
                            "maxima": item.get("high"),
                            "minima": item.get("low"),
                            "fechamento": fechamento,
                            "volume": volume,
                            "volume_financeiro": volume_financeiro,
                        }
                    )

                if registros:

                    (
                        supabase
                        .table("cotacoes")
                        .upsert(
                            registros,
                            on_conflict="ticker,data"
                        )
                        .execute()
                    )

                    total_registros += len(registros)

            except Exception as erro:

                print(f"Erro em {ticker}: {erro}")

        registrar_carga(
            status="SUCESSO",
            registros=total_registros,
            mensagem="Carga de cotações concluída"
        )

        print(
            f"✅ Total de registros carregados: {total_registros}"
        )

    except Exception as erro:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(erro)
        )

        raise


if __name__ == "__main__":
    main()
