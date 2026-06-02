from etl.config.settings import settings


def main():
    print("=== Sobral Invest ETL ===")
    print(f"Supabase URL: {settings.supabase_url}")


if __name__ == "__main__":
    main()
