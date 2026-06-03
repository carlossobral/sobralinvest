from etl.database.supabase_client import supabase


def main():
    response = (
        supabase.table("etl_healthcheck")
        .insert({"status": "ok"})
        .execute()
    )

    print(response)


if __name__ == "__main__":
    main()
