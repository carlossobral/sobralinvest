from datetime import datetime, UTC

from etl.database.supabase_client import supabase


def main():
    response = (
        supabase.table("etl_cargas")
        .insert(
            {
                "processo": "teste",
                "inicio": datetime.now(UTC).isoformat(),
                "status": "SUCESSO",
                "registros": 1,
                "mensagem": "Primeiro teste do Sobral Invest"
            }
        )
        .execute()
    )

    print(response.data)


if __name__ == "__main__":
    main()
