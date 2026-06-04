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

        response = httpx.get(URL, timeout=120)
        response.raise_for_status()

        payload = response.json()

        dados = payload.get("stocks", [])

        registros = []

        for item in dados:

            ticker = item.get("symbol")

            if not ticker:
                continue

            registros.append(
                {
                    "ticker": ticker,
                    "nome": item.get("name"),
                    "setor": item.get("sector"),
                    "subsetor": item.get("subSector"),
                    "segmento": item.get("segment"),
                    "ativo": True,
                }
            )

        print(f"Empresas encontradas: {len(registros)}")

        if registros:
            supabase.table("empresas").upsert(
                registros,
                on_conflict="ticker"
            ).execute()

        registrar_carga(
            status="SUCESSO",
            registros=len(registros),
            mensagem="Carga de empresas concluída"
        )

        print(f"✅ {len(registros)} empresas carregadas")

    except Exception as e:

        registrar_carga(
            status="ERRO",
            registros=0,
            mensagem=str(e)
        )

        print(f"❌ Erro: {e}")
        raise


if __name__ == "__main__":
    main()
