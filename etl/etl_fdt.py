def main():
    print("=" * 80)
    print("🔍 ETL FUNDAMENTUS - MODO PREVIEW")
    print("=" * 80)
    
    # 1. Extrair dados
    df = extrair_tabela_fundamentus()
    
    if df is None:
        return
    
    # 2. Processar
    df = processar_dados(df)
    
    # 3. Exibir primeiros registros
    print("\n📊 PRIMEIROS 10 REGISTROS:")
    print("-" * 80)
    print(df.head(10).to_string())
    
    # 4. Estatísticas
    print("\n📈 ESTATÍSTICAS:")
    print("-" * 80)
    print(f"Total de tickers: {len(df)}")
    print(f"Tickers com P/L > 0: {len(df[df['p_l'] > 0])}")
    print(f"Tickers com ROE > 0: {len(df[df['roe'] > 0])}")
    print(f"Data de cálculo: {df['data_calculo'].iloc[0]}")
