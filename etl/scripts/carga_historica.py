from datetime import datetime, UTC
import sys

import yfinance as yf

from etl.database.supabase_client import supabase


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "carga_historica",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def carregar_ticker(ticker: str):

    print(f"\nBaixando histórico: {ticker}")

    df = yf.download(
        f"{ticker}.SA",
        period="max",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        print(f"Sem histórico para {ticker}")
        return 0

    # Corrige retorno MultiIndex das versões novas do yfinance
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    registros = []

    for data, row in df.iterrows():

        registros.append(
            {
                "ticker": ticker,
                "data": data.strftime("%Y-%m-%d"),
                "abertura": (
                    None if row["Open"] is None else float(row["Open"])
                ),
                "maxima": (
                    None if row["High"] is None else float(row["High"])
                ),
                "minima": (
                    None if row["Low"] is None else float(row["Low"])
                ),
                "fechamento": (
                    None if row["Close"] is None else float(row["Close"])
                ),
                "volume": (
                    0 if row["Volume"] is None else int(row["Volume"])
                ),
            }
        )

    print(f"Registros encontrados: {len(registros)}")

    lote = 500

    for i in range(0, len(registros), lote):

        (
            supabase.table("cotacoes_diarias")
            .upsert(
                registros[i:i + lote],
                on_conflict="ticker,data",
            )
            .execute()
        )

    print(f"{ticker}: {len(registros)} registros gravados")

    return len(registros)


def main():

    if len(sys.argv) < 2:

        print(
            "Uso: uv run python -m etl.scripts.carga_historica PETR4"
        )

        return

    ticker = sys.argv[1].upper()

    try:

        total = carregar_ticker(ticker)

        registrar_carga(
            status="SUCESSO",
            registros=total,
            mensagem=f"{ticker}: {total} registros",
        )

        print()
        print("========== FINAL ==========")
        print(f"Ticker    : {ticker}")
        print(f"Registros : {total}")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e),
        )

        raise


if __name__ == "__main__":
    main()
