from datetime import datetime, UTC

from etl.database.supabase_client import supabase


def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert(
        {
            "processo": "calcular_indicadores",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }
    ).execute()


def obter_cotacao(ticker):

    dados = (
        supabase.table("cotacoes_diarias")
        .select("fechamento")
        .eq("ticker", ticker)
        .order("data", desc=True)
        .limit(1)
        .execute()
        .data
    )

    if not dados:
        return None

    return float(dados[0]["fechamento"])


def obter_lucro_liquido(cd_cvm):

    dados = (
        supabase.table("cvm_dre")
        .select("valor")
        .eq("cd_cvm", cd_cvm)
        .ilike("descricao_conta", "%lucro liquido%")
        .order("dt_referencia", desc=True)
        .limit(1)
        .execute()
        .data
    )

    if not dados:
        return None

    return float(dados[0]["valor"])


def obter_patrimonio_liquido(cd_cvm):

    dados = (
        supabase.table("cvm_bpp")
        .select("valor")
        .ilike("descricao_conta", "%patrimonio liquido%")
        .eq("cd_cvm", cd_cvm)
        .order("dt_referencia", desc=True)
        .limit(1)
        .execute()
        .data
    )

    if not dados:
        return None

    return float(dados[0]["valor"])


def main():

    total = 0

    empresas = (
        supabase.table("empresas")
        .select("*")
        .execute()
        .data
    )

    print(f"Empresas: {len(empresas)}")

    for empresa in empresas:

        try:

            ticker = empresa["ticker"]

            cotacao = obter_cotacao(ticker)

            if cotacao is None:
                continue

            registro = {
                "ticker": ticker,
                "cotacao": cotacao,
                "data_calculo": datetime.now(UTC).date().isoformat(),
            }

            (
                supabase.table("indicadores")
                .upsert(
                    registro,
                    on_conflict="ticker"
                )
                .execute()
            )

            total += 1

        except Exception as e:

            print(
                f"Erro {empresa['ticker']}: {e}"
            )

    registrar_carga(
        "SUCESSO",
        total,
        f"{total} empresas processadas"
    )

    print()
    print("========== FINAL ==========")
    print(f"Empresas processadas: {total}")


if __name__ == "__main__":
    main()
