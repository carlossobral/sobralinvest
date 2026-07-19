import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ==========================================================
# 1. CONFIGURAÇÃO DA PÁGINA E CONEXÃO SUPABASE
# ==========================================================
st.set_page_config(page_title="Sobral Invest", page_icon="📈", layout="wide")

# Esconde o menu default do Streamlit para parecer um app real
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
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Credenciais do Supabase não encontradas nas variáveis de ambiente.")
        st.stop()
    return create_client(url, key)

supabase = init_supabase()

# ==========================================================
# 2. BUSCAR DADOS NO BANCO (Com Cache para performance)
# ==========================================================
@st.cache_data(ttl=3600) # Atualiza a cache a cada 1 hora
def buscar_dados():
    # Busca o score mais recente
    resp_score = supabase.table("score").select("ticker, score, rentabilidade, crescimento, seguranca, dividendos, valuation, data_balanco").order("data_balanco", desc=True).limit(1000).execute()
    df_score = pd.DataFrame(resp_score.data)
    
    if df_score.empty:
        return pd.DataFrame()
        
    # Pega a data do último balanço disponível
    data_max = df_score['data_balanco'].max()
    df_score = df_score[df_score['data_balanco'] == data_max]
    
    # Busca indicadores e empresas para merge
    resp_ind = supabase.table("indicadores").select("ticker, p_l, p_vp, roe, roic, dy_atual, margem_liquida, payout").eq("data_balanco", data_max).execute()
    df_ind = pd.DataFrame(resp_ind.data)
    
    resp_emp = supabase.table("empresas").select("ticker, nome, setor").execute()
    df_emp = pd.DataFrame(resp_emp.data)
    
    # Merge final
    df = df_score.merge(df_emp, on="ticker", how="left")
    df = df.merge(df_ind, on="ticker", how="left")
    
    return df

df_principal = buscar_dados()

# ==========================================================
# 3. LAYOUT DO DASHBOARD
# ==========================================================
st.title("📈 Sobral Invest - Score 3.0")

if df_principal.empty:
    st.warning("Nenhum dado encontrado no banco.")
else:
    st.markdown(f"**Data do último balanço:** `{df_principal['data_balanco'].iloc[0]}`")

    # --- SIDEBAR COM FILTROS ---
    st.sidebar.header("🔍 Filtros de Screener")
    
    # Filtro de Setor
    setores = ["Todos"] + sorted(df_principal["setor"].dropna().unique().tolist())
    setor_sel = st.sidebar.selectbox("Setor", setores)
    
    # Filtro de Score
    score_min = st.sidebar.slider("Score Mínimo", 0, 100, 50)
    
    # Filtro de DY
    dy_min = st.sidebar.slider("DY Mínimo (%)", 0.0, 20.0, 0.0, 0.5)
    
    # Filtro de P/L
    pl_max = st.sidebar.slider("P/L Máximo", 0, 50, 20)
    
    # Aplicar Filtros
    df_filtrado = df_principal.copy()
    if setor_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["setor"] == setor_sel]
        
    df_filtrado = df_filtrado[
        (df_filtrado["score"] >= score_min) &
        (df_filtrado["dy_atual"] >= dy_min/100) &
        (df_filtrado["p_l"] <= pl_max) &
        (df_filtrado["p_l"] > 0)
    ]
    
    df_filtrado = df_filtrado.sort_values(by="score", ascending=False)
    
    # --- TABELA PRINCIPAL ---
    st.header(f"🏆 Ranking de Ações ({len(df_filtrado)} resultados)")
    
    # Formatação para exibição
    df_display = df_filtrado[['ticker', 'nome', 'setor', 'score', 'rentabilidade', 'crescimento', 'seguranca', 'dividendos', 'valuation', 'p_l', 'p_vp', 'roe', 'dy_atual', 'payout']].copy()
    
    # Converter decimais para % para facilitar a leitura visual
    df_display['roe'] = df_display['roe'] * 100
    df_display['dy_atual'] = df_display['dy_atual'] * 100
    df_display['payout'] = df_display['payout'] * 100
    
    # Renomear colunas para o padrão brasileiro
    df_display.columns = ['Ticker', 'Empresa', 'Setor', 'Score', 'Rentab.', 'Cresc.', 'Segur.', 'Divid.', 'Valuat.', 'P/L', 'P/VP', 'ROE (%)', 'DY (%)', 'Payout (%)']
    
    st.dataframe(
        df_display,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                help="Score CS 3.0",
                format="%f",
                min_value=0,
                max_value=100,
            ),
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("---")
    st.caption("Sobral Invest - Plataforma proprietária de análise fundamentalista. Dados extraídos da CVM e B3.")
