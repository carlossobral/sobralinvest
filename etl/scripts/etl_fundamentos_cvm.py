import pandas as pd
import numpy as np
import httpx
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, UTC
from etl.database.supabase_client import supabase

ANO_INICIAL = 2019
ANO_FINAL = datetime.now().year

# Contas validadas
MAPEAMENTO_DRE = {
    'receita_liquida': r'^3\.01$',
    'custo':           r'^3\.02$',
    'ebit':            r'^3\.05$',
}

MAPEAMENTO_BPA = {
    'ativo_total':      r'^1$',
    'ativo_circulante': r'^1\.01$',
    'caixa':            r'^1\.01\.01\.01$',
}

MAPEAMENTO_BPP = {
    'passivo_circulante': r'^2\.01$',
    'divida_bruta':       r'^2\.02$',
    'patrimonio_liquido': r'^2\.03$',
}

COLUNAS_DRE = ['receita_liquida', 'custo', 'lucro_bruto', 'ebit', 'ebitda', 'lucro_liquido']
COLUNAS_BAL = ['ativo_total', 'ativo_circulante', 'passivo_circulante',
               'patrimonio_liquido', 'caixa', 'divida_bruta', 'divida_liquida']


def registrar_carga(status, registros, mensagem):
    try:
        supabase.table("etl_cargas").insert({
            "processo": "etl_fundamentos_cvm",
            "inicio": datetime.now(UTC).isoformat(),
            "status": status,
            "registros": registros,
            "mensagem": mensagem,
        }).execute()
    except Exception as e:
        print(f"Erro ao registrar carga: {e}")


def obter_dados_empresas():
    print("Buscando empresas...")
    data = (
        supabase.table("empresas")
        .select("ticker, cd_cvm, quantidade_acoes")
        .not_.is_("cd_cvm", "null")
        .execute()
        .data
    )

    mapa_tickers, mapa_acoes = {}, {}
    for e in data:
        if e.get('cd_cvm'):
            key = str(int(float(e['cd_cvm'])))
            mapa_tickers[key] = e['ticker']
            mapa_acoes[key] = int(e['quantidade_acoes']) if e.get('quantidade_acoes') else None

    print(f"  {len(mapa_tickers)} tickers mapeados.")
    return mapa_tickers, mapa_acoes


def extrair_lucro_liquido(df):
    df311 = df[df['CD_CONTA'].str.fullmatch(r'^3\.11$', na=False)].copy()
    df309 = df[df['CD_CONTA'].str.fullmatch(r'^3\.09$', na=False)].copy()

    df311_agg = df311.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
    df311_agg.columns = ['CD_CVM', 'DT_REFER', 'lucro_liquido']

    df309_agg = df309.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
    df309_agg.columns = ['CD_CVM', 'DT_REFER', 'lucro_liquido_309']

    merged = df311_agg.merge(df309_agg, on=['CD_CVM', 'DT_REFER'], how='outer')
    merged['lucro_liquido'] = merged['lucro_liquido'].combine_first(merged['lucro_liquido_309'])
    return merged[['CD_CVM', 'DT_REFER', 'lucro_liquido']].set_index(['CD_CVM', 'DT_REFER'])


def processar_csv_dre(df_csv, mapeamento):
    frames = {}
    for conta, regex in mapeamento.items():
        mask = df_csv['CD_CONTA'].astype(str).str.strip().str.fullmatch(regex, na=False)
        sub = df_csv[mask]
        if sub.empty:
            continue
        agg = sub.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].first().reset_index()
        agg.columns = ['CD_CVM', 'DT_REFER', conta]
        frames[conta] = agg.set_index(['CD_CVM', 'DT_REFER'])
    return frames


def processar_ano(ano, tipo_doc, mapa_tickers, mapa_acoes):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"

    try:
        r = httpx.get(url, timeout=180, follow_redirects=True)
        if r.status_code != 200:
            print(f"  {tipo_doc} {ano}: HTTP {r.status_code}")
            return pd.DataFrame()

        resultado = {}

        with ZipFile(BytesIO(r.content)) as z:
            csvs_con = [n for n in z.namelist() if '_con_' in n.lower() and n.endswith('.csv')]

            dre_csv  = [n for n in csvs_con if '_DRE_' in n.upper()]
            bpa_csv  = [n for n in csvs_con if '_BPA_' in n.upper()]
            bpp_csv  = [n for n in csvs_con if '_BPP_' in n.upper()]

            # DRE
            for nome in dre_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()

                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']

                frames = processar_csv_dre(df, MAPEAMENTO_DRE)
                for conta, frame in frames.items():
                    if conta not in resultado:
                        resultado[conta] = frame
                    else:
                        resultado[conta] = resultado[conta].combine_first(frame)

                ll = extrair_lucro_liquido(df)
                if 'lucro_liquido' not in resultado:
                    resultado['lucro_liquido'] = ll
                else:
                    resultado['lucro_liquido'] = resultado['lucro_liquido'].combine_first(ll)

            # BPA
            for nome in bpa_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()
                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']
                frames = processar_csv_dre(df, MAPEAMENTO_BPA)
                for conta, frame in frames.items():
                    resultado[conta] = frame

            # BPP
            for nome in bpp_csv:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0)
                df['CD_CONTA'] = df['CD_CONTA'].astype(str).str.strip()
                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']
                frames = processar_csv_dre(df, MAPEAMENTO_BPP)
                for conta, frame in frames.items():
                    resultado[conta] = frame

        if not resultado:
            return pd.DataFrame()

        df_final = pd.concat(resultado.values(), axis=1).reset_index()

        if 'receita_liquida' in df_final.columns and 'custo' in df_final.columns:
            df_final['lucro_bruto'] = df_final['receita_liquida'] + df_final['custo']

        if 'ebit' in df_final.columns:
            df_final['ebitda'] = df_final['ebit']

        for col in [c for c in COLUNAS_DRE + COLUNAS_BAL if c in df_final.columns]:
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce') * 1000

        div = df_final.get('divida_bruta', pd.Series(0, index=df_final.index)).fillna(0)
        cxa = df_final.get('caixa', pd.Series(0, index=df_final.index)).fillna(0)
        df_final['divida_liquida'] = div - cxa

        df_final['CD_CVM_STR'] = df_final['CD_CVM'].astype(str)
        df_final['ticker'] = df_final['CD_CVM_STR'].map(mapa_tickers)
        df_final['quantidade_acoes'] = df_final['CD_CVM_STR'].map(mapa_acoes)
        df_final = df_final.dropna(subset=['ticker'])

        if df_final.empty:
            return pd.DataFrame()

        df_final['DT_REFER'] = pd.to_datetime(df_final['DT_REFER'], errors='coerce')
        df_final['ano'] = df_final['DT_REFER'].dt.year
        df_final['data_referencia'] = df_final['DT_REFER'].dt.strftime('%Y-%m-%d')

        if tipo_doc == 'ITR':
            df_final['trimestre'] = df_final['DT_REFER'].dt.month.map({3: 1, 6: 2, 9: 3})
            df_final = df_final.dropna(subset=['trimestre'])
            df_final['trimestre'] = df_final['trimestre'].astype(int)
        else:
            df_final['trimestre'] = 4

        for col in COLUNAS_DRE:
            if col in df_final.columns:
                df_final[f'{col}_ytd'] = df_final[col]
                df_final = df_final.drop(columns=[col])

        cols_saida = (
            ['ticker', 'ano', 'trimestre', 'data_referencia']
            + [f'{c}_ytd' for c in COLUNAS_DRE if f'{c}_ytd' in df_final.columns]
            + [c for c in COLUNAS_BAL if c in df_final.columns]
            + ['quantidade_acoes']
        )

        df_out = df_final[[c for c in cols_saida if c in df_final.columns]].copy()
        df_out['ano'] = df_out['ano'].astype(int)
        df_out['trimestre'] = df_out['trimestre'].astype(int)
        if 'quantidade_acoes' in df_out.columns:
            df_out['quantidade_acoes'] = pd.to_numeric(df_out['quantidade_acoes'], errors='coerce').astype('Int64')

        df_out['fonte'] = tipo_doc
        df_out = df_out.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        return df_out

    except Exception as e:
        print(f"  Erro {tipo_doc} {ano}: {e}")
        return pd.DataFrame()


def processar_dfc(ano, tipo_doc, mapa_tickers):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFC_MI/DADOS/dfc_mi_cia_aberta_{ano}.zip"

    try:
        r = httpx.get(url, timeout=180, follow_redirects=True)
        if r.status_code != 200:
            print(f"  [DFC] Falha ao baixar {ano}: HTTP {r.status_code}")
            return pd.DataFrame()

        frames = []
        with ZipFile(BytesIO(r.content)) as z:
            csvs = [n for n in z.namelist() if '_con_' in n.lower() and n.endswith('.csv')]
            if not csvs:
                print(f"  [DFC] Nenhum arquivo _con_ encontrado no ZIP de {ano}")
                return pd.DataFrame()
                
            for nome in csvs:
                df = pd.read_csv(z.open(nome), sep=';', encoding='latin1', low_memory=False)
                df['VL_CONTA'] = pd.to_numeric(df['VL_CONTA'], errors='coerce').fillna(0) * 1000

                if 'ORDEM_EXERC' in df.columns:
                    norm = df['ORDEM_EXERC'].astype(str).str.upper().str.strip()
                    norm = norm.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
                    df = df[norm == 'ULTIMO']

                # Filtro robusto para D&A
                df['CD_CONTA_STR'] = df['CD_CONTA'].astype(str).str.strip()
                df['DS_CONTA_STR'] = df['DS_CONTA'].astype(str).str.strip().str.lower()
                
                mask_da = (
                    df['CD_CONTA_STR'].str.startswith('6.01.01') &
                    (df['DS_CONTA_STR'].str.contains('deprecia', na=False) | 
                     df['DS_CONTA_STR'].str.contains('amortiza', na=False) |
                     df['DS_CONTA_STR'].str.contains('exaust', na=False))
                )
                df_da = df[mask_da]

                if not df_da.empty:
                    agg = df_da.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
                    frames.append(agg)

        if not frames:
            print(f"  [DFC] Nenhum registro de D&A encontrado em {ano}")
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df = df.groupby(['CD_CVM', 'DT_REFER'])['VL_CONTA'].sum().reset_index()
        df.columns = ['CD_CVM', 'DT_REFER', 'depreciacao_amortizacao']

        df['CD_CVM_STR'] = df['CD_CVM'].astype(str)
        df['ticker'] = df['CD_CVM_STR'].map(mapa_tickers)
        df = df.dropna(subset=['ticker'])

        df['DT_REFER'] = pd.to_datetime(df['DT_REFER'], errors='coerce')
        df['ano'] = df['DT_REFER'].dt.year.astype(int)
        df['data_referencia'] = df['DT_REFER'].dt.strftime('%Y-%m-%d')

        if tipo_doc == 'ITR':
            df['trimestre'] = df['DT_REFER'].dt.month.map({3: 1, 6: 2, 9: 3})
            df = df.dropna(subset=['trimestre'])
            df['trimestre'] = df['trimestre'].astype(int)
        else:
            df['trimestre'] = 4

        return df[['ticker', 'ano', 'trimestre', 'depreciacao_amortizacao']].drop_duplicates(
            subset=['ticker', 'ano', 'trimestre'], keep='last'
        )

    except Exception as e:
        print(f"  [DFC] Erro {tipo_doc} {ano}: {e}")
        return pd.DataFrame()


def calcular_colunas_q(df):
    print("Calculando colunas _q...")
    df = df.sort_values(['ticker', 'ano', 'data_referencia']).reset_index(drop=True)

    for col_base in COLUNAS_DRE:
        col_ytd = f'{col_base}_ytd'
        col_q = f'{col_base}_q'
        if col_ytd not in df.columns:
            continue

        grupo = df['ticker'].astype(str) + '_' + df['ano'].astype(str)
        df[col_q] = df.groupby(grupo)[col_ytd].diff()
        df[col_q] = df[col_q].fillna(df[col_ytd])

    print(f"  {len(df)} registros processados.")
    return df


def integrar_dfc(df_principal, df_dfc):
    if df_dfc.empty:
        print("  [DFC] Sem dados de D&A. EBITDA = EBIT.")
        return df_principal

    print(f"  [DFC] Integrando D&A: {len(df_dfc)} registros...")
    df = df_principal.merge(df_dfc, on=['ticker', 'ano', 'trimestre'], how='left')

    if 'ebit_ytd' in df.columns:
        da = df['depreciacao_amortizacao'].fillna(0)
        df['ebitda_ytd'] = df['ebit_ytd'] + da

    if 'ebit_q' in df.columns:
        da_q = df['depreciacao_amortizacao'].fillna(0) / 4.0
        df['ebitda_q'] = df['ebit_q'] + da_q

    ok = df['depreciacao_amortizacao'].notna().sum()
    print(f"  [DFC] {ok} registros com D&A integrado com sucesso.")
    return df


def main():
    print("Iniciando ETL de fundamentos CVM...")
    mapa_tickers, mapa_acoes = obter_dados_empresas()
    if not mapa_tickers:
        print("Nenhum ticker. Abortando.")
        return

    todos_dfp = []
    todos_itr = []
    todos_dfc = []

    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        print(f"\nAno {ano}...")

        df_dfp = processar_ano(ano, 'DFP', mapa_tickers, mapa_acoes)
        if not df_dfp.empty:
            todos_dfp.append(df_dfp)
            print(f"  DFP: {len(df_dfp)} registros")

        df_itr = processar_ano(ano, 'ITR', mapa_tickers, mapa_acoes)
        if not df_itr.empty:
            todos_itr.append(df_itr)
            print(f"  ITR: {len(df_itr)} registros")

        df_dfc_dfp = processar_dfc(ano, 'DFP', mapa_tickers)
        if not df_dfc_dfp.empty:
            todos_dfc.append(df_dfc_dfp)
            print(f"  DFC DFP: {len(df_dfc_dfp)} registros")

        df_dfc_itr = processar_dfc(ano, 'ITR', mapa_tickers)
        if not df_dfc_itr.empty:
            todos_dfc.append(df_dfc_itr)
            print(f"  DFC ITR: {len(df_dfc_itr)} registros")

    if not todos_dfp and not todos_itr:
        print("Nenhum dado extraído.")
        registrar_carga("ERRO", 0, "Nenhum dado extraído")
        return

    if todos_dfp and todos_itr:
        df_dfp_all = pd.concat(todos_dfp, ignore_index=True)
        df_itr_all = pd.concat(todos_itr, ignore_index=True)
        
        df_dfp_all = df_dfp_all.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        df_itr_all = df_itr_all.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        
        df_final = df_dfp_all.copy()
        
        df_itr_somente = df_itr_all.merge(
            df_dfp_all[['ticker', 'ano', 'trimestre']],
            on=['ticker', 'ano', 'trimestre'],
            how='left',
            indicator=True
        )
        df_itr_somente = df_itr_somente[df_itr_somente['_merge'] == 'left_only'].drop(columns=['_merge'])
        
        print(f"\nPriorização: {len(df_dfp_all)} DFP + {len(df_itr_somente)} ITR (exclusivos)")
        df_final = pd.concat([df_final, df_itr_somente], ignore_index=True)
        
    elif todos_dfp:
        df_final = pd.concat(todos_dfp, ignore_index=True)
    else:
        df_final = pd.concat(todos_itr, ignore_index=True)

    if 'fonte' in df_final.columns:
        df_final = df_final.drop(columns=['fonte'])

    df_final = calcular_colunas_q(df_final)

    if todos_dfc:
        df_dfc = pd.concat(todos_dfc, ignore_index=True)
        df_dfc = df_dfc.drop_duplicates(subset=['ticker', 'ano', 'trimestre'], keep='last')
        df_final = integrar_dfc(df_final, df_dfc)

    df_final = df_final.replace({np.nan: None, pd.NaT: None})
    registros = df_final.to_dict('records')

    print(f"\nSalvando {len(registros)} registros...")
    total = 0
    erros = 0
    for i in range(0, len(registros), 100):
        try:
            supabase.table("fundamentos_trimestrais").upsert(
                registros[i:i + 100],
                on_conflict="ticker,ano,trimestre"
            ).execute()
            total += len(registros[i:i + 100])
        except Exception as e:
            erros += 1
            print(f"  Erro lote {i}: {e}")

    registrar_carga("SUCESSO", total, f"{total} registros, {erros} erros")
    print(f"\n========== FINAL ==========")
    print(f"Registros salvos : {total}")
    print(f"Lotes com erro   : {erros}")


if __name__ == "__main__":
    main()
