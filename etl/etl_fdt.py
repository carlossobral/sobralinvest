from playwright.sync_api import sync_playwright
import time

def diagnosticar_pagina(url):
    """
    Diagnostica a estrutura da página para encontrar os links corretos
    """
    print(f"🔍 Diagnosticando: {url}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()
        
        try:
            page.goto(url, wait_until='networkidle', timeout=60000)
            time.sleep(3)
            
            # 1. Ver todos os links da página
            print("=" * 60)
            print("📋 TODOS OS LINKS DA PÁGINA:")
            print("=" * 60)
            
            links = page.locator('a').all()
            for i, link in enumerate(links[:30]):  # Primeiros 30 links
                try:
                    texto = link.inner_text(timeout=2000).strip()
                    href = link.get_attribute('href')
                    if texto and href:
                        print(f"{i+1}. Texto: '{texto}'")
                        print(f"   HREF: {href}\n")
                except:
                    pass
            
            # 2. Verificar se há iframes
            print("=" * 60)
            print("🖼️ IFRAMES ENCONTRADOS:")
            print("=" * 60)
            
            frames = page.frames
            print(f"Total de frames: {len(frames)}\n")
            
            for i, frame in enumerate(frames):
                print(f"Frame {i+1}: {frame.url}")
                try:
                    links_frame = frame.locator('a').all()
                    if links_frame:
                        print(f"  → {len(links_frame)} links neste frame")
                        for link in links_frame[:5]:
                            try:
                                texto = link.inner_text(timeout=1000).strip()
                                if texto:
                                    print(f"    - {texto}")
                            except:
                                pass
                except:
                    pass
                print()
            
            # 3. Salvar HTML completo para análise
            print("=" * 60)
            print("💾 Salvando HTML da página...")
            print("=" * 60)
            
            html_content = page.content()
            with open('pagina_cvm.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("✅ Arquivo 'pagina_cvm.html' salvo!")
            
            # 4. Procurar por palavras-chave específicas
            print("\n" + "=" * 60)
            print("🔎 PROCURANDO PALAVRAS-CHAVE:")
            print("=" * 60)
            
            palavras = ['Balanço', 'Patrimonial', 'Resultado', 'Fluxo', 'Caixa']
            for palavra in palavras:
                count = html_content.lower().count(palavra.lower())
                print(f"'{palavra}': {count} ocorrências")
            
            browser.close()
            
        except Exception as e:
            print(f"❌ Erro: {str(e)}")
            browser.close()

# Executar diagnóstico
url_teste = "https://www.rad.cvm.gov.br/ENET/frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=157120&CodigoTipoInstituicao=1"
diagnosticar_pagina(url_teste)
