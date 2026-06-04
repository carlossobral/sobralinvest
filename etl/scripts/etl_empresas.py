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
        response = httpx.get(URL, timeout=60)
        response.raise_for_status()

        dados = response.json()

        print("\n===== DEBUG =====")
        print("Tipo:", type(dados))

        if isinstance(dados, list):
            print("Quantidade:", len(dados))
            print("Primeiros 3 registros:")
            print(dados[:3])
        else:
            print("Conteúdo:")
            print(dados)

        print("=================\n")

        return

        registros = []

        for item in dados:
            registros.append(
                {
                    "ticker": item.get("symbol"),
                    "nome": item.get("name"),
                    "setor": item.get("sector"),
                    "subsetor": item.get("subSector"),
                    "segmento": item.get("segment"),
                    "ativo": True,
                }
            )

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

        raise


if __name__ == "__main__":
    main()
