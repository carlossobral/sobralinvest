"""
ETL CVM via Playwright - VERSÃO FUNCIONAL
"""

import time
import re
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

def extrair_demonstracao_cvm(page, url_enet: str, nome_demonstracao: str) -> pd.DataFrame | None:
    """
    Acessa uma demonstração específica no ENET e extrai a tabela
    """
    print(f"    📊 Acessando: {nome_demonstracao}")
    
    try:
        # Acessar a página principal do ENET
        page.goto(url_enet, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        
        # Tentar encontrar o link no menu
        # O menu tem links com os nomes exatos das demonstrações
        link = page.locator(f'a:has-text("{nome_demonstracao}")').first
        link.wait_for(state="visible", timeout=10000)
        link.click()
        
        # Aguardar o conteúdo carregar
        page.wait_for_timeout(5000)
        
        # Extrair a tabela
        tabela = page.locator('table').first
        tabela.wait_for(state="visible", timeout=10000)
        
        html_tabela = tabela.inner_html()
        df = pd.read_html(f'<table>{html_tabela}</table>')[0]
        
        print(f"    ✅ {len(df)} linhas extraídas")
        return df
        
    except Exception as e:
        print(f"    ❌ Erro ao extrair {nome_demonstracao}: {e}")
        return None


def converter_valor(valor) -> float | None:
    if pd.isna(valor):
        return None
    s = str(valor).strip()
    if s in ("", "-", "—"):
        return None
    s = re.sub(r"\s", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


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
    """Formata valor no padrão brasileiro"""
    if valor is None:
        return "N/A"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    print("=" * 80)
    print("🔍 ETL CVM - EXTRAÇÃO DIRETA DO ENET")
    print("=" * 80)
    
    url_enet = "https://www.rad.cvm.gov.br/ENET/frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=157120&CodigoTipoInstituicao=1"
    ticker = "PETR4"
    data_ref = "2026-03-31"
    
    print(f"\n📋 Ticker: {ticker}")
    print(f"📅 Data: {data_ref}")
    print(f"🔗 URL: {url_enet}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()
        
        try:
            # Extrair cada demonstração
            bpa = extrair_demonstracao_cvm(page, url_enet, "Balanço Patrimonial Ativo")
            time.sleep(2)
            
            bpp = extrair_demonstracao_cvm(page, url_enet, "Balanço Patrimonial Passivo")
            time.sleep(2)
            
            dre = extrair_demonstracao_cvm(page, url_enet, "Demonstração do Resultado")
            time.sleep(2)
            
            dfc = extrair_demonstracao_cvm(page, url_enet, "Demonstração do Fluxo de Caixa")
            
            # Exibir resultados
            print("\n" + "=" * 80)
            print("📊 DADOS EXTRAÍDOS")
            print("=" * 80)
            
            bpa_dict = parsear_df(bpa)
            bpp_dict = parsear_df(bpp)
            dre_dict = parsear_df(dre)
            
            print("\n💼 BALANÇO PATRIMONIAL - ATIVO")
            print("-" * 80)
            for conta in ["1", "1.01", "1.01.01", "1.01.02"]:
                if conta in bpa_dict:
                    print(f"  {conta:15s} {formatar_valor_br(bpa_dict[conta]):>25s}")
            
            print("\n💼 BALANÇO PATRIMONIAL - PASSIVO")
            print("-" * 80)
            for conta in ["2", "2.01", "2.02", "2.03"]:
                if conta in bpp_dict:
                    print(f"  {conta:15s} {formatar_valor_br(bpp_dict[conta]):>25s}")
            
            print("\n📈 DEMONSTRAÇÃO DO RESULTADO")
            print("-" * 80)
            for conta in ["3.01", "3.02", "3.03", "3.05", "3.11"]:
                if conta in dre_dict:
                    print(f"  {conta:15s} {formatar_valor_br(dre_dict[conta]):>25s}")
            
            print("\n" + "=" * 80)
            print("✅ EXTRAÇÃO CONCLUÍDA!")
            print("=" * 80)
            
        except Exception as e:
            print(f"\n❌ Erro geral: {e}")
        
        finally:
            browser.close()


if __name__ == "__main__":
    main()
