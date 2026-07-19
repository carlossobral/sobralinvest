"""
ETL - Sobral Score 3.0

Calcula o Score CS para todas as empresas.

Fluxo:
indicadores + empresas + metricas_score + dividendos = score
Regras:
- Dividendos: Histórico (8) + DY Atual (6) + Payout (6).
- Rentabilidade: Inversão ROIC(10)/ROE(7). Penalidade por diferença (Alavancagem). Fator 0.8 se Marg. Liq > Marg. EBIT.
- Segurança: DL/EBITDA + Cobertura de Juros + Liquidez. Zera se DL > 4x ou Cobertura < 2x.
- Bancos/Seguradoras: Segurança = 0. Pesos redistribuídos.
- Se setor < 3 empresas, usa mediana do mercado geral.
- Se anos_listagem for NULL, usa a quantidade de anos de balanço no banco (Proxy).
"""

import pandas as pd
import numpy as np
from datetime import datetime
from etl.database.supabase_client import supabase

# ==========================================================
# 1. BUSCAR DATA_CÁLCULO E CARREGAR DADOS
# ==========================================================
print("Buscando data do último cálculo...")
resp = (
    supabase.table("indicadores")
    .select("data_calculo")
    .order("data_calculo", desc=True)
    .limit(1)
    .execute()
)

if not resp.data:
    raise Exception("Nenhum cálculo encontrado.")

data_calculo = resp.data[0]["data_calculo"]
print(f"Data encontrada: {data_calculo}")

print("Carregando empresas...")
dados_emp = []
offset = 0
while True:
    chunk = supabase.table("empresas").select("ticker, setor, segmento, anos_listagem").range(offset, offset + 999).execute().data
    dados_emp.extend(chunk)
    if len(chunk) < 1000: break
    offset += 1000
empresas_df = pd.DataFrame(dados_emp)

print("Carregando indicadores...")
dados_ind = []
offset = 0
while True:
    chunk = supabase.table("indicadores").select("*").eq("data_calculo", data_calculo).range(offset, offset + 999).execute().data
    dados_ind.extend(chunk)
    if len(chunk) < 1000: break
    offset += 1000
indicadores_df = pd.DataFrame(dados_ind)

print("Carregando métricas setoriais...")
metricas_df = pd.DataFrame(supabase.table("metricas_score").select("*").execute().data)

print("Carregando dividendos...")
dados_div = []
offset = 0
while True:
    chunk = supabase.table("dividendos").select("ticker, data_pagamento, valor").range(offset, offset + 999).execute().data
    dados_div.extend(chunk)
    if len(chunk) < 1000: break
    offset += 1000
dividendos_df = pd.DataFrame(dados_div)

# ==========================================================
# 2. HISTÓRICOS (ROE E DIVIDENDOS)
# ==========================================================
print("Calculando histórico do ROE (5 anos completos)...")
hist_roe_resp = []
offset = 0
while True:
    chunk = supabase.table("indicadores").select("ticker, ano, roe").range(offset, offset + 999).execute().data
    hist_roe_resp.extend(chunk)
    if len(chunk) < 1000: break
    offset += 1000

hist_roe_df = pd.DataFrame(hist_roe_resp)
ano_atual = datetime.now().year
anos_disponiveis = [a for a in sorted(hist_roe_df["ano"].unique(), reverse=True) if a < ano_atual][:5]
hist_roe_df = hist_roe_df[hist_roe_df['ano'].isin(anos_disponiveis)]

hist_roe_df['roe_10'] = hist_roe_df['roe'] >= 0.10
consistencia_roe = hist_roe_df.groupby('ticker')['roe_10'].sum().reset_index()
consistencia_roe.columns = ['ticker', 'anos_roe_10']

proxy_listagem = hist_roe_df.groupby('ticker')['ano'].nunique().reset_index()
proxy_listagem.columns = ['ticker', 'anos_hist_banco']

print("Calculando histórico de dividendos (6 anos completos)...")
if not dividendos_df.empty:
    dividendos_df['data_pagamento'] = pd.to_datetime(dividendos_df['data_pagamento'])
    dividendos_df['valor'] = pd.to_numeric(dividendos_df['valor'], errors="coerce").fillna(0)
    dividendos_df['ano'] = dividendos_df['data_pagamento'].dt.year
    
    ano_limite = ano_atual - 6
    div_6a = dividendos_df[(dividendos_df["ano"] >= ano_limite) & (dividendos_df["ano"] < ano_atual)]
    div_anual = div_6a.groupby(['ticker', 'ano'])['valor'].sum().reset_index()
    div_anual['pagou'] = div_anual['valor'] > 0
    hist_div = div_anual.groupby('ticker')['pagou'].sum().reset_index()
    hist_div.columns = ['ticker', 'anos_div_pagos']
else:
    hist_div = pd.DataFrame(columns=['ticker', 'anos_div_pagos'])

# ==========================================================
# 3. MERGE E MEDIANA DE MERCADO
# ==========================================================
print("Unindo bases e calculando medianas de mercado...")
df = indicadores_df.merge(empresas_df, on="ticker", how="left")
df = df.merge(metricas_df, on=["setor", "data_balanco"], how="left")
df = df.merge(consistencia_roe, on="ticker", how="left")
df = df.merge(hist_div, on="ticker", how="left")
df = df.merge(proxy_listagem, on="ticker", how="left")

df['anos_roe_10'] = df['anos_roe_10'].fillna(0).astype(int)
df['anos_div_pagos'] = df['anos_div_pagos'].fillna(0).astype(int)
df['anos_hist_banco'] = df['anos_hist_banco'].fillna(0).astype(int)

def med_pos(serie):
    s = pd.to_numeric(serie, errors='coerce').dropna()
    s = s[s > 0]
    return s.median() if not s.empty else None

mkt_medians = df.groupby('data_balanco').agg(
    pl_mkt=('p_l', med_pos), pvp_mkt=('p_vp', med_pos), ev_ebit_mkt=('ev_ebit', med_pos),
    roe_mkt=('roe', med_pos), roic_mkt=('roic', med_pos)
).reset_index()

df = df.merge(mkt_medians, on='data_balanco', how='left')

# ==========================================================
# 4. FUNÇÕES SCORE 3.0 E FILTROS
# ==========================================================

# --- RENTABILIDADE (25 base) ---
def score_roic(val):
    if pd.isna(val): return 0
    if val >= 20: return 10
    if val >= 15: return 8
    if val >= 10: return 6
    if val >= 5: return 3
    return 0

def score_roe(val):
    if pd.isna(val): return 0
    if val >= 25: return 7
    if val >= 20: return 5
    if val >= 15: return 4
    if val >= 10: return 2
    return 0

def score_margem(val):
    if pd.isna(val): return 0
    if val >= 20: return 5
    if val >= 15: return 4
    if val >= 10: return 2
    if val >= 5: return 1
    return 0

def score_consistencia_roe(anos):
    if anos >= 5: return 3
    if anos == 4: return 2
    if anos == 3: return 1
    return 0

# --- CRESCIMENTO (25 base) ---
def score_cagr_receita(val):
    if pd.isna(val): return 0
    if val >= 20: return 12
    if val >= 15: return 10
    if val >= 10: return 7
    if val >= 5: return 4
    if val >= 0: return 2
    return 0

def score_cagr_lucro(val):
    if pd.isna(val): return 0
    if val >= 20: return 13
    if val >= 15: return 10
    if val >= 10: return 7
    if val >= 5: return 4
    if val >= 0: return 2
    return 0

# --- SEGURANÇA (20 base) ---
def score_divida(val):
    if pd.isna(val): return 0
    if val <= 1: return 10
    if val <= 2: return 8
    if val <= 3: return 5
    if val <= 4: return 2
    return 0

def score_liquidez(val):
    if pd.isna(val): return 0
    if val >= 2.0: return 5
    if val >= 1.5: return 4
    if val >= 1.2: return 3
    if val >= 1.0: return 2
    if val >= 0.5: return 1
    return 0

def score_cobertura_juros(val):
    if pd.isna(val): return 0
    if val >= 5.0: return 5
    if val >= 3.0: return 4
    if val >= 2.0: return 2
    return 0

# --- DIVIDENDOS (20 base) ---
def score_hist_div(anos):
    if anos >= 6: return 8
    if anos == 5: return 6
    if anos == 4: return 4
    if anos == 3: return 2
    return 0

def score_dy_atual(val):
    if pd.isna(val): return 0
    if val >= 8: return 6
    if val >= 6: return 5
    if val >= 4: return 4
    if val >= 3: return 3
    if val >= 2: return 2
    return 0

def score_payout(val):
    if pd.isna(val): return 0
    if val > 1.0: return 0        # > 100%
    if val < 0.2: return 0        # < 20%
    if val > 0.9: return 2        # > 90% e <= 100%
    if val >= 0.75: return 4      # 75% a 90%
    if val < 0.30: return 4       # 20% a 30%
    return 6                      # 30% a 75% (Ideal)

# --- VALUATION (10 base) ---
def score_pl_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 3 if val < med else 0

def score_pvp_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 3 if val < med else 0

def score_ev_ebit_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 4 if val < med else 0 # Ajustado para totalizar 10

def eh_financeiro(segmento, ticker):
    if pd.isna(segmento): return False
    seg = str(segmento).strip()
    tk = str(ticker).strip().upper()
    is_banco = seg == "Bancos" and tk not in ['ITSA3', 'ITSA4']
    is_seguradora = seg == "Seguradoras" or tk in ['WIZC3', 'CXSE3', 'BBSE3']
    return is_banco or is_seguradora

def bonus_listagem(anos_listagem, anos_hist_banco):
    if not pd.isna(anos_listagem) and float(anos_listagem) >= 5:
        return 1
    elif pd.isna(anos_listagem) and anos_hist_banco >= 5:
        return 1
    return 0

# ==========================================================
# 5. CALCULAR SCORE 3.0
# ==========================================================
print("Calculando Score CS 3.0...")

resultados = []

for _, row in df.iterrows():
    is_banco = eh_financeiro(row.get("segmento"), row.get("ticker"))
    
    roe_val = row["roe"] * 100 if pd.notna(row["roe"]) else None
    roic_val = row["roic"] * 100 if pd.notna(row["roic"]) else None
    margem_liq_val = row["margem_liquida"] * 100 if pd.notna(row["margem_liquida"]) else None
    margem_ebit_val = row["margem_ebit"] * 100 if pd.notna(row["margem_ebit"]) else None
    cagr_rec_val = row["cagr_receita_5a"] * 100 if pd.notna(row["cagr_receita_5a"]) else None
    cagr_luc_val = row["cagr_lucro_5a"] * 100 if pd.notna(row["cagr_lucro_5a"]) else None
    dy_atual_val = row["dy_atual"] * 100 if pd.notna(row["dy_atual"]) else None
    
    # 1. RENTABILIDADE (25 base)
    rentabilidade = (
        score_roic(roic_val) + score_roe(roe_val) +
        score_margem(margem_liq_val) + score_consistencia_roe(row["anos_roe_10"])
    )
    
    # Penalidade Alavancagem (Diferença ROE - ROIC)
    if pd.notna(roe_val) and pd.notna(roic_val):
        diff_roe_roic = roe_val - roic_val
        if diff_roe_roic > 15:
            rentabilidade *= 0.70
        elif diff_roe_roic > 5:
            rentabilidade *= 0.85
            
    # Fator Lucro Sujo (Margem Líquida > Margem EBIT)
    if pd.notna(margem_liq_val) and pd.notna(margem_ebit_val) and margem_liq_val > margem_ebit_val:
        rentabilidade *= 0.80
    
    rentabilidade = round(rentabilidade, 2)
    
    # 2. CRESCIMENTO (25 base)
    crescimento = score_cagr_receita(cagr_rec_val) + score_cagr_lucro(cagr_luc_val)
    
    # 3. SEGURANÇA (20 base / 0 para financeiros)
    if is_banco:
        seguranca = 0
    else:
        div_ebitda = row.get("div_liq_ebitda")
        cob_juros = row.get("cobertura_juros")
        
        if (pd.notna(div_ebitda) and div_ebitda > 4) or (pd.notna(cob_juros) and cob_juros < 2):
            seguranca = 0
        else:
            seguranca = score_divida(div_ebitda) + score_liquidez(row["liquidez_corrente"]) + score_cobertura_juros(cob_juros)
        
    # 4. DIVIDENDOS (20 base)
    dividendos = score_hist_div(row["anos_div_pagos"]) + score_dy_atual(dy_atual_val) + score_payout(row.get("payout"))
    
    # 5. VALUATION (10 base) E BÔNUS ROE/ROIC
    n_emp_setor = row.get("empresas_setor")
    if pd.isna(n_emp_setor) or n_emp_setor < 3:
        pl_med, pvp_med, ev_ebit_med = row.get("pl_mkt"), row.get("pvp_mkt"), row.get("ev_ebit_mkt")
        roe_med, roic_med = row.get("roe_mkt"), row.get("roic_mkt")
    else:
        pl_med, pvp_med, ev_ebit_med = row.get("pl_mediano"), row.get("pvp_mediano"), row.get("ev_ebit_mediano")
        roe_med, roic_med = row.get("roe_mediano"), row.get("roic_mediano")

    valuation = (
        score_pl_rel(row["p_l"], pl_med) + score_pvp_rel(row["p_vp"], pvp_med) +
        score_ev_ebit_rel(row["ev_ebit"], ev_ebit_med)
    )
    
    bonus_roe = 0
    bonus_roe += (1 if not pd.isna(row["roe"]) and not pd.isna(roe_med) and row["roe"] > roe_med else 0)
    bonus_roe += (1 if not pd.isna(row["roic"]) and not pd.isna(roic_med) and row["roic"] > roic_med else 0)
    
    # REDISTRIBUIÇÃO DOS PESOS (Apenas Financeiros)
    if is_banco:
        rentabilidade = round(rentabilidade * (31 / 25), 2)
        crescimento = round(crescimento * (31 / 25), 2)
        dividendos = round(dividendos * (25 / 20), 2)
        valuation = round(valuation * (13 / 10), 2)
    
    b_listagem = bonus_listagem(row.get("anos_listagem"), row.get("anos_hist_banco"))
    
    # TOTAL
    score_cs = rentabilidade + crescimento + seguranca + dividendos + valuation + bonus_roe + b_listagem
    score_cs = min(103, max(0, score_cs))
    
    def clean_val(v):
        if pd.isna(v): return None
        return float(v)
    
    resultados.append({
        "ticker": row["ticker"],
        "data_balanco": row.get("data_balanco"),
        "score": clean_val(score_cs),
        "rentabilidade": clean_val(rentabilidade),
        "crescimento": clean_val(crescimento),
        "seguranca": clean_val(seguranca),
        "dividendos": clean_val(dividendos),
        "valuation": clean_val(valuation),
        "bonus_roe": int(bonus_roe),
        "bonus_listagem": int(b_listagem)
    })

resultado_df = pd.DataFrame(resultados)

# ==========================================================
# 6. SALVAR NA TABELA SCORE
# ==========================================================
print(f"Atualizando tabela 'score' para {len(resultado_df)} registros...")

lote = 500
erros = 0
salvos = 0

for i in range(0, len(resultado_df), lote):
    lote_atual = resultado_df.iloc[i: i + lote].to_dict(orient="records")
    try:
        supabase.table("score").upsert(
            lote_atual,
            on_conflict="ticker,data_balanco"
        ).execute()
        salvos += len(lote_atual)
    except Exception as e:
        erros += 1
        print(f"  Erro no lote {i}: {e}")

print(f"✅ Score CS 3.0 atualizado com sucesso. {salvos} registros processados, {erros} lotes com erro.")
