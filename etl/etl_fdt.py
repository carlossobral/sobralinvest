"""
ETL Fundamentus - MODO DEBUG (com diagnóstico completo)
"""

import requests
import pandas as pd
from datetime import datetime


def extrair_tabela_fundamentus() -> pd.DataFrame:
    """
    Acessa o site Fundamentus e extrai a tabela completa com diagnóstico
    """
    url = "https://www.fundamentus.com.br/resultado.php"
    
    print("=" * 80)
    print("🔍 DIAGNÓSTICO DE EXTRAÇÃO")
    print("=" * 80)
    print(f"\n🌐 URL: {url}")
    
    # Headers para simular navegador
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        print("\n📡 Fazendo requisição...")
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"✅ Status Code: {response.status_code}")
        print(f"✅ Content-Type: {response.headers.get('Content-Type')}")
        print(f"✅ Tamanho da resposta: {len(response.content)} bytes")
        
        if response.status_code != 200:
            print(f"❌ Erro: Status code {response.status_code}")
            return None
        
        # Salvar HTML para análise
        print("\n💾 Salvando HTML para análise...")
        with open('fundamentus_debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("✅ Arquivo 'fundamentus_debug.html' salvo")
        
        # Tentar extrair tabelas com pandas
        print("\n🔍 Tentando extrair tabelas com pandas...")
        try:
            tabelas = pd.read_html(response.text)
            print(f"✅ {len(tabelas)} tabela(s) encontrada(s)")
            
            if not tabelas:
                print("❌ Nenhuma tabela encontrada")
                return None
            
            # Mostrar info de cada tabela
            for i, df in enumerate(tabelas):
                print(f"\n📊 Tabela {i+1}:")
                print(f"   Linhas: {len(df)}")
                print(f"   Colunas: {len(df.columns)}")
                print(f"   Colunas: {list(df.columns)}")
                print(f"   Preview:")
                print(df.head(3).to_string())
            
            # Pegar a maior tabela (provavelmente a principal)
            df = max(tabelas, key=len)
            print(f"\n✅ Tabela selecionada: {len(df)} linhas, {len(df.columns)} colunas")
            
            return df
            
        except Exception as e:
            print(f"❌ Erro ao extrair com pandas: {e}")
            print("\n🔍 Tentando com BeautifulSoup...")
            
            # Fallback para BeautifulSoup
            try:
                from bs4 import BeautifulSoup
                
                soup = BeautifulSoup(response.text, 'html.parser')
                tabelas_html = soup.find_all('table')
                
                print(f"✅ {len(tabelas_html)} tabela(s) HTML encontrada(s)")
                
                for i, tabela in enumerate(tabelas_html):
                    linhas = tabela.find_all('tr')
                    print(f"\n📊 Tabela HTML {i+1}:")
                    print(f"   Linhas: {len(linhas)}")
                    
                    if linhas:
                        # Mostrar primeira linha (headers)
                        headers_linha = linhas[0].find_all(['th', 'td'])
                        print(f"   Headers: {[h.get_text().strip() for h in headers_linha]}")
                
                # Tentar converter a maior tabela
                if tabelas_html:
                    maior_tabela = max(tabelas_html, key=lambda t: len(t.find_all('tr')))
                    
                    # Extrair dados manualmente
                    linhas = maior_tabela.find_all('tr')
                    dados = []
                    
                    for linha in linhas[1:]:  # Pular header
                        cols = linha.find_all('td')
                        if cols:
                            dados.append([col.get_text().strip() for col in cols])
                    
                    if dados:
                        # Pegar headers
                        headers = [th.get_text().strip() for th in linhas[0].find_all(['th', 'td'])]
                        
                        # Criar DataFrame
                        df = pd.DataFrame(dados, columns=headers)
                        print(f"\n✅ DataFrame criado: {len(df)} linhas, {len(df.columns)} colunas")
                        print(f"   Colunas: {list(df.columns)}")
                        
                        return df
                
            except Exception as e2:
                print(f"❌ Erro com BeautifulSoup: {e2}")
                return None
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro de requisição: {e}")
        return None
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return None


def limpar_valor(valor) -> float | None:
    """
    Converte valores do formato brasileiro para float
    """
    if pd.isna(valor):
        return None
    
    valor_str = str(valor).strip()
    
    # Remover % e converter
    if '%' in valor_str:
        valor_str = valor_str.replace('%', '')
    
    # Remover pontos de milhar e converter vírgula para ponto
    valor_str = valor_str.replace('.', '').replace(',', '.')
    
    try:
        return float(valor_str)
    except ValueError:
        return None


def main():
    print("=" * 80)
    print("🔍 ETL FUNDAMENTUS - MODO DEBUG")
    print("=" * 80)
    
    # 1. Extrair dados com diagnóstico completo
    df = extrair_tabela_fundamentus()
    
    if df is None:
        print("\n❌ Falha na extração")
        print("\n📋 PRÓXIMOS PASSOS:")
        print("1. Verifique o arquivo 'fundamentus_debug.html'")
        print("2. Abra no navegador e veja se a tabela está lá")
        print("3. Me envie o conteúdo do arquivo para análise")
        return
    
    # 2. Mostrar dados brutos
    print("\n" + "=" * 80)
    print("📊 DADOS BRUTOS EXTRAÍDOS")
    print("=" * 80)
    print(df.head(10).to_string())
    
    # 3. Estatísticas
    print("\n" + "=" * 80)
    print("📈 ESTATÍSTICAS")
    print("=" * 80)
    print(f"Total de linhas: {len(df)}")
    print(f"Total de colunas: {len(df.columns)}")
    print(f"Colunas: {list(df.columns)}")
    
    # 4. Verificar tipos de dados
    print("\n🔍 TIPOS DE DADOS:")
    print(df.dtypes)
    
    # 5. Verificar valores nulos
    print("\n🔍 VALORES NULOS:")
    print(df.isnull().sum())
    
    print("\n" + "=" * 80)
    print("✅ EXTRAÇÃO CONCLUÍDA")
    print("=" * 80)


if __name__ == "__main__":
    main()
