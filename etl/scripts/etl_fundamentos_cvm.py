import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

# Dicionário de Mapeamento Regex para as 12 contas essenciais
# A lógica soma automaticamente curto + longo prazo para Dívida Bruta
MAPEAMENTO = {
    'receita_liquida': r'(?i)receita.l.quida|receita.de.vendas',
    'lucro_bruto': r'(?i)lucro.bruto|resultado.bruto',
    'ebit': r'(?i)lucro.antes.do.resultado.financeiro|resultado.operacional|ebit',
    'ebitda': r'(?i)ebitda|lucro.operacional.antes.da.deprecia',
    'lucro_liquido': r'(?i)lucro.l.quido.do.exerc.cio|lucro.l.quido.atribu',
    'ativo_total': r'(?i)total.do.ativo|ativo.total',
    'ativo_circulante': r'(?i)ativo.circulante(?!.*n.o.circulante)',
    'passivo_circulante': r'(?i)passivo.circulante(?!.*n.o.circulante)',
    'patrimonio_liquido': r'(?i)patrim.nio.l.quido.consolidado|patrim.nio.l.quido',
    'caixa': r'(?i)caixa.e.equivalentes|disponibilidades',
    'divida_bruta': r'(?i)debentures|empr.stimos.e.financiamentos', # Soma curto + longo prazo
    'quantidade_acoes': r'(?i)quantidade.de.a.oes|numero.de.a.oes'
}

def obter_mapa_tickers():
    """Busca o mapeamento CD_CVM -> Ticker direto do Supabase"""
    print("🔄 Buscando mapeamento CD_CVM -> Ticker...")
    emp_data = supabase.table("empresas").select("ticker, cd_cvm").not_.is_("cd_cvm", "null").execute().data
    return {str(int(e['cd_cvm'])): e['ticker'] for e in emp_data if e.get('cd_cvm')}

def processar_ano(ano, tipo_doc, mapa_tickers):
    """Baixa o ZIP, filtra via Regex e agrega em memória"""
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: 
            return [], []
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            for nome in z.namelist():
                if 'CONSOLIDADO' not in nome.upper(): continue
                
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    df_filtrado = df[df['DS_CONTA'].str.contains(regex, na=False, regex=True)]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais: return [], []
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(
            index=['CD_CVM', 'DT_REFER'], 
            columns='conta', 
            values='valor', 
            aggfunc='sum'
        ).reset_index()
        
        # Conversão de tipos e mapeamento de Ticker
        df_pivot['CD_CVM_STR'] = df_pivot['CD_CVM'].astype(str)
        df_pivot['ticker'] = df_pivot['CD_CVM_STR'].map(mapa_tickers)
        df_pivot = df_pivot.dropna(subset=['ticker'])
        
        df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
        df_pivot['data_referencia'] = df_pivot['DT_REFER']
        
        # Lógica de Trimestre
        if tipo_doc == 'ITR':
            df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
            df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
            df_pivot = df_pivot.dropna(subset=['trimestre'])
        else:
            df_pivot['trimestre'] = 4 # DFP é anual
            
        # Cálculo de Dívida Líquida
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        # Preparar colunas finais
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 
                'ebit', 'ebitda', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 
                'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta', 
                'divida_liquida', 'quantidade_acoes']
        
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        df_final['quantidade_acoes'] = df_final['quantidade_acoes'].astype('Int64') # Nullable integer
        
        registros = df_final.to_dict('records')
        return registros, [] # Retorna lista de dicionários
        
    except Exception as e:
        print(f"❌ Erno ano {ano} {tipo_doc}: {e}")
        return [], []

def main():
    print("🔄 Iniciando carga otimizada de fundamentos (Camada Silver)...")
    mapa_tickers = obter_mapa_tickers()
    
    if not mapa_tickers:
        print("❌ Nenhum ticker com CD_CVM encontrado. Abortando.")
        return

    total_registros = 0
    anos = range(2024, datetime.now().year + 1)
    
    for ano in anos:
        print(f"\n📊 Processando {ano}...")
        
        # Processa DFP (Anual)
        registros_dfp, _ = processar_ano(ano, 'DFP', mapa_tickers)
        if registros_dfp:
            supabase.table("fundamentos_anuais").upsert(registros_dfp, on_conflict="ticker,ano").execute()
            supabase.table("fundamentos_trimestrais").upsert(registros_dfp, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_dfp)
            print(f"  ✅ DFP {ano}: {len(registros_dfp)} registros")
            
        # Processa ITR (Trimestral)
        registros_itr, _ = processar_ano(ano, 'ITR', mapa_tickers)
        if registros_itr:
            supabase.table("fundamentos_trimestrais").upsert(registros_itr, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_itr)
            print(f"  ✅ ITR {ano}: {len(registros_itr)} registros")

    supabase.table("etl_cargas").insert({
        "processo": "etl_fundamentos_cvm",
        "inicio": datetime.now(UTC).isoformat(),
        "status": "SUCESSO",
        "registros": total_registros,
        "mensagem": "Fundamentos padronizados carregados"
    }).execute()
    
    print(f"\n CONCLUÍDO! {total_registros} registros salvos nas tabelas fundamentos.")

if __name__ == "__main__":
    main()
