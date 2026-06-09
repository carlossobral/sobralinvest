from io import BytesIO
from zipfile import ZipFile
import httpx
import pandas as pd
from etl.database.supabase_client import supabase

ANOS = [2024]

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS"

CONTA_RECEITA = "3.01"
CONTA_LUCRO = "3.11"

CONTA_ATIVO_TOTAL = "1"
CONTA_ATIVO_CIRC = "1.01"

CONTA_PASSIVO_CIRC = "2.01"
CONTA_PL = "2.03"


def baixar_zip(ano: int):
    url = f"{BASE_URL}/itr_cia_aberta_{ano}.zip"
    response = httpx.get(
        url,
        timeout=300,
        follow_redirects=True,
    )
    response.raise_for_status()
    return ZipFile(BytesIO(response.content))


def carregar_csv(zip_file, nome):
    with zip_file.open(nome) as f:
        return pd.read_csv(
            f,
            sep=";",
            encoding="latin1",
            low_memory=False,
        )


def carregar_empresas():
    resultado = (
        supabase
        .table("empresas")
        .select("ticker,cd_cvm")
        .not_.is_("cd_cvm", "null")
        .execute()
    )
    return {
        int(x["cd_cvm"]): x["ticker"]
        for x in resultado.data
        if x["cd_cvm"]
    }


def obter_valor(df, conta):
    # Filtrando pela conta informada
    linha = df[df["CD_CONTA"] == conta]
    
    if linha.empty:
        return None
    
    try:
        # Ordena para garantir que pegamos a última versão (ST_CONTA_FIXA ou maior valor de versão se houver)
        # E evita quebras caso o valor venha nulo
        valor = linha.iloc[0]["VL_CONTA"]
        return float(valor) if pd.notna(valor) else None
    except Exception:
        return None


def processar_empresa(
    ticker,
    ano,
    trimestre,
    data_ref,
    dre_empresa,
    bpa_empresa,
    bpp_empresa,
):
    receita = obter_valor(dre_empresa, CONTA_RECEITA)
    lucro = obter_valor(dre_empresa, CONTA_LUCRO)
    ativo_total = obter_valor(bpa_empresa, CONTA_ATIVO_TOTAL)
    ativo_circ = obter_valor(bpa_empresa, CONTA_ATIVO_CIRC)
    passivo_circ = obter_valor(bpp_empresa, CONTA_PASSIVO_CIRC)
    pl = obter_valor(bpp_empresa, CONTA_PL)

    passivo_total = None
    if ativo_total is not None and pl is not None:
        passivo_total = ativo_total - pl

    registro = {
        "ticker": ticker,
        "ano": ano,
        "trimestre": trimestre,
        "data_referencia": str(data_ref.date()),
        "receita_liquida": receita,
        "lucro_liquido": lucro,
        "ativo_total": ativo_total,
        "ativo_circulante": ativo_circ,
        "passivo_total": passivo_total,
        "passivo_circulante": passivo_circ,
        "patrimonio_liquido": pl,
    }

    # Certifique-se de que sua tabela no Supabase aceita a sintaxe de on_conflict baseada nas colunas passadas
    (
        supabase
        .table("fundamentos_trimestrais")
        .upsert(registro, on_conflict="ticker,ano,trimestre")
        .execute()
    )


def processar_ano(ano):
    print(f"\nBaixando ITR {ano}...")
    zip_file = baixar_zip(ano)

    print("Carregando CSVs na memória...")
    dre = carregar_csv(zip_file, f"itr_cia_aberta_DRE_con_{ano}.csv")
    bpa = carregar_csv(zip_file, f"itr_cia_aberta_BPA_con_{ano}.csv")
    bpp = carregar_csv(zip_file, f"itr_cia_aberta_BPP_con_{ano}.csv")

    # Padroniza as colunas de data para evitar incompatibilidade de string
    dre["DT_REFER"] = pd.to_datetime(dre["DT_REFER"])
    bpa["DT_REFER"] = pd.to_datetime(bpa["DT_REFER"])
    bpp["DT_REFER"] = pd.to_datetime(bpp["DT_REFER"])

    empresas = carregar_empresas()
    total = 0

    codigos_cvm = dre["CD_CVM"].dropna().unique()

    for cd_cvm in codigos_cvm:
        try:
            ticker = empresas.get(int(cd_cvm))
        except Exception:
            continue

        if not ticker:
            continue

        dre_empresa = dre[dre["CD_CVM"] == cd_cvm]
        bpa_empresa = bpa[bpa["CD_CVM"] == cd_cvm]
        bpp_empresa = bpp[bpp["CD_CVM"] == cd_cvm]

        datas = dre_empresa["DT_REFER"].dropna().unique()

        for data_ref in datas:
            try:
                # Converte o timestamp do numpy/pandas para datetime do python puro para extrair o mês
                dt = pd.to_datetime(data_ref)
                trimestre = ((dt.month - 1) // 3) + 1

                dre_trim = dre_empresa[dre_empresa["DT_REFER"] == data_ref]
                bpa_trim = bpa_empresa[bpa_empresa["DT_REFER"] == data_ref]
                bpp_trim = bpp_empresa[bpp_empresa["DT_REFER"] == data_ref]

                processar_empresa(
                    ticker=ticker,
                    ano=ano,
                    trimestre=trimestre,
                    data_ref=dt,
                    dre_empresa=dre_trim,
                    bpa_empresa=bpa_trim,
                    bpp_empresa=bpp_trim,
                )
                total += 1

            except Exception as e:
                print(f"Erro no processamento de {ticker} na data {data_ref}: {e}")

    return total


def main():
    total = 0
    for ano in ANOS:
        total += processar_ano(ano)

    print("\n========== FINAL ==========")
    print(f"Fundamentos processados: {total}")


if __name__ == "__main__":
    main()
