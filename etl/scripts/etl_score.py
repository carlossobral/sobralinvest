"""
ETL - Score CS 2.0

Calcula o Score CS para todas as empresas.

Fluxo:
indicadores + empresas + metricas_score + dividendos = score_cs
"""

import pandas as pd
import numpy as np
from datetime import datetime
from etl.database.supabase_client import supabase

# ==========================================================
# 1. IMPORTS
# ==========================================================

# ==========================================================
# 2. BUSCAR DATA_CÁLCULO
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

# ==========================================================
# 3. CARREGAR EMPRESAS
# ==========================================================
print("Carregando empresas...")
dados_emp = []
offset = 0
while True:
    chunk = (
        supabase.table("empresas")
        .select("ticker, setor, segmento, anos_listagem")
        .range(offset, offset + 999)
        .execute()
        .data
    )
    dados_emp.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

empresas_df = pd.DataFrame(dados_emp)
print(f"{len(empresas_df)} empresas carregadas.")

# ==========================================================
# 4. CARREGAR INDICADORES
# ==========================================================
print("Carregando indicadores...")
dados_ind = []
offset = 0
while True:
    chunk = (
        supabase.table("indicadores")
        .select("*")
        .eq("data_calculo", data_calculo)
        .range(offset, offset + 999)
        .execute()
        .data
    )
    dados_ind.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

indicadores_df = pd.DataFrame(dados_ind)
print(f"{len(indicadores_df)} indicadores carregados.")

# ==========================================================
# 5. CARREGAR MÉTRICAS_SCORE
# ==========================================================
print("Carregando métricas setoriais...")
metricas_df = pd.DataFrame(
    supabase.table("metricas_score").select("*").execute().data
)
print(f"{len(metricas_df)} setores carregados.")

# ==========================================================
# 6. CARREGAR DIVIDENDOS
# ==========================================================
print("Carregando dividendos...")
dados_div = []
offset = 0
while True:
    chunk = (
        supabase.table("dividendos")
        .select("ticker, data_pagamento, valor")
        .range(offset, offset + 999)
        .execute()
        .data
    )
    dados_div.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

dividendos_df = pd.DataFrame(dados_div)
print(f"{len(dividendos_df)} eventos de dividendos carregados.")

# ==========================================================
# 7. CALCULAR HISTÓRICO ROE (VETORIZADO)
# ==========================================================
print("Calculando histórico do ROE (5 anos completos)...")

hist_roe_resp = []
offset = 0
while True:
    chunk = (
        supabase.table("indicadores")
        .select("ticker, ano, roe")
        .range(offset, offset + 999)
        .execute()
        .data
    )
    hist_roe_resp.extend(chunk)
    if len(chunk) < 1000:
        break
    offset += 1000

hist_roe_df = pd.DataFrame(hist_roe_resp)

# Regra: Excluir ano parcial (corrente) e pegar 5 anos completos
ano_max = hist_roe_df["ano"].max()
anos_disponiveis = [
    a for a in sorted(hist_roe_df["ano"].unique(), reverse=True)
    if a < ano_max
][:5]

hist_roe_df = hist_roe_df[hist_roe_df['ano'].isin(anos_disponiveis)]
hist_roe_df['roe_10'] = hist_roe_df['roe'] >= 10
consistencia_roe = hist_roe_df.groupby('ticker')['roe_10'].sum().reset_index()
consistencia_roe.columns = ['ticker', 'anos_roe_10']

print("Histórico ROE processado.")

# ==========================================================
# 8. CALCULAR HISTÓRICO DIVIDENDOS (VETORIZADO)
# ==========================================================
print("Calculando histórico de dividendos (6 anos completos)...")

if not dividendos_df.empty:
    dividendos_df['data_pagamento'] = pd.to_datetime(dividendos_df['data_pagamento'])
    dividendos_df['valor'] = pd.to_numeric(dividendos_df['valor'], errors='coerce').fillna(0)
    dividendos_df['ano'] = dividendos_df['data_pagamento'].dt.year
    
    # Regra: Garantir 6 anos COMPLETOS, excluindo o ano parcial corrente
    ano_atual = datetime.now().year
    ano_limite = ano_atual - 6
    
    div_6a = dividendos_df[
        (dividendos_df["ano"] >= ano_limite) & 
        (dividendos_df["ano"] < ano_atual)
    ]
    
    div_anual = div_6a.groupby(['ticker', 'ano'])['valor'].sum().reset_index()
    div_anual['pagou'] = div_anual['valor'] > 0
    hist_div = div_anual.groupby('ticker')['pagou'].sum().reset_index()
    hist_div.columns = ['ticker', 'anos_div_pagos']
else:
    hist_div = pd.DataFrame(columns=['ticker', 'anos_div_pagos'])

print("Histórico de dividendos processado.")

# ==========================================================
# 9. MERGE
# ==========================================================
print("Unindo bases...")

df = indicadores_df.merge(empresas_df, on="ticker", how="left")
df = df.merge(metricas_df, on="setor", how="left")
df = df.merge(consistencia_roe, on="ticker", how="left")
df = df.merge(hist_div, on="ticker", how="left")

df['anos_roe_10'] = df['anos_roe_10'].fillna(0).astype(int)
df['anos_div_pagos'] = df['anos_div_pagos'].fillna(0).astype(int)

print(f"{len(df)} empresas prontas para cálculo.")

# ==========================================================
# 10. FUNÇÕES SCORE
# ==========================================================

# --- RENTABILIDADE (25) ---
def score_roe(val):
    if pd.isna(val): return 0
    if val >= 25: return 10
    if val >= 20: return 8
    if val >= 15: return 6
    if val >= 10: return 4
    if val >= 5: return 2
    return 0

def score_roic(val):
    if pd.isna(val): return 0
    if val >= 20: return 7
    if val >= 15: return 5
    if val >= 10: return 3
    if val >= 5: return 1
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

# --- CRESCIMENTO (25) ---
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

# --- SEGURANÇA (20 - Apenas Normais) ---
def score_divida(val):
    if pd.isna(val): return 0
    if val <= 0: return 15
    if val <= 1: return 13
    if val <= 2: return 10
    if val <= 3: return 6
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

# --- DIVIDENDOS (20) ---
def score_hist_div(anos):
    if anos >= 6: return 8
    if anos == 5: return 6
    if anos == 4: return 4
    if anos == 3: return 2
    return 0

def score_dy_atual(val):
    if pd.isna(val): return 0
    if val >= 8: return 5
    if val >= 6: return 4
    if val >= 4: return 3
    if val >= 2: return 2
    return 0

def score_dy_medio(val):
    if pd.isna(val): return 0
    if val >= 8: return 7
    if val >= 6: return 6
    if val >= 5: return 5
    if val >= 4: return 3
    if val >= 2: return 1
    return 0

# --- VALUATION (10 + Bônus) ---
def score_pl_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 3 if val < med else 0

def score_pvp_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 3 if val < med else 0

def score_ev_ebit_rel(val, med):
    if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0: return 0
    return 2 if val < med else 0

# --- DETECÇÃO BANCOS E SEGURADORAS (REGRA FINAL) ---
def eh_financeiro(segmento, ticker):
    if pd.isna(segmento): 
        return False
    
    seg = str(segmento).strip()
    tk = str(ticker).strip().upper()
    
    # Regra Banco: É banco, mas não é a Itaúsa (Holdings)
    is_banco = seg == "Bancos" and tk not in ['ITSA3', 'ITSA4']
    
    # Regra Seguradora: É seguradora OU está na lista de tickers específicos
    is_seguradora = seg == "Seguradoras" or tk in ['WIZC3', 'CXSE3', 'BBSE3']
    
    return is_banco or is_seguradora

# --- BÔNUS LISTAGEM ---
def bonus_listagem(anos):
    if pd.isna(anos):
        return 0
    try:
        return 1 if float(anos) >= 5 else 0
    except (ValueError, TypeError):
        return 0

# ==========================================================
# 11. CALCULAR SCORE
# ==========================================================
print("Calculando Score CS...")

resultados = []

for _, row in df.iterrows():
    is_banco = eh_financeiro(row.get("segmento"), row.get("ticker"))
    
    # 1. RENTABILIDADE (25 base)
    rentabilidade = (
        score_roe(row["roe"]) +
        score_roic(row["roic"]) +
        score_margem(row["margem_liquida"]) +
        score_consistencia_roe(row["anos_roe_10"])
    )
    
    # 2. CRESCIMENTO (25 base)
    crescimento = (
        score_cagr_receita(row["cagr_receita_5a"]) + 
        score_cagr_lucro(row["cagr_lucro_5a"])
    )
    
    # 3. SEGURANÇA (20 base / 0 para financeiros)
    if is_banco:
        seguranca = 0
    else:
        seguranca = score_divida(row["div_liq_ebitda"]) + score_liquidez(row["liquidez_corrente"])
        
    # 4. DIVIDENDOS (20 base)
    dividendos = (
        score_hist_div(row["anos_div_pagos"]) + 
        score_dy_atual(row["dy_atual"]) + 
        score_dy_medio(row["dividendos_6a_media"])
    )
    
    # 5. VALUATION (10 base + Bônus ROE/ROIC)
    valuation = (
        score_pl_rel(row["p_l"], row.get("pl_mediano")) +
        score_pvp_rel(row["p_vp"], row.get("pvp_mediano")) +
        score_ev_ebit_rel(row["ev_ebit"], row.get("ev_ebit_mediano")) +
        (1 if not pd.isna(row["roe"]) and not pd.isna(row.get("roe_mediano")) and row["roe"] > row.get("roe_mediano") else 0) +
        (1 if not pd.isna(row["roic"]) and not pd.isna(row.get("roic_mediano")) and row["roic"] > row.get("roic_mediano") else 0)
    )
    
    # REDISTRIBUIÇÃO DOS PESOS (Apenas Financeiros)
    if is_banco:
        rentabilidade = round(rentabilidade * (31 / 25), 2)
        crescimento = round(crescimento * (31 / 25), 2)
        dividendos = round(dividendos * (25 / 20), 2)
        valuation = round(valuation * (13 / 10), 2)
    
    # TOTAL (+ Bônus Listagem)
    score_cs = (
        rentabilidade
        + crescimento
        + seguranca
        + dividendos
        + valuation
        + bonus_listagem(row.get("anos_listagem"))
    )
    
    # Limite máximo 103
    score_cs = min(103, max(0, score_cs))
    
    resultados.append({
        "ticker": row["ticker"],
        "score_cs": round(score_cs, 2)
    })

resultado_df = pd.DataFrame(resultados)

# ==========================================================
# 12. ATUALIZAR SCORE_CS (VERSÃO OTIMIZADA BATCH UPSERT)
# ==========================================================
print(f"Atualizando Score CS para {len(resultado_df)} empresas (Batch Upsert)...")

# Prepara o payload com as chaves únicas + o dado a ser atualizado
batch_payload = []
for _, row in resultado_df.iterrows():
    batch_payload.append({
        "ticker": row["ticker"],
        "data_calculo": data_calculo, # Necessário para o upsert resolver o conflito
        "score_cs": row["score_cs"]
    })

# Upsert em lotes de 100
lote = 100
erros = 0
salvos = 0

for i in range(0, len(batch_payload), lote):
    lote_atual = batch_payload[i: i + lote]
    try:
        supabase.table("indicadores").upsert(
            lote_atual,
            on_conflict="ticker,data_calculo" # Chave que definimos lá no início!
        ).execute()
        salvos += len(lote_atual)
    except Exception as e:
        erros += 1
        print(f"  Erro no lote {i}: {e}")

print(f"✅ Score CS atualizado com sucesso. {salvos} registros processados, {erros} lotes com erro.")
