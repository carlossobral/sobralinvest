"""
ETL CVM via XBRL - Download e Parsing de Demonstrações Financeiras
"""

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import re
from datetime import datetime


def obter_link_xbrl(url_enet: str) -> str | None:
    """
    A partir da URL do ENET, obtém o link para download do XBRL
    """
    print(f"🔗 Acessando ENET: {url_enet}")
    
    try:
        # Fazer request para a página do ENET
        response = requests.get(url_enet, timeout=30)
        response.raise_for_status()
        
        # Parsear HTML para encontrar link de download
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Procurar por botão/link de download XBRL
        # Geralmente tem um botão "Download" ou "XBRL"
        links = soup.find_all('a', href=True)
        
        for link in links:
            href = link['href']
            if 'XBRL' in href.upper() or 'DownloadDocumento' in href:
                print(f"✅ Link XBRL encontrado: {href}")
                return href
        
        print("❌ Link XBRL não encontrado")
        return None
        
    except Exception as e:
        print(f"❌ Erro ao acessar ENET: {e}")
        return None


def baixar_xbrl(url_xbrl: str, output_file: str = "demonstracao.xml") -> bool:
    """
    Baixa o arquivo XBRL da CVM
    """
    print(f"\n📥 Baixando XBRL...")
    
    try:
        response = requests.get(url_xbrl, timeout=60)
        response.raise_for_status()
        
        with open(output_file, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ Arquivo salvo: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao baixar XBRL: {e}")
        return False


def parsear_xbrl(xml_file: str) -> dict:
    """
    Faz parsing do arquivo XBRL e extrai dados financeiros
    """
    print(f"\n🔍 Parseando XBRL...")
    
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Remover namespaces para facilitar busca
        for elem in root.getiterator():
            if not hasattr(elem.tag, 'find'):
                continue
            i = elem.tag.find('}')
            if i >= 0:
                elem.tag = elem.tag[i+1:]
        
        dados = {
            'balanco_ativo': {},
            'balanco_passivo': {},
            'dre': {},
            'dfc': {}
        }
        
        # Procurar por elementos de demonstrações financeiras
        # XBRL usa tags específicas para cada conta contábil
        
        # Balanço Patrimonial
        for elem in root.iter():
            tag = elem.tag.lower()
            text = elem.text.strip() if elem.text else None
            
            if not text:
                continue
            
            # Converter valor brasileiro para float
            try:
                valor = float(text.replace('.', '').replace(',', '.'))
            except:
                continue
            
            # Identificar conta pelo nome ou contexto
            if 'ativo' in tag and 'total' in tag:
                dados['balanco_ativo']['1'] = valor
            elif 'passivo' in tag and 'total' in tag:
                dados['balanco_passivo']['2'] = valor
            elif 'receita' in tag and 'liquida' in tag:
                dados['dre']['3.01'] = valor
            elif 'lucro' in tag and 'liquido' in tag:
                dados['dre']['3.11'] = valor
        
        print(f"✅ Parsing concluído")
        print(f"   - Balanço Ativo: {len(dados['balanco_ativo'])} contas")
        print(f"   - Balanço Passivo: {len(dados['balanco_passivo'])} contas")
        print(f"   - DRE: {len(dados['dre'])} contas")
        print(f"   - DFC: {len(dados['dfc'])} contas")
        
        return dados
        
    except Exception as e:
        print(f"❌ Erro ao parsear XBRL: {e}")
        return None


def formatar_valor_br(valor) -> str:
    """Formata valor no padrão brasileiro"""
    if valor is None:
        return "N/A"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def exibir_resultados(dados: dict):
    """
    Exibe os dados extraídos de forma formatada
    """
    print("\n" + "=" * 80)
    print("📊 DADOS EXTRAÍDOS DO XBRL")
    print("=" * 80)
    
    # BALANÇO PATRIMONIAL ATIVO
    print("\n💼 BALANÇO PATRIMONIAL - ATIVO")
    print("-" * 80)
    bpa = dados.get('balanco_ativo', {})
    if bpa:
        for conta, valor in sorted(bpa.items()):
            print(f"  {conta:15s} {formatar_valor_br(valor):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")
    
    # BALANÇO PATRIMONIAL PASSIVO
    print("\n💼 BALANÇO PATRIMONIAL - PASSIVO")
    print("-" * 80)
    bpp = dados.get('balanco_passivo', {})
    if bpp:
        for conta, valor in sorted(bpp.items()):
            print(f"  {conta:15s} {formatar_valor_br(valor):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")
    
    # DRE
    print("\n📈 DEMONSTRAÇÃO DO RESULTADO")
    print("-" * 80)
    dre = dados.get('dre', {})
    if dre:
        for conta, valor in sorted(dre.items()):
            print(f"  {conta:15s} {formatar_valor_br(valor):>25s}")
    else:
        print("  ⚠️  Dados não extraídos")
    
    print("\n" + "=" * 80)


def main():
    print("=" * 80)
    print("🔍 ETL CVM via XBRL - Download e Parsing")
    print("=" * 80)
    
    # URL do ENET (PETR4 - 1T2026)
    url_enet = "https://www.rad.cvm.gov.br/ENET/frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=157120&CodigoTipoInstituicao=1"
    
    print(f"\n📋 URL ENET: {url_enet}\n")
    
    # 1. Obter link do XBRL
    url_xbrl = obter_link_xbrl(url_enet)
    
    if not url_xbrl:
        print("\n❌ Não foi possível obter o link do XBRL")
        return
    
    # 2. Baixar arquivo XBRL
    if not baixar_xbrl(url_xbrl, "petr4_1t2026.xml"):
        print("\n❌ Não foi possível baixar o XBRL")
        return
    
    # 3. Parsear XBRL
    dados = parsear_xbrl("petr4_1t2026.xml")
    
    if not dados:
        print("\n❌ Não foi possível parsear o XBRL")
        return
    
    # 4. Exibir resultados
    exibir_resultados(dados)
    
    print("\n✅ Processo concluído com sucesso!")


if __name__ == "__main__":
    main()
