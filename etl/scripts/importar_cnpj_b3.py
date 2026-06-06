from pathlib import Path
import pandas as pd

from etl.config.database import supabase


ARQUIVO = Path("Pasta1.xlsx")


def limpar_cnpj(cnpj):
    if pd.isna(cnpj):
        return None

    return (
        str(cnpj)
        .replace(".", "")
        .replace("/", "")
        .replace("-", "")
        .strip()
    )


def main():

    df = pd.read_excel(ARQUIVO)

    df["Código(s)"] = df["Código(s)"].astype(str).str.strip()

    cnpj_atual = None
    atualizados = 0

    for _, row in df.iterrows():

        ticker = row["Código(s)"]

        if pd.notna(row["CNPJ"]):
            cnpj_atual = limpar_cnpj(row["CNPJ"])

        if not ticker or ticker == "nan":
            continue

        try:

            supabase.table("ticker_empresa").upsert(
                {
                    "ticker": ticker,
                    "cnpj": cnpj_atual,
                }
            ).execute()

            atualizados += 1

        except Exception as e:
            print(f"Erro {ticker}: {e}")

    print("\n========== FINAL ==========")
    print(f"Registros processados: {atualizados}")


if __name__ == "__main__":
    main()
