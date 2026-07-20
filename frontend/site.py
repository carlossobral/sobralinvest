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
st.set_page_config(page_title="Sobral Invest", page_icon="📊", layout="wide")

# Esconde o menu default do Streamlit
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display: none;}
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
    return create_client(url, key)

supabase = init_supabase()

# ==========================================================
# 2. CSS GLOBAL (TEMA ESCURO E CARDS)
# ==========================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
.c * { font-family: 'Inter', sans-serif; } .c { padding: 0 8px 40px 8px; }
.st { font-size: 1.05rem; font-weight: 700; color: #f1f5f9; text-transform: uppercase; letter-spacing: 0.1em; margin: 40px 0 22px 0; padding-bottom: 10px; border-bottom: 2px solid #334155; display: flex; align-items: center; gap: 10px; }
.mc { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 12px; padding: 18px 16px; transition: all 0.3s ease; box-shadow: 0 2px 4px rgba(0,0,0,0.1); height: 100%; display: flex; flex-direction: column; justify-content: space-between; min-height: 95px; }
.mc:hover { transform: translateY(-2px); box-shadow: 0 8px 12px rgba(0,0,0,0.25); border-color: #3b82f6; }
.ml { font-size: 0.72rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; line-height: 1.3; }
.mv { font-size: 1.45rem; font-weight: 700; color: #f1f5f9; line-height: 1.1; letter-spacing: -0.02em; }
.sc { border-radius: 16px; padding: 24px; text-align: center; box-shadow: 0 10px 15px rgba(0,0,0,0.2); }
.sn { font-size: 3.5rem; font-weight: 800; line-height: 1; margin-bottom: 8px; }
.sl { font-size: 1.1rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; }
.sd { font-size: 0.8rem; color: #94a3b8; margin-top: 6px; }
.tt { position: relative; display: inline-block; }
.tt-i { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 50%; background: #475569; color: #f1f5f9; font-size: 11px; font-weight: 700; cursor: help; margin-left: 6px; }
.tt-t { visibility: hidden; width: 280px; background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #475569; color: #e2e8f0; text-align: left; border-radius: 10px; padding: 12px 14px; position: absolute; z-index: 1000; bottom: 125%; left: 50%; margin-left: -140px; opacity: 0; transition: opacity 0.3s; font-size: 0.8rem; line-height: 1.4; box-shadow: 0 10px 15px rgba(0,0,0,0.3); }
.tt:hover .tt-t { visibility: visible; opacity: 1; }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 3. FUNÇÕES DE DADOS
# ==========================================================
@st.cache_data(ttl=3600)
def load_data():
    # Busca Score
    resp_score = supabase.table("score").select("ticker, score, rentabilidade, crescimento, seguranca, dividendos, valuation, data_balanco").order("data_balanco", desc=True).limit(1000).execute()
    df_score = pd.DataFrame(resp_score.data)
    if df_score.empty: return pd.DataFrame()
    
    data_max = df_score['data_balanco'].max()
    df_score = df_score[df_score['data_balanco'] == data_max]
    
    # Busca Indicadores
    resp_ind = supabase.table("indicadores").select("*").eq("data_balanco", data_max).execute()
    df_ind = pd.DataFrame(resp_ind.data)
    
    # Busca Empresas
    resp_emp = supabase.table("empresas").select("ticker, nome, setor, subsetor, segmento").execute()
    df_emp = pd.DataFrame(resp_emp.data)
    
    df = df_score.merge(df_emp, on="ticker", how="left")
    df = df.merge(df_ind, on="ticker", how="left")
    return df

def get_ativo_detalhado(ticker):
    # Busca dados da empresa
    emp = supabase.table("empresas").select("*").eq("ticker", ticker).execute().data
    if not emp: return None
    emp = emp[0]
    
    # Busca último score
    sc = supabase.table("score").select("*").eq("ticker", ticker).order("data_balanco", desc=True).limit(1).execute().data
    if sc: emp.update(sc[0])
        
    # Busca último indicador
    ind = supabase.table("indicadores").select("*").eq("ticker", ticker).order("data_balanco", desc=True).limit(1).execute().data
    if ind: emp.update(ind[0])
        
    # Busca última cotação
    cot = supabase.table("cotacoes").select("fechamento, data").eq("ticker", ticker).order("data", desc=True).limit(1).execute().data
    if cot:
        emp["preco_atual"] = cot[0]["fechamento"]
        emp["data_cotacao"] = cot[0]["data"]
    else:
        emp["preco_atual"] = 0
        
    return emp

# ==========================================================
# 4. PÁGINAS
# ==========================================================
def pagina_home():
    st.markdown('<h1 style="color:#f1f5f9;">🏠 Dashboard & Mercado</h1>', unsafe_allow_html=True)
    st.markdown("Bem-vindo ao Sobral Invest 3.0. Use o menu lateral para navegar.")
    
    # Widget TradingView Ibovespa
    st.markdown("### 📈 Ibovespa")
    components.html("""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>{"symbols": [["BMFBOVESPA:IBOV|1D"]], "chartOnly": false, "width": "100%", "height": "400", "locale": "br", "colorTheme": "dark", "autosize": false, "showVolume": true}</script></div>""", height=420)

def pagina_analise():
    st.markdown('<h1 style="color:#f1f5f9;">🔍 Análise Fundamentalista</h1>', unsafe_allow_html=True)
    
    df = load_data()
    if df.empty:
        st.warning("Dados não disponíveis.")
        return
        
    df['Disp'] = (df['ticker'].astype(str).fillna('') + ' - ' + df['nome'].astype(str).fillna('')).astype(str)
    opts = sorted(df['Disp'].tolist())
    
    sel = st.selectbox("Selecione o ativo", options=opts)
    ticker = sel.split(' - ')[0]
    
    ativo = get_ativo_detalhado(ticker)
    if not ativo: return

    # Cabeçalho Setor
    st.markdown(f"""
    <div style="display: flex; gap: 24px; margin: 8px 0 16px 0;">
        <div><span style="font-size: 0.7rem; font-weight: 600; color: #94a3b8;">Setor</span><span style="font-size: 0.85rem; color: #f1f5f9; margin-left: 8px;">{ativo.get('setor', 'N/A')}</span></div>
        <div><span style="font-size: 0.7rem; font-weight: 600; color: #94a3b8;">Segmento</span><span style="font-size: 0.85rem; color: #f1f5f9; margin-left: 8px;">{ativo.get('segmento', 'N/A')}</span></div>
    </div>
    """, unsafe_allow_html=True)

    # Gráfico TradingView
    components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>{{"symbols": [["BMFBOVESPA:{ticker}|1D"]], "chartOnly": false, "width": "100%", "height": "350", "locale": "br", "colorTheme": "dark"}}</script></div>""", height=360)

    def safe(v, d=0.0):
        try: return float(v) if v is not None else d
        except: return d

    def sec(title, data, cols):
        st.markdown(f'<div class="st">{title}</div>', unsafe_allow_html=True)
        for r in range(2 if len(data) > cols else 1):
            cs = st.columns(cols)
            for c in range(cols):
                i = r * cols + c
                if i < len(data):
                    lbl, val = data[i]
                    cs[c].markdown(f"""<div class="mc"><div class="ml">{lbl}</div><div class="mv">{val}</div></div>""", unsafe_allow_html=True)

    # Cards de Indicadores
    sec("Valuation", [
        ("P/L", f"{safe(ativo.get('p_l')):.2f}x"), 
        ("P/VP", f"{safe(ativo.get('p_vp')):.2f}x"), 
        ("LPA", f"R$ {safe(ativo.get('lpa')):.2f}"), 
        ("P/Receita", f"{safe(ativo.get('p_receita')):.2f}x"), 
        ("P/Ativo", f"{safe(ativo.get('p_ativo')):.2f}x"), 
        ("EV/EBITDA", f"{safe(ativo.get('ev_ebitda')):.2f}x")
    ], 6)
    
    sec("Rentabilidade", [
        ("ROE", f"{safe(ativo.get('roe'))*100:.2f}%"), 
        ("ROA", f"{safe(ativo.get('roa'))*100:.2f}%"), 
        ("ROIC", f"{safe(ativo.get('roic'))*100:.2f}%"), 
        ("Margem Bruta", f"{safe(ativo.get('margem_bruta'))*100:.2f}%"), 
        ("Margem EBITDA", f"{safe(ativo.get('margem_ebitda'))*100:.2f}%"), 
        ("Margem Líquida", f"{safe(ativo.get('margem_liquida'))*100:.2f}%")
    ], 6)
    
    sec("Endividamento", [
        ("Dív. Líq/Ativos", f"{safe(ativo.get('div_liq_ativos')):.2f}x"), 
        ("Dív. Líq/PL", f"{safe(ativo.get('div_liq_pl')):.2f}x"), 
        ("Dív. Líq/EBIT", f"{safe(ativo.get('div_liq_ebit')):.2f}x"), 
        ("Dív. Líq/EBITDA", f"{safe(ativo.get('div_liq_ebitda')):.2f}x"), 
        ("Liq. Corrente", f"{safe(ativo.get('liquidez_corrente')):.2f}x"), 
        ("Cobertura Juros", f"{safe(ativo.get('cobertura_juros')):.2f}x")
    ], 6)

    # Preço Teto / Justo
    st.markdown('<div class="st">Preço Teto | Preço Justo</div>', unsafe_allow_html=True)
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
        cps[i].markdown(f"""<div class="mc" style="text-align: center;"><div class="ml">{t}</div><div class="mv">{price_str}</div><div style="color:{c}; font-weight:700;">{ups:+.1f}%</div></div>""", unsafe_allow_html=True)

    # Score 3.0
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

def pagina_rankings():
    st.markdown('<h1 style="color:#f1f5f9;">🏆 Rankings</h1>', unsafe_allow_html=True)
    df = load_data()
    if df.empty: return

    col1, col2 = st.columns([3, 1])
    with col1:
        ranking_sel = st.selectbox("Ranking", ["Maiores Scores", "Maiores ROE", "Maiores DY", "Menores P/L", "Maiores Crescimento"], key="rank_select")
    with col2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.markdown(f'<p style="color:#94a3b8; font-size:0.85rem;">{len(df)} ativos</p>', unsafe_allow_html=True)

    if ranking_sel == "Maiores Scores":
        top = df.nlargest(50, 'score')
        val_col = 'score'
        fmt = lambda x: f"{x:.0f}"
    elif ranking_sel == "Maiores ROE":
        top = df.nlargest(50, 'roe')
        val_col = 'roe'
        fmt = lambda x: f"{x*100:.2f}%"
    elif ranking_sel == "Maiores DY":
        top = df.nlargest(50, 'dy_atual')
        val_col = 'dy_atual'
        fmt = lambda x: f"{x*100:.2f}%"
    elif ranking_sel == "Menores P/L":
        top = df[df['p_l'] > 0].nsmallest(50, 'p_l')
        val_col = 'p_l'
        fmt = lambda x: f"{x:.2f}x"
    else:
        top = df.nlargest(50, 'crescimento')
        val_col = 'crescimento'
        fmt = lambda x: f"{x:.1f}"

    cols = st.columns(5)
    for i, (_, row) in enumerate(top.iterrows()):
        with cols[i % 5]:
            st.markdown(f"""
            <div style="background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 10px; margin-bottom: 10px; text-align: center;">
                <div style="font-weight: 700; color: #38bdf8;">{row['ticker']}</div>
                <div style="font-size: 1.2rem; font-weight: 700; color: #f1f5f9; margin: 5px 0;">{fmt(row[val_col])}</div>
                <div style="font-size: 0.7rem; color: #94a3b8;">Score: {row['score']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)

def pagina_comparativo():
    st.markdown('<h1 style="color:#f1f5f9;">📊 Comparativo</h1>', unsafe_allow_html=True)
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
# 5. ROTEADOR PRINCIPAL
# ==========================================================
def main():
    if "pagina_atual" not in st.session_state:
        st.session_state["pagina_atual"] = "home"

    # Header
    st.markdown("""
    <style>
    .header-container { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }
    .header-brand-name { font-size: 1.4rem; font-weight: 800; color: #f1f5f9; }
    </style>
    <div class="header-container">
        <div class="header-brand-name">SOBRAL Invest</div>
        <div style="color: #38bdf8;">v3.0</div>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar
    with st.sidebar:
        st.markdown("<div style='font-size: 1.1rem; font-weight: 700; color: #f1f5f9; margin-bottom: 12px;'>Navegação</div>", unsafe_allow_html=True)
        pages = [("home", "🏠 Home"), ("analise", "🔍 Análise"), ("rankings", "🏆 Rankings"), ("comparativo", "📊 Comparativo")]
        for key, label in pages:
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state["pagina_atual"] = key
                st.rerun()

    # Roteamento
    pagina = st.session_state["pagina_atual"]
    if pagina == "home": pagina_home()
    elif pagina == "analise": pagina_analise()
    elif pagina == "rankings": pagina_rankings()
    elif pagina == "comparativo": pagina_comparativo()

if __name__ == "__main__":
    main()
