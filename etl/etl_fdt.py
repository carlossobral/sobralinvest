"""
ETL CVM via Playwright - MODO PREVIEW (sem Supabase)
Fluxo:
  1. Acessa Fundamentus para tickers específicos
  2. Acessa o link do ENET (CVM)
  3. Extrai BP, DRE e DFC
  4. Apenas exibe os dados (NÃO insere no banco)

Instalar dependências com uv:
  uv init
  uv add playwright pandas python-dotenv
  uv run playwright install chromium

Executar:
  uv run python etl_preview.py
"""

import time
import re
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Mapeamento dos textos do menu ENET
SECOES_ENET = {
    "balanco_ativo":   ["Balanço Patrimonial Ativo",   "Balanco Patrimonial Ativo"],
    "balanco_passivo": ["Balanço Patrimonial Passivo",  "Balanco Patrimonial Passivo"],
    "dre":             ["Demonstração do Resultado",    "Demonstracao do Resultado",
                        "Demonstração de Resultado",    "DRE"],
    "dfc":             ["Demonstração dos Fluxos de Caixa", "Demonstracao dos Fluxos de Caixa",
                        "Demonstração do Fluxo de Caixa",  "DFC"],
}


# ---------------------------------------------------------------------------
# FUNDAMENTUS — pegar última data e link do ENET
# ---------------------------------------------------------------------------

def obter_dados_fundamentus(page, ticker: str):
    """
    Acessa a página de resultados trimestrais do Fundamentus e retorna
    a data mais recente e o link para o ENET da CVM.
    """
    url = f"https://www.fundamentus.com.br/resultados_trimestrais.php?papel={ticker}"
    print(f"  🌐 Fundamentus: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # A tabela tem id="resultado" no Fundamentus
        tabela = page.locator("table#resultado tbody tr").first

        # Primeira coluna = data | segunda coluna = link demonstração
        data_texto = tabela.locator("td").nth(0).inner_text().strip()
        link_elem  = tabela.locator("td a").first
        link_href  = link_elem.get_attribute("href")

        # Converter data "31/03/2026" → "2026-03-31"
        data_iso = datetime.strptime(data_texto, "%d/%m/%Y").strftime("%Y-%m-%d")

        print(f"  📅 Data no Fundamentus: {data_iso}")
        print(f"  🔗 Link ENET: {link_href}")
        return data_iso, link_href

    except Exception as e:
        print(f"  ❌ Erro ao acessar Fundamentus para {ticker}: {e}")
        return None, None


# ---------------------------------------------------------------------------
# ENET — extrair tabelas financeiras
# ---------------------------------------------------------------------------

def clicar_secao(page, candidatos: list):
    """
    Tenta clicar em um link do menu ENET testando variações do texto.
    Retorna True se conseguiu.
    """
    for texto in candidatos:
        try:
            # Tenta na página principal primeiro
            loc = page.locator(f'a:text-is("{texto}")').first
            loc.wait_for(state="visible", timeout=5000)
            loc.click()
            return True
        except PlaywrightTimeout:
            pass

        try:
            # Tenta com contains
            loc = page.locator(f'a:has-text("{texto}")').first
            loc.wait_for(state="visible", timeout=5000)
            loc.click()
            return True
        except PlaywrightTimeout:
            pass

        # Tenta em cada frame
        for frame in page.frames:
            try:
                loc = frame.locator(f'a:has-text("{texto}")').first
                loc.wait_for(state="visible", timeout=3000)
                loc.click()
                return True
            except Exception:
                pass

    return False


def extrair_tabela_enet(page) -> pd.DataFrame | None:
    """
    Após clicar em uma seção do ENET, extrai a tabela de dados.
    """
    page.wait_for_timeout(4000)

    # Tentar encontrar tabela em todos os frames
    frames_para_tentar = [page] + list(page.frames)

    for contexto in frames_para_tentar:
        try:
            tabelas = contexto.locator("table").all()
            if not tabelas:
                continue

            # Pegar a maior tabela (mais linhas)
            melhor = None
            melhor_linhas = 0
            for t in tabelas:
                html = t.inner_html()
                linhas = html.count("<tr")
                if linhas > melhor_linhas:
                    melhor_linhas = linhas
                    melhor = html

            if melhor and melhor_linhas > 3:
                dfs = pd.read_html(f"<table>{melhor}</table>")
                if dfs:
                    return dfs[0]
        except Exception:
            continue

    return None


def converter_valor(valor) -> float | None:
    if pd.isna(valor):
        return None
    s = str(valor).strip()
    if s in ("", "-", "—"):
        return None
    # Remove pontos de milhar, troca vírgula decimal
    s = re.sub(r"\s", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extrair_enet(page, url_enet: str) -> dict:
    """
    Acessa o ENET e extrai BP ativo, BP passivo, DRE e DFC.
    Retorna dicionário com DataFrames.
    """
    print(f"  🏛️  ENET: {url_enet}")
    page.goto(url_enet, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    dados = {}

    for chave, candidatos in SECOES_ENET.items():
        print(f"\n    📊 Extraindo: {chave}")
        clicou = clicar_secao(page, candidatos)

        if not clicou:
            print(f"    ⚠️  Não encontrou link para: {chave}")
            dados[chave] = None
            continue

        df = extrair_tabela_enet(page)

        if df is None:
            print(f"    ⚠️  Tabela não encontrada para: {chave}")
            dados[chave] = None
        else:
            print(f"    ✅  {len(df)} linhas extraídas")
            dados[chave] = df

        # Voltar para a página do ENET antes do próximo clique
        page.go_back()
        page.wait_for_timeout(3000)

    return dados


# ---------------------------------------------------------------------------
# PARSEAR dados → estrutura para exibição
# ---------------------------------------------------------------------------

def parsear_df(df: pd.DataFrame) -> dict:
    """
    Recebe um DataFrame e retorna dicionário {codigo_conta: valor}
    """
    if df is None or df.empty:
        return {}

    resultado = {}
    df.columns = [str(c).strip() for c in df.columns]

    col_conta = df.columns[0]

    col_valor = None
    for c in df.columns[1:]:
        vals = df[c].apply(converter_valor).dropna()
        if len(vals) > 3:
            col_valor = c
            break

    if col_valor is None:
        return {}

    for _, row in df.iterrows():
        conta = str(row[col_conta]).strip()
        valor = converter_valor(row[col_valor])
        if conta and valor is not None:
            resultado[conta] = valor

    return resultado


def formatar_valor_br(valor) -> str:
    """Formata valor no padrão brasileiro (R$ 1.234,56)"""
    if valor is None:
        return "N/A"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def exibir_resultados(ticker: str, data_ref: str, dados_brutos: dict):
    """
    Exibe os dados extraídos de forma formatada
    """
    dt = datetime.strptime(data_ref, "%Y-%m-%d")
    mes = dt.month
    trimestre = (mes - 1) // 3 + 1

    print("\n" + "=" * 80)
    print(f"📋 DADOS EXTRAÍDOS - {ticker} | {trimestre}º Trimestre {dt.year}")
    print(f"📅 Data de Referência: {data_ref}")
    print("=" * 80)

    bpa = parsear_df(dados_brutos.get("balanco_ativo"))
    bpp = parsear_df(dados_brutos.get("balanco_passivo"))
    dre = parsear_df(dados_brutos.get("dre"))
    dfc = parsear_df(dados_brutos.get("dfc"))

    # BALANÇO PATRIMONIAL ATIVO
    print("\n💼 BALANÇO PATRIMONIAL - ATIVO")
    print("-" * 80)
    if bpa:
        for conta in ["1", "1.01", "1.01.01", "1.01.02", "1.02", "1.02.01", "1.02.03"]:
            if conta in bpa:
                print(f"  {conta:15s} {formatar_valor_br(bpa[conta]):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")

    # BALANÇO PATRIMONIAL PASSIVO
    print("\n💼 BALANÇO PATRIMONIAL - PASSIVO")
    print("-" * 80)
    if bpp:
        for conta in ["2", "2.01", "2.01.04", "2.02", "2.02.01", "2.03"]:
            if conta in bpp:
                print(f"  {conta:15s} {formatar_valor_br(bpp[conta]):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")

    # DRE
    print("\n📈 DEMONSTRAÇÃO DO RESULTADO (YTD)")
    print("-" * 80)
    if dre:
        for conta in ["3.01", "3.02", "3.03", "3.05", "3.11"]:
            if conta in dre:
                print(f"  {conta:15s} {formatar_valor_br(dre[conta]):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")

    # CÁLCULOS DERIVADOS
    print("\n🧮 INDICADORES CALCULADOS")
    print("-" * 80)
    
    caixa = (bpa.get("1.01.01", 0) or 0) + (bpa.get("1.01.02", 0) or 0)
    divida_cp = bpp.get("2.01.04", 0) or 0
    divida_lp = bpp.get("2.02.01", 0) or 0
    divida_bruta = divida_cp + divida_lp
    divida_liquida = divida_bruta - caixa

    print(f"  {'Caixa Total':15s} {formatar_valor_br(caixa):>25s}")
    print(f"  {'Dívida Bruta':15s} {formatar_valor_br(divida_bruta):>25s}")
    print(f"  {'Dívida Líquida':15s} {formatar_valor_br(divida_liquida):>25s}")

    if bpp.get("2.03"):
        div_liq_pl = divida_liquida / bpp["2.03"] if bpp["2.03"] != 0 else 0
        print(f"  {'Dív.Liq/PL':15s} {div_liq_pl:>24.2f}x")

    if dre.get("3.05") and bpp.get("1"):
        roa = dre["3.05"] / bpp["1"] if bpp["1"] != 0 else 0
        print(f"  {'ROA':15s} {roa*100:>24.2f}%")

    print("\n" + "=" * 80)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("🔍 ETL CVM via Playwright - MODO PREVIEW (sem Supabase)")
    print("=" * 80)

    # Lista de tickers para testar (você pode mudar)
    tickers = ["PETR4", "VALE3", "WEGE3"]  # Exemplo: 3 empresas
    
    print(f"\n📋 Tickers para processar: {', '.join(tickers)}\n")

    processados = 0
    erros = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)  # Visível para debug
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for i, ticker in enumerate(tickers, start=1):
            print(f"\n[{i}/{len(tickers)}] Processando {ticker}")
            print("-" * 80)

            try:
                # 1. Pegar data e link do Fundamentus
                data_site, link_enet = obter_dados_fundamentus(page, ticker)

                if not data_site or not link_enet:
                    print(f"  ⚠️  Sem dados no Fundamentus para {ticker}")
                    continue

                # 2. Extrair do ENET
                dados_brutos = extrair_enet(page, link_enet)

                # 3. Exibir resultados
                exibir_resultados(ticker, data_site, dados_brutos)
                processados += 1

            except Exception as e:
                print(f"  ❌ Erro ao processar {ticker}: {e}")
                erros += 1

            # Pausa entre empresas
            time.sleep(2)

        browser.close()

    print("\n" + "=" * 80)
    print("📊 RESUMO FINAL")
    print("=" * 80)
    print(f"✅ Processados com sucesso: {processados}")
    print(f"❌ Erros: {erros}")
    print(f"📝 Modo: PREVIEW (nenhum dado foi inserido no banco)")
    print("=" * 80)


if __name__ == "__main__":
    main()
