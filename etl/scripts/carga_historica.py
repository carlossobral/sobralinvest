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


def ticker_ja_carregado(ticker: str) -> bool:

    resultado = (
        supabase.table("cotacoes_diarias")
        .select("id", count="exact")
        .eq("ticker", ticker)
        .limit(1)
        .execute()
    )

    return (resultado.count or 0) > 0


def carregar_ticker(ticker: str):

    print(f"Baixando histórico: {ticker}")

    df = yf.download(
        f"{ticker}.SA",
        period="max",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        print(f"Sem histórico: {ticker}")
        return 0

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    registros = []

    for data, row in df.iterrows():

        registros.append(
            {
                "ticker": ticker,
                "data": data.strftime("%Y-%m-%d"),
                "abertura": float(row["Open"]) if row["Open"] == row["Open"] else None,
                "maxima": float(row["High"]) if row["High"] == row["High"] else None,
                "minima": float(row["Low"]) if row["Low"] == row["Low"] else None,
                "fechamento": float(row["Close"]) if row["Close"] == row["Close"] else None,
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            }
        )

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

    print(f"{ticker}: {len(registros)} registros")

    return len(registros)


def main():

    total_registros = 0
    processados = 0
    pulados = 0

    try:

        # MODO 1 -> TICKER INFORMADO
        if len(sys.argv) > 1:

            ticker = sys.argv[1].upper()

            total = carregar_ticker(ticker)

            print()
            print("========== FINAL ==========")
            print(f"Ticker    : {ticker}")
            print(f"Registros : {total}")

            return

        # MODO 2 -> TODOS OS TICKERS DA TABELA EMPRESAS

        empresas = (
            supabase.table("empresas")
            .select("ticker")
            .order("ticker")
            .execute()
            .data
        )

        print(f"Empresas encontradas: {len(empresas)}")
        print()

        for i, empresa in enumerate(empresas, start=1):

            ticker = empresa["ticker"]

            print(f"[{i}/{len(empresas)}] {ticker}")

            try:

                if ticker_ja_carregado(ticker):

                    pulados += 1
                    print("Já possui histórico")
                    continue

                total = carregar_ticker(ticker)

                total_registros += total
                processados += 1

            except Exception as e:

                print(f"Erro em {ticker}: {e}")

        registrar_carga(
            status="SUCESSO",
            registros=total_registros,
            mensagem=f"{processados} tickers carregados",
        )

        print()
        print("========== FINAL ==========")
        print(f"Tickers carregados : {processados}")
        print(f"Tickers pulados    : {pulados}")
        print(f"Registros gravados : {total_registros}")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e),
        )

        raise


if __name__ == "__main__":
    main()
