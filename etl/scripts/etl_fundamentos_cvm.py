import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

# CONFIGURAÇÃO DE RANGE DINÂMICO
ANO_INICIAL = 2022  # Altere apenas este valor se quiser expandir o histórico
ANO_FINAL = datetime.now().year  # Automático: sempre pega o ano corrente

MAPEAMENTO = {
    'receita_liquida': r'(?i)receita.de.venda|receita.operacional.bruta',
    'lucro_bruto': r'(?i)resultado.bruto|lucro.bruto',
    'ebit': r'(?i)resultado.antes.do.resultado.financeiro|resultado.operacional',
    'depreciacao_amortizacao': r'(?i)deprecia|amortiza',
    'lucro_liquido': r'(?i)consolidado.do.per.odo|lucro.l.quido.do.exerc.cio',
    'ativo_total': r'(?i)total.do.ativo|ativo.total',
    'ativo_circulante': r'(?i)ativo.circulante(?!.*n.o.circulante)',
    'passivo_circulante': r'(?i)passivo.circulante(?!.*n.o.circulante)',
    'patrimonio_liquido': r'(?i)patrim.nio.l.quido.consolidado|patrim.nio.l.quido',
    'caixa': r'(?i)caixa.e.equivalentes|disponibilidades',
    'divida_bruta': r'(?i)debentures|empr.stimos.e.financiamentos'
}

def obter_dados_empresas():
    """Busca Ticker, CD_CVM e Quantidade de Ações direto da tabela empresas"""
    print("🔄 Buscando dados da tabela empresas...")
    emp_data = supabase.table("empresas").select("ticker, cd_cvm, quantidade_acoes").not_.is_("cd_cvm", "null").execute().data
    
    mapa_tickers = {}
    mapa_acoes = {}
    
    for e in emp_data:
        if e.get('cd_cvm'):
            cd_cvm_str = str(int(e['cd_cvm']))
            mapa_tickers[cd_cvm_str] = e['ticker']
            mapa_acoes[cd_cvm_str] = int(e['quantidade_acoes']) if e.get('quantidade_acoes') else None
            
    print(f"✅ {len(mapa_tickers)} tickers e ações mapeados.")
    return mapa_tickers, mapa_acoes

def processar_ano(ano, tipo_doc, mapa_tickers, mapa_acoes):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
    
    try:
        r = httpx.get(url, timeout=120, follow_redirects=True)
        if r.status_code != 200: 
            print(f"  ⚠️ Arquivo {ano} {tipo_doc} não encontrado (Status {r.status_code})")
            return []
        
        dados_finais = []
        with ZipFile(BytesIO(r.content)) as z:
            arquivos_consolidados = [n for n in z.namelist() if '_con_' in n.lower() or 'consolidado' in n.lower()]
            
            if not arquivos_consolidados:
                print(f"  ⚠️ Nenhum arquivo consolidado encontrado no ZIP de {ano} {tipo_doc}")
                return []

            for nome in arquivos_consolidados:
                df = pd.read_csv(z.open(nome), sep=';', decimal=',', encoding='latin1')
                df['valor'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                
                for conta_padrao, regex in MAPEAMENTO.items():
                    df_filtrado = df[df['DS_CONTA'].str.contains(regex, na=False, regex=True)]
                    if not df_filtrado.empty:
                        agg = df_filtrado.groupby(['CD_CVM', 'DT_REFER'])['valor'].sum().reset_index()
                        agg['conta'] = conta_padrao
                        dados_finais.append(agg)
                        
        if not dados_finais: 
            return []
        
        df_final = pd.concat(dados_finais)
        df_pivot = df_final.pivot_table(
            index=['CD_CVM', 'DT_REFER'], 
            columns='conta', 
            values='valor', 
            aggfunc='sum'
        ).reset_index()
        
        if 'ebit' in df_pivot.columns and 'depreciacao_amortizacao' in df_pivot.columns:
            df_pivot['ebitda'] = df_pivot['ebit'] + df_pivot['depreciacao_amortizacao']
        elif 'ebit' in df_pivot.columns:
            df_pivot['ebitda'] = df_pivot['ebit']
            
        df_pivot['CD_CVM_STR'] = df_pivot['CD_CVM'].astype(str)
        df_pivot['ticker'] = df_pivot['CD_CVM_STR'].map(mapa_tickers)
        df_pivot['quantidade_acoes'] = df_pivot['CD_CVM_STR'].map(mapa_acoes)
        
        tickers_encontrados = df_pivot['ticker'].notna().sum()
        print(f"   🔍 {tickers_encontrados} tickers mapeados com sucesso no {tipo_doc} {ano}")
        
        df_pivot = df_pivot.dropna(subset=['ticker'])
        
        df_pivot['ano'] = pd.to_datetime(df_pivot['DT_REFER']).dt.year
        df_pivot['data_referencia'] = df_pivot['DT_REFER']
        
        if tipo_doc == 'ITR':
            df_pivot['mes'] = pd.to_datetime(df_pivot['DT_REFER']).dt.month
            df_pivot['trimestre'] = df_pivot['mes'].map({3:1, 6:2, 9:3})
            df_pivot = df_pivot.dropna(subset=['trimestre'])
        else:
            df_pivot['trimestre'] = 4
            
        df_pivot['divida_liquida'] = df_pivot.get('divida_bruta', 0) - df_pivot.get('caixa', 0)
        
        cols = ['ticker', 'ano', 'trimestre', 'data_referencia', 'receita_liquida', 'lucro_bruto', 
                'ebit', 'ebitda', 'lucro_liquido', 'ativo_total', 'ativo_circulante', 
                'passivo_circulante', 'patrimonio_liquido', 'caixa', 'divida_bruta', 
                'divida_liquida', 'quantidade_acoes']
        
        df_final = df_pivot[[c for c in cols if c in df_pivot.columns]].replace({np.nan: None})
        
        if 'trimestre' in df_final.columns:
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        if 'ano' in df_final.columns:
            df_final['ano'] = df_final['ano'].astype(int)
        if 'quantidade_acoes' in df_final.columns:
            df_final['quantidade_acoes'] = df_final['quantidade_acoes'].astype('Int64')
            
        return df_final.to_dict('records')
        
    except Exception as e:
        print(f"❌ Erro ano {ano} {tipo_doc}: {e}")
        return []

def main():
    print("🔄 Iniciando carga otimizada de fundamentos (Camada Silver)...")
    mapa_tickers, mapa_acoes = obter_dados_empresas()
    
    if not mapa_tickers:
        print("❌ Nenhum ticker com CD_CVM encontrado. Abortando.")
        return

    total_registros = 0
    # RANGE DINÂMICO: Do ano inicial configurado até o ano corrente
    anos = range(ANO_INICIAL, ANO_FINAL + 1)
    print(f"📅 Processando anos de {ANO_INICIAL} a {ANO_FINAL}...")
    
    for ano in anos:
        print(f"\n📊 Processando {ano}...")
        
        registros_dfp = processar_ano(ano, 'DFP', mapa_tickers, mapa_acoes)
        if registros_dfp:
            registros_anuais = [{k: v for k, v in reg.items() if k != 'trimestre'} for reg in registros_dfp]
            supabase.table("fundamentos_anuais").upsert(registros_anuais, on_conflict="ticker,ano").execute()
            supabase.table("fundamentos_trimestrais").upsert(registros_dfp, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_dfp)
            print(f"  ✅ DFP {ano}: {len(registros_dfp)} registros")
            
        registros_itr = processar_ano(ano, 'ITR', mapa_tickers, mapa_acoes)
        if registros_itr:
            supabase.table("fundamentos_trimestrais").upsert(registros_itr, on_conflict="ticker,ano,trimestre").execute()
            total_registros += len(registros_itr)
            print(f"  ✅ ITR {ano}: {len(registros_itr)} registros")

    print(f"\n🏆 CONCLUÍDO! {total_registros} registros salvos.")

if __name__ == "__main__":
    main()
