from sqlalchemy import text

from etl.database.connection import engine


def main():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))

            print("✅ Conexão realizada com sucesso!")
            print(result.scalar())

    except Exception as e:
        print("❌ Erro na conexão")
        print(str(e))


if __name__ == "__main__":
    main()
