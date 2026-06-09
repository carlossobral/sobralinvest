from datetime import datetime, UTC, date

import httpx

from etl.database.supabase_client import supabase


URL = "https://mfinance.com.br/api/v1/stocks"


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "etl_empresas",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def main():
    try:
        print("Buscando empresas na MFinance...")

        response = httpx.get(URL, timeout=60)

        response.raise_for_status()

        dados = response.json()

        stocks = dados.get("stocks", [])

        empresas = []
        cotacoes = []

        ignoradas = 0

        hoje = date.today().isoformat()

        for item in stocks:

            nome = item.get("name")

            # Ignora registros inválidos
            if not nome:
                ignoradas += 1
                continue

            if nome.strip() == "#N/A":
                ignoradas += 1
                continue

            ticker = item.get("symbol")

            empresas.append(
                {
                    "ticker": ticker,
                    "nome": nome,
                    "setor": item.get("sector"),
                    "subsetor": item.get("subSector"),
                    "segmento": item.get("segment"),
                    "ativo": True,
                }
            )

            cotacoes.append(
                {
                    "ticker": ticker,
                    "data": hoje,
                    "abertura": item.get("priceOpen"),
                    "maxima": item.get("high"),
                    "minima": item.get("low"),
                    "fechamento": item.get("lastPrice"),
                    "volume": item.get("volume"),
                }
            )

        if empresas:

            (
                supabase.table("empresas")
                .upsert(
                    empresas,
                    on_conflict="ticker"
                )
                .execute()
            )

        if cotacoes:

            (
                supabase.table("cotacoes")
                .upsert(
                    cotacoes,
                    on_conflict="ticker,data"
                )
                .execute()
            )

        registrar_carga(
            status="SUCESSO",
            registros=len(empresas),
            mensagem=(
                f"{len(empresas)} empresas carregadas. "
                f"{len(cotacoes)} cotações carregadas. "
                f"{ignoradas} ignoradas (#N/A)"
            )
        )

        print()
        print("========== FINAL ==========")
        print(f"Empresas válidas : {len(empresas)}")
        print(f"Cotações salvas  : {len(cotacoes)}")
        print(f"Ignoradas (#N/A) : {ignoradas}")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e)
        )

        raise


if __name__ == "__main__":
    main()
