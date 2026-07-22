import os
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
import plotly.graph_objects as go

# ==========================================================
# 1. CONFIGURAÇÃO DA PÁGINA E CONEXÃO SUPABASE
# ==========================================================
st.set_page_config(page_title="Sobral Invest", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display: none;}
        section[data-testid="stSidebar"] { display: none !important; }
        button[kind="header"] { display: none !important; }
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

@st.cache_resource
def init_supabase():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(dotenv_path=env_path)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Credenciais do Supabase não encontradas.")
        st.stop()
        return None
    return create_client(url, key)

supabase = init_supabase()

# ==========================================================
# 2. CSS GLOBAL (TEMA ESCURO, CARDS E TOOLTIPS)
# ==========================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
.c * { font-family: 'Inter', sans-serif; } .c { padding: 0 8px 40px 8px; }

/* --- SOLUÇÃO STICKY HEADER VIA JS (Fixed + Placeholder) --- */
.header-container {
    position: relative !important; /* Estado normal */
    border-bottom: 1px solid var(--secondary-background-color, #262730) !important;
    padding: 1rem 0 !important;
    margin: 0 !important;
    background-color: var(--background-color, #0e1117) !important;
    z-index: 9998;
    transition: box-shadow 0.3s ease;
}

/* Estado fixo aplicado pelo JavaScript */
.header-container.is-sticky {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    z-index: 9999 !important;
    background-color: rgba(14, 17, 23, 0.95) !important; /* Leve transparência */
    backdrop-filter: blur(8px) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4) !important;
    padding: 0.8rem 0 !important; /* Leve redução no padding ao ficar fixo */
    animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
    from { transform: translateY(-100%); }
    to { transform: translateY(0); }
}

.header-brand { display: flex; align-items: center; gap: 12px; }
.header-brand-name { font-size: 1.4rem; font-weight: 800; color: #f1f5f9; letter-spacing: -0.03em; line-height: 1.2; }
.header-brand-tag { font-size: 0.75rem; color: #64748b; font-weight: 500; }
.header-context { text-align: right; }
.header-page-title { font-size: 1.1rem; font-weight: 600; color: #38bdf8; margin-bottom: 2px; }
.header-subtitle { font-size: 0.8rem; color: #94a3b8; }

.st { font-size: 1.05rem; font-weight: 700; color: #f1f5f9; text-transform: uppercase; letter-spacing: 0.1em; margin: 40px 0 22px 0; padding-bottom: 10px; border-bottom: 2px solid #334155; display: flex; align-items: center; gap: 10px; }
.mc { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 12px; padding: 18px 16px; transition: all 0.3s ease; box-shadow: 0 2px 4px rgba(0,0,0,0.1); height: 100%; display: flex; flex-direction: column; justify-content: space-between; min-height: 95px; }
.mc:hover { transform: translateY(-2px); box-shadow: 0 8px 12px rgba(0,0,0,0.25); border-color: #3b82f6; }
.ml { position: relative; font-size: 0.72rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; line-height: 1.3; }
.mv { font-size: 1.45rem; font-weight: 700; color: #f1f5f9; line-height: 1.1; letter-spacing: -0.02em; }
.sc { border-radius: 16px; padding: 24px; text-align: center; box-shadow: 0 10px 15px rgba(0,0,0,0.2); }
.sn { font-size: 3.5rem; font-weight: 800; line-height: 1; margin-bottom: 8px; }
.sl { font-size: 1.1rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; }
.sd { font-size: 0.8rem; color: #94a3b8; margin-top: 6px; }

.ranking-card { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 12px; padding: 4px 10px 14px 10px; margin-bottom: 0.75rem; transition: all 0.3s ease; text-align: center; height: 100%; }
.ranking-card:hover { transform: translateY(-3px); box-shadow: 0 8px 16px rgba(0,0,0,0.3); border-color: #3b82f6; }
.ranking-nome { font-size: 0.72rem; color: #94a3b8; margin: 0 0 8px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.2; }
.ranking-valor { font-size: 1.35rem; font-weight: 800; color: #38bdf8; margin: 6px 0; line-height: 1.1; }
.ranking-footer { display: flex; justify-content: space-between; align-items: center; font-size: 0.68rem; margin-top: 8px; padding-top: 8px; border-top: 1px solid #334155; }

.tt { position: relative; display: inline-block; cursor: help; vertical-align: middle; }
.tt-i { display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px; border-radius: 50%; background: #475569; color: #f1f5f9; font-size: 10px; font-weight: 700; margin-left: 4px; }
.tt-t { visibility: hidden; opacity: 0; width: 250px; background-color: #1e293b; border: 1px solid #475569; color: #e2e8f0; text-align: left; border-radius: 6px; padding: 10px; position: absolute; z-index: 9999; top: 20px; left: 50%; transform: translateX(-50%); transition: opacity 0.3s ease; font-size: 0.8rem; line-height: 1.4; box-shadow: 0 4px 6px rgba(0,0,0,0.3); pointer-events: none; }
.tt:hover .tt-t { visibility: visible; opacity: 1; }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 3. SCRIPT JAVASCRIPT PARA STICKY HEADER (Bypass do Overflow do Streamlit)
# ==========================================================
sticky_header_js = """
<script>
(function() {
    // Previne múltiplas inicializações
    if (window.stickyHeaderInitialized) return;
    
    function initSticky() {
        const header = document.querySelector('.header-container');
        if (!header) return;
        
        // Cria um placeholder invisível para evitar que o conteúdo "pule" quando o header ficar fixed
        let placeholder = document.getElementById('header-placeholder');
        if (!placeholder) {
            placeholder = document.createElement('div');
            placeholder.id = 'header-placeholder';
            placeholder.style.display = 'none';
            // Insere o placeholder imediatamente antes do header
            header.parentNode.insertBefore(placeholder, header);
        }

        window.addEventListener('scroll', function() {
            const rect = header.getBoundingClientRect();
            // Quando o topo do header está prestes a sair da viewport (buffer de 10px)
            if (rect.top <= 10) {
                if (!header.classList.contains('is-sticky')) {
                    placeholder.style.height = rect.height + 'px';
                    placeholder.style.display = 'block';
                    header.classList.add('is-sticky');
                }
            } else {
                if (header.classList.contains('is-sticky')) {
                    placeholder.style.display = 'none';
                    header.classList.remove('is-sticky');
                }
            }
        });
        
        window.stickyHeaderInitialized = true;
    }

    // Executa imediatamente e monitora mudanças no DOM (Streamlit re-renderiza)
    initSticky();
    setInterval(initSticky, 1000); 
})();
</script>
"""
components.html(sticky_header_js, height=0, width=0)

# ==========================================================
# 4. TOOLTIPS E FUNÇÕES AUXILIARES
# ==========================================================
TOOLTIPS = {
    "P/L": "Preço sobre o Lucro. Demonstra quanto o mercado está disposto a pagar pelos lucros da empresa.",
    "P/VP": "Preço sobre o Valor Patrimonial. Abaixo de 1, indica que a empresa está sendo vendida por menos que seu valor real.",
    "LPA": "Lucro por Ação. Indicador que mostra se a empresa é lucrativa.",
    "P/Receita": "Price to Sales Ratio (PSR). Compara o preço da ação com as vendas.",
    "P/Ativo": "Preço sobre Total de Ativos. Um P/Ativo inferior a 1, quer dizer que o preço da ação está menor que os seus próprios ativos.",
    "P/Cap. Giro": "Mede se a empresa está sendo negociada a um preço justo em comparação com sua capacidade de cobrir suas obrigações de curto prazo.",
    "DY 12m": "Dividend Yield. Mostra o rendimento obtido por uma ação através dos proventos distribuídos pela empresa nos últimos 12 meses.",
    "P/Ativo Circ. Líq.": "Compara o preço da ação com os ativos circulantes líquidos da empresa.",
    "P/EBIT": "Preço sobre EBIT. Medida da lucratividade que exclui juros e impostos.",
    "P/EBITDA": "Preço sobre EBITDA. Medida da lucratividade que exclui juros, impostos, depreciação e amortização.",
    "EV/EBIT": "Valor da empresa sobre EBIT.",
    "EV/EBITDA": "Indica quantos anos seriam necessários para que a empresa pagasse o seu próprio valor de mercado utilizando apenas o seu lucro operacional.",
    "ROE": "Return on Equity. Mede a eficiência de uma empresa em gerar lucro a partir do capital investido pelos próprios sócios.",
    "ROA": "Retorno sobre o Ativo. Mede a eficiência com que uma empresa utiliza seus ativos para gerar lucro.",
    "ROIC": "Retorno sobre o Capital Investido. Mede o retorno sobre o capital investido.",
    "Giro Ativos": "Mede a capacidade da empresa em gerar receita com seus ativos.",
    "Margem Bruta": "Indica a eficiência da empresa em transformar suas vendas em lucro, excluindo os custos variáveis.",
    "Margem EBITDA": "Mede a eficiência operacional de uma empresa.",
    "Margem EBIT": "Mede a produtividade e serve como comparação de lucratividade operacional.",
    "Margem Líquida": "Indica quanto da receita é convertida em lucro.",
    "Dív. Líq/Ativos": "Dívida Líq / Ativos. < 0.5 bom.",
    "Dív. Líq/PL": "Mede o nível de endividamento em relação ao capital próprio. < 1 ideal.",
    "Dív. Líq/EBIT": "Mostra, em anos, quanto tempo a companhia levaria para pagar suas dívidas utilizando exclusivamente o seu lucro operacional. < 3 bom.",
    "Dív. Líq/EBITDA": "Calcula quantos anos a empresa levaria para pagar todas as suas dívidas usando apenas o seu lucro operacional (EBITDA). < 2.5 saudável.",
    "Liq. Corrente": "Mede a capacidade de uma empresa de pagar suas dívidas correntes usando apenas seus ativos correntes.",
    "Passivo/Ativos": "Indica o quanto a empresa está endividada em relação a seus ativos.",
    "Patrimonio/Ativos": "Indica quanto a empresa possui em ativos em comparação com suas obrigações.",
    "VPA": "Valor Patrimonial por Ação. Representa quanto vale uma ação da empresa em relação a todo seu patrimônio.",
    "Patrim. Líq.": "Patrimônio Líquido da empresa. Ativos menos passivos.",
    "Lucro Líquido": "Lucro após impostos e despesas. Base para dividendos.",
    "EBIT": "Lucro antes de juros e impostos. Mede eficiência operacional.",
    "Receita Líq.": "Receita total da empresa após deduções.",
    "CAGR Receitas 5a": "Crescimento anual composto da receita nos últimos 5 anos.",
    "CAGR Lucros 5a": "Crescimento anual composto do lucro nos últimos 5 anos.",
    "Graham": "Preço justo pelo método clássico de Benjamin Graham: √(22.5 × LPA × VPA).",
    "Graham BR": "Preço justo pelo método conservador de Graham para o Brasil: √(15 × LPA × VPA).",
    "Bazin": "Preço teto pelo método de Décio Bazin: foco em dividendos com yield alvo de 6%.",
    "AGF (Barsi)": "Método AGF, utilizado pelo maior investidor PF da B3, Luiz Barsi Filho",
    "Cobertura Juros": "EBIT / Despesa Financeira. Mede a capacidade de pagar juros. > 3 é seguro."
}

def safe(v, d=0.0):
    try: return float(v) if v is not None and pd.notna(v) else d
    except: return d

def tooltip(t):
    d = TOOLTIPS.get(t, "")
    return f'<span class="tt"><span class="tt-i">?</span><span class="tt-t">{d}</span></span>' if d else ""

def sem_color(label, val_str):
    try:
        val = float(str(val_str).replace('R$','').replace('x','').replace('%','').replace('+','').replace(',','').strip())
    except:
        return "#94a3b8"
    
    l = label.lower()
    
    if any(k in l for k in ["p/l", "p/vp", "ev/ebit", "ev/ebitda", "dív. líq", "passivo/ativos", "p/receita", "p/ativo", "p/cap", "p/ebit", "p/ativo circ"]):
        return "#10b981" if val < 10 else ("#f59e0b" if val < 20 else "#ef4444")
        
    if any(k in l for k in ["roe", "roic", "roa", "margem", "dy", "cagr", "giro", "patrimonio/ativos", "liq. corrente", "cobertura"]):
        return "#10b981" if val > 15 else ("#f59e0b" if val > 5 else "#ef4444")
        
    return "#38bdf8"

# ==========================================================
# 5. FUNÇÕES DE DADOS
# ==========================================================
@st.cache_data(ttl=3600)
def load_data():
    resp_score = supabase.table("score").select("ticker, score, rentabilidade, crescimento, seguranca, dividendos, valuation, data_balanco").order("data_balanco", desc=True).limit(1000).execute()
    df_score = pd.DataFrame(resp_score.data)
    if df_score.empty: return pd.DataFrame()
    
    data_max = df_score['data_balanco'].max()
    df_score = df_score[df_score['data_balanco'] == data_max]
    
    resp_ind = supabase.table("indicadores").select("*").eq("data_balanco", data_max).execute()
    df_ind = pd.DataFrame(resp_ind.data)
    
    resp_emp = supabase.table("empresas").select("ticker, nome, setor, subsetor, segmento, qtd_acoes_totais").execute()
    df_emp = pd.DataFrame(resp_emp.data)
    
    df = df_score.merge(df_emp, on="ticker", how="left")
    df = df.merge(df_ind, on="ticker", how="left")
    
    resp_cot_date = supabase.table("cotacoes").select("data").order("data", desc=True).limit(1).execute()
    if resp_cot_date.data:
        latest_date = resp_cot_date.data[0]['data']
        resp_cot = supabase.table("cotacoes").select("ticker, fechamento").eq("data", latest_date).execute()
        df_cot = pd.DataFrame(resp_cot.data).rename(columns={'fechamento': 'preco_atual'})
        df = df.merge(df_cot, on='ticker', how='left')
    else:
        df['preco_atual'] = 0

    if 'preco_atual' in df.columns and 'qtd_acoes_totais' in df.columns:
        df['valor_mercado'] = df['preco_atual'] * df['qtd_acoes_totais']
        
    return df

@st.cache_data(ttl=3600)
def get_ativo_detalhado(ticker):
    emp = supabase.table("empresas").select("*").eq("ticker", ticker).execute().data
    if not emp: return None
    emp = emp[0]
    
    sc = supabase.table("score").select("*").eq("ticker", ticker).order("data_balanco", desc=True).limit(1).execute().data
    if sc: emp.update(sc[0])
        
    ind = supabase.table("indicadores").select("*").eq("ticker", ticker).order("data_balanco", desc=True).limit(1).execute().data
    if ind: emp.update(ind[0])
        
    cot = supabase.table("cotacoes").select("fechamento, data").eq("ticker", ticker).order("data", desc=True).limit(1).execute().data
    if cot:
        emp["preco_atual"] = cot[0]["fechamento"]
        emp["data_cotacao"] = cot[0]["data"]
    else:
        emp["preco_atual"] = 0
        
    return emp

# ==========================================================
# 6. HEADER UNIFICADO
# ==========================================================
def render_header(pagina, ticker_sel=None):
    titulo_pagina = ""
    subtitulo = ""
    
    if pagina == "home":
        titulo_pagina = "🏠 Home"
        subtitulo = "Dashboard & Mercado"
    elif pagina == "analise":
        titulo_pagina = "🔍 Análise"
        subtitulo = f"Ativo: {ticker_sel}" if ticker_sel else "Selecione um ativo"
    elif pagina == "rankings":
        titulo_pagina = "🏆 Rankings"
        subtitulo = "Top 50 Ativos & Valuation"
    elif pagina == "comparativo":
        titulo_pagina = "📊 Comparativo"
        subtitulo = "Análise Relativa"

    st.markdown(f"""
    <div class="header-container">
        <div class="header-brand">
            <div>
                <div class="header-brand-name">SOBRAL Invest</div>
                <div class="header-brand-tag">Análise Fundamentalista & Valuation</div>
            </div>
        </div>
        <div class="header-context">
            <div class="header-page-title">{titulo_pagina}</div>
            <div class="header-subtitle">{subtitulo}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ==========================================================
# 7. PÁGINAS
# ==========================================================
def pagina_home():
    render_header("home")
    
    st.markdown("### 📈 Ibovespa")
    components.html("""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>{"symbols": [["BMFBOVESPA:IBOV|1D"]], "chartOnly": false, "width": "100%", "height": "400", "locale": "br", "colorTheme": "dark", "autosize": false, "showVolume": true}</script></div>""", height=420)
    
    st.markdown("### 🚀 Maiores Altas e Baixas (B3)")
    components.html("""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-hotlists.js" async>
      {
        "colorTheme": "dark",
        "dateRange": "1D",
        "exchange": "BMFBOVESPA",
        "showChart": true,
        "locale": "br",
        "largeChartUrl": "",
        "isTransparent": false,
        "showSymbolLogo": true,
        "showFloatingTooltip": true,
        "width": "100%",
        "height": "550",
        "plotLineColorGrowing": "rgba(41, 98, 255, 1)",
        "plotLineColorFalling": "rgba(41, 98, 255, 1)",
        "plotLineColorGrowingBottom": "rgba(41, 98, 255, 0)",
        "plotLineColorFallingBottom": "rgba(41, 98, 255, 0)",
        "gridLineColor": "rgba(42, 46, 57, 0)",
        "scaleFontColor": "rgba(120, 123, 134, 1)",
        "belowLineFillColorGrowing": "rgba(41, 98, 255, 0.12)",
        "belowLineFillColorFalling": "rgba(41, 98, 255, 0.12)",
        "belowLineFillColorGrowingBottom": "rgba(41, 98, 255, 0)",
        "belowLineFillColorFallingBottom": "rgba(41, 98, 255, 0)",
        "symbolActiveColor": "rgba(41, 98, 255, 0.12)",
        "tabs": [
          {
            "title": "Mais Negociadas",
            "symbols": [
              { "s": "BMFBOVESPA:PETR4", "d": "Petrobras" },
              { "s": "BMFBOVESPA:VALE3", "d": "Vale" },
              { "s": "BMFBOVESPA:ITUB4", "d": "Itau Unibanco" },
              { "s": "BMFBOVESPA:BBDC4", "d": "Bradesco" },
              { "s": "BMFBOVESPA:ABEV3", "d": "Ambev" },
              { "s": "BMFBOVESPA:WEGE3", "d": "Weg" },
              { "s": "BMFBOVESPA:BBAS3", "d": "Banco do Brasil" }
            ],
            "originalTitle": "Equities"
          },
          {
            "title": "Maiores Altas",
            "symbols": [{ "s": "BMFBOVESPA:IBOV", "d": "Ibovespa" }]
          },
          {
            "title": "Maiores Baixas",
            "symbols": [{ "s": "BMFBOVESPA:IBOV", "d": "Ibovespa" }]
          }
        ]
      }
      </script>
    </div>
    """, height=560)

def pagina_analise():
    df = load_data()
    if df.empty:
        render_header("analise")
        st.warning("Dados não disponíveis.")
        return
        
    df['Disp'] = (df['ticker'].astype(str).fillna('') + ' - ' + df['nome'].astype(str).fillna('')).astype(str)
    opts = sorted(df['Disp'].tolist())
    
    sel = st.selectbox("Selecione o ativo", options=opts)
    ticker = sel.split(' - ')[0]
    
    render_header("analise", ticker)
    
    st.markdown('<div class="c">', unsafe_allow_html=True)
    
    ativo = get_ativo_detalhado(ticker)
    if not ativo: return

    st.markdown(f"""
    <div style="display: flex; gap: 20px; margin: 8px 0 16px 0; align-items: center; flex-wrap: wrap;">
        <div><span style="font-size: 0.7rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;">Setor</span><span style="font-size: 0.85rem; font-weight: 500; color: #f1f5f9; margin-left: 8px;">{ativo.get('setor', 'N/A')}</span></div>
        <div style="color: #475569;">&rsaquo;</div>
        <div><span style="font-size: 0.7rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;">SubSetor</span><span style="font-size: 0.85rem; font-weight: 500; color: #f1f5f9; margin-left: 8px;">{ativo.get('subsetor', 'N/A')}</span></div>
        <div style="color: #475569;">&rsaquo;</div>
        <div><span style="font-size: 0.7rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;">Segmento</span><span style="font-size: 0.85rem; font-weight: 500; color: #f1f5f9; margin-left: 8px;">{ativo.get('segmento', 'N/A')}</span></div>
    </div>
    """, unsafe_allow_html=True)

    components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>{{"symbols": [["BMFBOVESPA:{ticker}|1D"]], "chartOnly": false, "width": "100%", "height": "350", "locale": "br", "colorTheme": "dark"}}</script></div>""", height=360)

    def sec(title, data, cols):
        st.markdown(f'<div class="st">{title}</div>', unsafe_allow_html=True)
        for r in range(2 if len(data) > cols else 1):
            cs = st.columns(cols)
            for c in range(cols):
                i = r * cols + c
                if i < len(data):
                    lbl, val = data[i]
                    cl = sem_color(lbl, val)
                    cs[c].markdown(f"""<div class="mc" style="border-left: 4px solid {cl};"><div class="ml">{lbl} {tooltip(lbl)}</div><div class="mv" style="color: {cl};">{val}</div></div>""", unsafe_allow_html=True)

    sec("Valuation", [
        ("P/L", f"{safe(ativo.get('p_l')):.2f}x"), 
        ("P/VP", f"{safe(ativo.get('p_vp')):.2f}x"), 
        ("LPA", f"R$ {safe(ativo.get('lpa')):.2f}"), 
        ("P/Receita", f"{safe(ativo.get('p_receita')):.2f}x"), 
        ("P/Ativo", f"{safe(ativo.get('p_ativo')):.2f}x"), 
        ("P/Cap. Giro", f"{safe(ativo.get('p_cap_giro')):.2f}x"),
        ("DY 12m", f"{safe(ativo.get('dy_atual'))*100:.2f}%"),
        ("P/Ativo Circ. Líq.", f"{safe(ativo.get('p_ativo_circ_liq')):.2f}x"), 
        ("P/EBIT", f"{safe(ativo.get('p_ebit')):.2f}x"), 
        ("P/EBITDA", f"{safe(ativo.get('p_ebitda')):.2f}x"), 
        ("EV/EBIT", f"{safe(ativo.get('ev_ebit')):.2f}x"), 
        ("EV/EBITDA", f"{safe(ativo.get('ev_ebitda')):.2f}x")
    ], 6)
    
    sec("Rentabilidade", [
        ("ROE", f"{safe(ativo.get('roe'))*100:.2f}%"), 
        ("ROA", f"{safe(ativo.get('roa'))*100:.2f}%"), 
        ("ROIC", f"{safe(ativo.get('roic'))*100:.2f}%"), 
        ("Giro Ativos", f"{safe(ativo.get('giro_ativos')):.2f}x"), 
        ("Margem Bruta", f"{safe(ativo.get('margem_bruta'))*100:.2f}%"), 
        ("Margem EBITDA", f"{safe(ativo.get('margem_ebitda'))*100:.2f}%"), 
        ("Margem EBIT", f"{safe(ativo.get('margem_ebit'))*100:.2f}%"), 
        ("Margem Líquida", f"{safe(ativo.get('margem_liquida'))*100:.2f}%")
    ], 4)
    
    sec("Endividamento", [
        ("Dív. Líq/Ativos", f"{safe(ativo.get('div_liq_ativos')):.2f}x"), 
        ("Dív. Líq/PL", f"{safe(ativo.get('div_liq_pl')):.2f}x"), 
        ("Dív. Líq/EBIT", f"{safe(ativo.get('div_liq_ebit')):.2f}x"), 
        ("Dív. Líq/EBITDA", f"{safe(ativo.get('div_liq_ebitda')):.2f}x"), 
        ("Liq. Corrente", f"{safe(ativo.get('liquidez_corrente')):.2f}x"), 
        ("Passivo/Ativos", f"{safe(ativo.get('passivos_ativos')):.2f}x"), 
        ("Patrimonio/Ativos", f"{safe(ativo.get('pl_ativos')):.2f}x"),
        ("Cobertura Juros", f"{safe(ativo.get('cobertura_juros')):.2f}x")
    ], 4)
    
    sec("Resultado", [
        ("LPA", f"R$ {safe(ativo.get('lpa')):.2f}"), 
        ("VPA", f"R$ {safe(ativo.get('vpa')):.2f}"), 
        ("Patrim. Líq.", f"R$ {safe(ativo.get('pl_absoluto'))/1e9:.2f}B"), 
        ("Lucro Líquido", f"R$ {safe(ativo.get('lucro_liquido'))/1e9:.2f}B"), 
        ("EBIT", f"R$ {safe(ativo.get('ebit'))/1e9:.2f}B"), 
        ("Receita Líq.", f"R$ {safe(ativo.get('receita_liquida'))/1e9:.2f}B")
    ], 6)
    
    sec("Crescimento", [
        ("CAGR Receitas 5a", f"{safe(ativo.get('cagr_receita_5a'))*100:.2f}%"), 
        ("CAGR Lucros 5a", f"{safe(ativo.get('cagr_lucro_5a'))*100:.2f}%")
    ], 2)

    st.markdown('<div class="st">Preco Teto | Preco Justo</div>', unsafe_allow_html=True)
    pr = safe(ativo.get("preco_atual"))
    pj = [
        ("Graham", safe(ativo.get('graham'))), 
        ("Graham BR", safe(ativo.get('graham_br'))), 
        ("Bazin", safe(ativo.get('bazin'))), 
        ("AGF (Barsi)", safe(ativo.get('agf')))
    ]
    cps = st.columns(4)
    for i, (t, p) in enumerate(pj):
        ups = ((p - pr) / pr) * 100 if pr > 0 and p > 0 else 0
        c = "#10b981" if ups > 0 else "#ef4444"
        price_str = f"R$ {p:.2f}" if p > 0 else "N/A"
        cps[i].markdown(f"""<div class="mc" style="text-align: center;"><div class="ml">{t} {tooltip(t)}</div><div class="mv">{price_str}</div><div style="color:{c}; font-weight:700;">{ups:+.1f}%</div></div>""", unsafe_allow_html=True)

    st.markdown('<div class="st">SCORE CS 3.0</div>', unsafe_allow_html=True)
    score = safe(ativo.get('score'))
    col, bg, lbl = ("#10b981", "#065f46", "Excelente") if score >= 80 else (("#84cc16", "#3f6212", "Bom") if score >= 60 else (("#f59e0b", "#92400e", "Regular") if score >= 40 else (("#f97316", "#7c2d12", "Fraco") if score >= 20 else ("#dc2626", "#7f1d1d", "Péssimo"))))
    
    st.markdown(f"""<div class="sc" style="background: linear-gradient(135deg, {bg} 0%, {col}20 100%); border: 2px solid {col}; max-width: 300px; margin: 0 auto 24px auto;"><div class="sn" style="color: {col};">{score:.0f}</div><div class="sl" style="color: {col};">{lbl}</div><div class="sd">de 100 pontos</div></div>""", unsafe_allow_html=True)
    
    cps2 = st.columns(5)
    pilares = [
        ("Rentabilidade", ativo.get('rentabilidade')), 
        ("Crescimento", ativo.get('crescimento')), 
        ("Segurança", ativo.get('seguranca')), 
        ("Dividendos", ativo.get('dividendos')), 
        ("Valuation", ativo.get('valuation'))
    ]
    for i, (t, v) in enumerate(pilares):
        cps2[i].markdown(f"""<div class="mc" style="text-align: center;"><div class="ml">{t}</div><div class="mv">{safe(v):.1f}</div></div>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

def pagina_rankings():
    render_header("rankings")
    df = load_data()
    if df.empty: return

    setores = ["Todos"] + sorted([str(x) for x in df['setor'].dropna().unique().tolist() if str(x) not in ['nan', 'N/A', '#N/A', '']])
    subsetores = ["Todos"] + sorted([str(x) for x in df['subsetor'].dropna().unique().tolist() if str(x) not in ['nan', 'N/A', '#N/A', '']])

    rankings = ["Selecione...", "Maior Valor de Mercado", "Maiores Lucros", "Maiores Receitas", "Maiores Dividend Yield", "Menores P/L", "Maiores ROE", "Maior Upside AGF", "Mais Baratas - Graham", "Mais Baratas - Bazin", "Menores P/VP", "Menor EV/EBITDA", "Maior CAGR Lucros 5a", "Maior CAGR Receitas 5a", "Maior Margem Liquida", "Menor Divida Liq/EBITDA", "Maiores Scores 3.0"]

    col_f1, col_f2, col_f3, col_f4 = st.columns([1.5, 1.5, 1.5, 2])
    with col_f1: setor_sel = st.selectbox("Setor", setores, key="rank_setor")
    with col_f2: subsetor_sel = st.selectbox("SubSetor", subsetores, key="rank_subsetor")
    with col_f3: ranking_sel = st.selectbox("Ranking", rankings, key="rank_select")
    with col_f4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.markdown(f'<p style="color:#94a3b8; font-size:0.85rem;">{len(df)} ativos carregados</p>', unsafe_allow_html=True)

    df_filt = df.copy()
    if setor_sel != "Todos": df_filt = df_filt[df_filt['setor'] == setor_sel]
    if subsetor_sel != "Todos": df_filt = df_filt[df_filt['subsetor'] == subsetor_sel]

    if ranking_sel == "Selecione..." or ranking_sel == "":
        st.info("Selecione um ranking acima.")
        return

    def render_ranking(df_rank, col_indicador, titulo, fmt_func, is_ascending=False, cor_valor="#38bdf8"):
        df_work = df_rank.copy()
        if col_indicador in ['p_l', 'p_vp', 'ev_ebitda', 'div_liq_ebitda']:
            df_work = df_work[df_work[col_indicador] > 0]
        if col_indicador in ['dy_atual', 'roe', 'roic', 'margem_liquida', 'cagr_lucro_5a', 'cagr_receita_5a', 'score']:
            df_work = df_work[df_work[col_indicador].notna()]
        if df_work.empty: return

        top = df_work.nsmallest(50, col_indicador) if is_ascending else df_work.nlargest(50, col_indicador)
        st.markdown(f'<div class="st">{titulo}</div>', unsafe_allow_html=True)

        items = []
        for _, row in top.iterrows():
            ticker = row['ticker']
            nome = str(row.get('nome', ticker))[:22] + "..." if len(str(row.get('nome', ticker))) > 22 else str(row.get('nome', ticker))
            valor = fmt_func(row.get(col_indicador, 0))
            score = int(row.get('score', 0))
            setor = str(row.get('setor', 'N/A'))[:15] + "..." if len(str(row.get('setor', 'N/A'))) > 15 else str(row.get('setor', 'N/A'))
            if score >= 80: badge_bg, badge_text, badge_label = "#065f46", "#10b981", "Excelente"
            elif score >= 60: badge_bg, badge_text, badge_label = "#3f6212", "#84cc16", "Bom"
            elif score >= 40: badge_bg, badge_text, badge_label = "#92400e", "#f59e0b", "Regular"
            elif score >= 20: badge_bg, badge_text, badge_label = "#7c2d12", "#f97316", "Fraco"
            else: badge_bg, badge_text, badge_label = "#7f1d1d", "#dc2626", "Pessimo"
            sc_color = badge_text
            items.append((ticker, nome, valor, score, sc_color, setor, badge_bg, badge_text, badge_label))

        for row_idx in range(10):
            cols = st.columns(5)
            for col_idx in range(5):
                idx = row_idx * 5 + col_idx
                if idx < len(items):
                    ticker, nome, valor, score, sc_color, setor, badge_bg, badge_text, badge_label = items[idx]
                    with cols[col_idx]:
                        if st.button(f"{ticker}", key=f"nav_{ticker}_{col_indicador}_{idx}"):
                            st.session_state["pagina_atual"] = "analise"
                            st.session_state["ticker_destino"] = ticker
                            st.rerun()
                        st.markdown(f"""
                        <div class="ranking-card">
                            <div class="ranking-nome">{nome}</div>
                            <div class="ranking-valor" style="color: {cor_valor};">{valor}</div>
                            <div style="margin-top:6px;"><span style="background:{badge_bg}40; color:{badge_text}; padding: 2px 8px; border-radius: 10px; font-size: 0.65rem; font-weight: 700;">{badge_label}</span></div>
                            <div class="ranking-footer"><span style="color:{sc_color}; font-weight: 700;">CS {score}</span><span style="color:#64748b; font-weight: 500;">{setor}</span></div>
                        </div>
                        """, unsafe_allow_html=True)

    if ranking_sel == "Maior Valor de Mercado":
        render_ranking(df_filt, 'valor_mercado', 'Maior Valor de Mercado', lambda x: f"R$ {x/1e9:.2f}B" if x >= 1e9 else f"R$ {x/1e6:.2f}M", cor_valor="#fbbf24")
    elif ranking_sel == "Maiores Lucros":
        render_ranking(df_filt, 'lucro_liquido', 'Maiores Lucros', lambda x: f"R$ {x/1e9:.2f}B" if abs(x) >= 1e9 else f"R$ {x/1e6:.2f}M", cor_valor="#10b981")
    elif ranking_sel == "Maiores Receitas":
        render_ranking(df_filt, 'receita_liquida', 'Maiores Receitas', lambda x: f"R$ {x/1e9:.2f}B" if x >= 1e9 else f"R$ {x/1e6:.2f}M", cor_valor="#38bdf8")
    elif ranking_sel == "Maiores Dividend Yield":
        render_ranking(df_filt, 'dy_atual', 'Maiores Dividend Yield', lambda x: f"{x*100:.2f}%", cor_valor="#f59e0b")
    elif ranking_sel == "Menores P/L":
        render_ranking(df_filt, 'p_l', 'Menores P/L', lambda x: f"{x:.2f}x", is_ascending=True, cor_valor="#38bdf8")
    elif ranking_sel == "Maiores ROE":
        render_ranking(df_filt, 'roe', 'Maiores ROE', lambda x: f"{x*100:.2f}%", cor_valor="#10b981")
    elif ranking_sel == "Maior Upside AGF":
        df_filt['upside_agf'] = ((df_filt['agf'] - df_filt['preco_atual']) / df_filt['preco_atual']) * 100
        render_ranking(df_filt, 'upside_agf', 'Maior Upside AGF', lambda x: f"{x:+.1f}%", cor_valor="#a78bfa")
    elif ranking_sel == "Mais Baratas - Graham":
        df_filt['upside_graham'] = ((df_filt['graham'] - df_filt['preco_atual']) / df_filt['preco_atual']) * 100
        render_ranking(df_filt, 'upside_graham', 'Mais Baratas - Graham', lambda x: f"{x:+.1f}%", cor_valor="#34d399")
    elif ranking_sel == "Mais Baratas - Bazin":
        df_filt['upside_bazin'] = ((df_filt['bazin'] - df_filt['preco_atual']) / df_filt['preco_atual']) * 100
        render_ranking(df_filt, 'upside_bazin', 'Mais Baratas - Bazin', lambda x: f"{x:+.1f}%", cor_valor="#fbbf24")
    elif ranking_sel == "Menores P/VP":
        render_ranking(df_filt, 'p_vp', 'Menores P/VP', lambda x: f"{x:.2f}x", is_ascending=True, cor_valor="#38bdf8")
    elif ranking_sel == "Menor EV/EBITDA":
        render_ranking(df_filt, 'ev_ebitda', 'Menor EV/EBITDA', lambda x: f"{x:.2f}x", is_ascending=True, cor_valor="#60a5fa")
    elif ranking_sel == "Maior CAGR Lucros 5a":
        render_ranking(df_filt, 'cagr_lucro_5a', 'Maior CAGR Lucros 5a', lambda x: f"{x*100:.2f}%", cor_valor="#10b981")
    elif ranking_sel == "Maior CAGR Receitas 5a":
        render_ranking(df_filt, 'cagr_receita_5a', 'Maior CAGR Receitas 5a', lambda x: f"{x*100:.2f}%", cor_valor="#34d399")
    elif ranking_sel == "Maior Margem Liquida":
        render_ranking(df_filt, 'margem_liquida', 'Maior Margem Liquida', lambda x: f"{x*100:.2f}%", cor_valor="#a78bfa")
    elif ranking_sel == "Menor Divida Liq/EBITDA":
        render_ranking(df_filt, 'div_liq_ebitda', 'Menor Divida Liq/EBITDA', lambda x: f"{x:.2f}x", is_ascending=True, cor_valor="#f87171")
    elif ranking_sel == "Maiores Scores 3.0":
        render_ranking(df_filt, 'score', 'Maiores Scores 3.0', lambda x: f"{x:.0f}", cor_valor="#10b981")

def pagina_comparativo():
    render_header("comparativo")
    df = load_data()
    if df.empty: return

    tickers = st.multiselect("Selecione até 5 ativos", sorted(df["ticker"].tolist()), max_selections=5)
    if len(tickers) < 2:
        st.info("Selecione pelo menos 2 ativos.")
        return

    selecionados = df[df["ticker"].isin(tickers)]
    categorias = ["Rentab.", "Cresc.", "Segur.", "Divid.", "Valuat."]
    fig = go.Figure()

    for _, row in selecionados.iterrows():
        valores = [row.get('rentabilidade', 0), row.get('crescimento', 0), row.get('seguranca', 0), row.get('dividendos', 0), row.get('valuation', 0)]
        fig.add_trace(go.Scatterpolar(r=valores + [valores[0]], theta=categorias + [categorias[0]], fill='toself', name=row['ticker']))

    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 30])), showlegend=True, height=500, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

# ==========================================================
# 8. ROTEADOR PRINCIPAL
# ==========================================================
def main():
    if "pagina_atual" not in st.session_state:
        st.session_state["pagina_atual"] = "home"
    if "ticker_destino" not in st.session_state:
        st.session_state["ticker_destino"] = None

    if st.session_state.get("ticker_destino"):
        st.session_state["pagina_atual"] = "analise"
        st.session_state["ticker_destino"] = None

    # --- MENU HORIZONTAL CENTRALIZADO ---
    cols_nav = st.columns([2, 1, 1, 1, 1, 2])
    pages = [
        ("home", "🏠 Home"), 
        ("analise", "🔍 Análise"), 
        ("rankings", "🏆 Rankings"), 
        ("comparativo", "📊 Comparativo")
    ]
    for i, (key, label) in enumerate(pages):
        is_active = st.session_state["pagina_atual"] == key
        btn_type = "primary" if is_active else "secondary"
        if cols_nav[i+1].button(label, key=f"nav_{key}", use_container_width=True, type=btn_type):
            st.session_state["pagina_atual"] = key
            st.rerun()
            
    st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

    pagina = st.session_state["pagina_atual"]
    if pagina == "home": pagina_home()
    elif pagina == "analise": pagina_analise()
    elif pagina == "rankings": pagina_rankings()
    elif pagina == "comparativo": pagina_comparativo()

if __name__ == "__main__":
    main()
