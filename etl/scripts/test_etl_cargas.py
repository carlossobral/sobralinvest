from datetime import datetime

from etl.database.supabase_client import supabase


def main():
    response = (
        supabase.table("etl_cargas")
        .insert(
            {
                "processo": "teste",
                "inicio": datetime.utcnow().isoformat(),
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
