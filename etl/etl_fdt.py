from playwright.sync_api import sync_playwright
import pandas as pd
import time
import re

def extrair_dados_cvm_playwright(url_cvm):
    """
    Extrai dados financeiros do site da CVM usando Playwright
    """
    print(f"🚀 Acessando: {url_cvm}")
    
    with sync_playwright() as p:
        # Iniciar navegador (headless=False para ver o que está acontecendo)
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()
        
        try:
            # Acessar a página principal
            page.goto(url_cvm, wait_until='networkidle', timeout=60000)
            print("✅ Página carregada com sucesso")
            
            # Aguardar um pouco para garantir que tudo carregou
            time.sleep(3)
            
            # Dicionário para armazenar todos os dados
            dados_extraidos = {}
            
            # Lista de seções para extrair
            secoes = [
                ('Balanço Patrimonial Ativo', 'balanco_ativo'),
                ('Balanço Patrimonial Passivo', 'balanco_passivo'),
                ('Demonstração do Resultado', 'dre'),
                ('Demonstração do Fluxo de Caixa', 'dfc')
            ]
            
            for nome_secao, chave in secoes:
                print(f"\n📊 Extraindo: {nome_secao}")
                
                try:
                    # Encontrar e clicar no link da seção
                    link = page.locator(f'a:has-text("{nome_secao}")').first
                    link.click()
                    
                    # Aguardar o iframe carregar
                    time.sleep(3)
                    
                    # Tentar acessar o iframe
                    frame = page.frames[-1]  # Geralmente o último frame é o conteúdo
                    
                    # Extrair a tabela
                    tabela_html = frame.locator('table').first.inner_html()
                    
                    # Fazer parsing da tabela
                    df = pd.read_html(f'<table>{tabela_html}</table>')[0]
                    
                    # Limpar e processar os dados
                    dados_extraidos[chave] = processar_tabela(df, chave)
                    
                    print(f"✅ {nome_secao} extraído com sucesso")
                    print(f"   Linhas: {len(df)}")
                    
                    # Voltar para a página principal
                    page.go_back()
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"❌ Erro ao extrair {nome_secao}: {str(e)}")
                    dados_extraidos[chave] = None
            
            browser.close()
            return dados_extraidos
            
        except Exception as e:
            print(f"❌ Erro geral: {str(e)}")
            browser.close()
            return None

def processar_tabela(df, tipo):
    """
    Processa e limpa os dados da tabela
    """
    # Remover colunas vazias
    df = df.dropna(axis=1, how='all')
    
    # Renomear colunas baseado no tipo
    if tipo == 'balanco_ativo':
        df.columns = ['Conta', 'Descrição', 'Valor']
    elif tipo == 'balanco_passivo':
        df.columns = ['Conta', 'Descrição', 'Valor']
    elif tipo == 'dre':
        df.columns = ['Conta', 'Descrição', 'Valor']
    elif tipo == 'dfc':
        df.columns = ['Conta', 'Descrição', 'Valor']
    
    # Converter valores numéricos
    def converter_valor(valor):
        if pd.isna(valor):
            return None
        # Remover pontos de milhar e converter vírgula para ponto
        valor_str = str(valor).replace('.', '').replace(',', '.')
        try:
            return float(valor_str)
        except:
            return None
    
    df['Valor'] = df['Valor'].apply(converter_valor)
    
    return df

def extrair_dados_especificos(dados_extraidos):
    """
    Extrai os dados específicos que você precisa
    """
    resultado = {
        'balanco': {},
        'dre': {},
        'dfc': {}
    }
    
    # Balanço Patrimonial
    if dados_extraidos.get('balanco_ativo') is not None:
        df_ativo = dados_extraidos['balanco_ativo']
        
        # Extrair contas específicas
        for _, row in df_ativo.iterrows():
            conta = str(row['Conta']).strip()
            valor = row['Valor']
            
            if conta == '1':
                resultado['balanco']['ativo_total'] = valor
            elif conta == '1.01':
                resultado['balanco']['ativo_circulante'] = valor
            elif conta.startswith('1.01.01'):
                resultado['balanco']['caixa'] = resultado['balanco'].get('caixa', 0) + (valor or 0)
            elif conta.startswith('1.01.02'):
                resultado['balanco']['caixa'] = resultado['balanco'].get('caixa', 0) + (valor or 0)
    
    if dados_extraidos.get('balanco_passivo') is not None:
        df_passivo = dados_extraidos['balanco_passivo']
        
        for _, row in df_passivo.iterrows():
            conta = str(row['Conta']).strip()
            valor = row['Valor']
            
            if conta == '2.01':
                resultado['balanco']['passivo_circulante'] = valor
            elif conta == '2.02':
                resultado['balanco']['passivo_nao_circulante'] = valor
            elif conta == '2.03':
                resultado['balanco']['patrimonio_liquido'] = valor
            elif conta.startswith('2.01.04'):
                resultado['balanco']['divida_cp'] = valor
            elif conta.startswith('2.02.01'):
                resultado['balanco']['divida_lp'] = valor
    
    # Calcular dívida bruta e líquida
    divida_cp = resultado['balanco'].get('divida_cp', 0) or 0
    divida_lp = resultado['balanco'].get('divida_lp', 0) or 0
    caixa = resultado['balanco'].get('caixa', 0) or 0
    
    resultado['balanco']['divida_bruta'] = divida_cp + divida_lp
    resultado['balanco']['divida_liquida'] = (divida_cp + divida_lp) - caixa
    
    # DRE
    if dados_extraidos.get('dre') is not None:
        df_dre = dados_extraidos['dre']
        
        for _, row in df_dre.iterrows():
            conta = str(row['Conta']).strip()
            valor = row['Valor']
            
            if conta == '3.01':
                resultado['dre']['receita_liquida'] = valor
            elif conta == '3.02':
                resultado['dre']['custo'] = abs(valor) if valor else 0
            elif conta == '3.03':
                resultado['dre']['lucro_bruto'] = valor
            elif conta == '3.05':
                resultado['dre']['ebit'] = valor
            elif conta == '3.11':
                resultado['dre']['lucro_liquido'] = valor
    
    # DFC
    if dados_extraidos.get('dfc') is not None:
        df_dfc = dados_extraidos['dfc']
        
        for _, row in df_dfc.iterrows():
            conta = str(row['Conta']).strip()
            valor = row['Valor']
            
            if conta == '6.01':
                resultado['dfc']['caixa_operacional'] = valor
            elif conta == '6.02':
                resultado['dfc']['caixa_investimento'] = valor
            elif conta == '6.03':
                resultado['dfc']['caixa_financiamento'] = valor
    
    return resultado

# Executar o teste
if __name__ == "__main__":
    url_teste = "https://www.rad.cvm.gov.br/ENET/frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=157120&CodigoTipoInstituicao=1"
    
    print("=" * 60)
    print("🧪 TESTE DE EXTRAÇÃO COM PLAYWRIGHT")
    print("=" * 60)
    
    dados_brutos = extrair_dados_cvm_playwright(url_teste)
    
    if dados_brutos:
        print("\n" + "=" * 60)
        print("📊 DADOS ESTRUTURADOS")
        print("=" * 60)
        
        dados_finais = extrair_dados_especificos(dados_brutos)
        
        print("\n💰 BALANÇO PATRIMONIAL (R$ Mil):")
        for chave, valor in dados_finais['balanco'].items():
            print(f"  {chave}: {valor:,.2f}" if valor else f"  {chave}: N/A")
        
        print("\n📈 DEMONSTRAÇÃO DO RESULTADO (R$ Mil):")
        for chave, valor in dados_finais['dre'].items():
            print(f"  {chave}: {valor:,.2f}" if valor else f"  {chave}: N/A")
        
        print("\n💸 FLUXO DE CAIXA (R$ Mil):")
        for chave, valor in dados_finais['dfc'].items():
            print(f"  {chave}: {valor:,.2f}" if valor else f"  {chave}: N/A")
        
        print("\n" + "=" * 60)
        print("✅ TESTE CONCLUÍDO COM SUCESSO!")
        print("=" * 60)
    else:
        print("\n❌ TESTE FALHOU")
