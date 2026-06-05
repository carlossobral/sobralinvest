from datetime import datetime, UTC

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

        registros = []

        ignoradas = 0

        for item in stocks:

            nome = item.get("name")

            # Ignora registros inválidos
            if not nome:
                ignoradas += 1
                continue

            if nome.strip() == "#N/A":
                ignoradas += 1
                continue

            registros.append(
                {
                    "ticker": item.get("symbol"),
                    "nome": nome,
                    "setor": item.get("sector"),
                    "subsetor": item.get("subSector"),
                    "segmento": item.get("segment"),
                    "ativo": True,
                }
            )

        if registros:

            (
                supabase.table("empresas")
                .upsert(
                    registros,
                    on_conflict="ticker"
                )
                .execute()
            )

        registrar_carga(
            status="SUCESSO",
            registros=len(registros),
            mensagem=f"{len(registros)} empresas carregadas. {ignoradas} ignoradas (#N/A)"
        )

        print()
        print("========== FINAL ==========")
        print(f"Empresas válidas : {len(registros)}")
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
