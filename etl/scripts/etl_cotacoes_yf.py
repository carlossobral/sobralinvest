from datetime import datetime, UTC
import time
import math
import yfinance as yf
from etl.database.supabase_client import supabase

# ==========================================================
# CONFIGURAÇÃO DE ANOS (Controle manual igual ao etl_indicadores)
# ==========================================================
ANO_INICIAL = 2015
ANO_FINAL = datetime.now().year

# Lista de tickers inválidos, deslistados ou índices que não devem ser processados
TICKERS_IGNORADOS = {
    "AFLT3", "AHEB3", "AHEB5", "AHEB6", "APTI3", "APTI4", "AURA33", "BALM3", 
    "BALM4", "BBML3", "BDLL3", "BDLL4", "BOBR3", "BOBR4", "BRQB3", "CALI3", 
    "CASN3", "CASN4", "CATA3", "CATA4", "CEGR3", "CTAX3", "CTCA3", "CTKA3", 
    "CTKA4", "CTSA3", "CTSA4", "DOHL3", "DOHL4", "DTCY3", "DTCY4", "EALT3", 
    "EALT4", "EKTR3", "EKTR4", "ENMT3", "ENMT4", "EPAR3", "ESTR3", "ESTR4", 
    "FIGE3", "FIGE4", "G2DI33", "GOLL54", "GPAR3", "GSHP3", "HBTS3", "HBTS5", "HBTS6", 
    "HETA3", "HETA4", "HOOT3", "HOOT4", "IGSN3", "JFEN3", "JOPA3", "JOPA4", 
    "LMED3", "LTEL3B", "LUXM3", "LUXM4", "MAPT3", "MAPT4", "MGEL3", "MGEL4", 
    "MMAQ3", "MMAQ4", "MNDL3", "MRSA3B", "MRSA5B", "MRSA6B", "MSPA3", "MSPA4", 
    "MWET3", "MWET4", "NEMO3", "ODER3", "ODER4", "OIBR3", "OIBR4", "OSXB3", 
    "PATI3", "PATI4", "PEAB3", "PEAB4", "PLAS3", "PPAR3", "PPLA11", "PTCA3", 
    "QUSW3", "RPAD3", "RPAD5", "RPAD6", "RPMG3", "RSID3", "SNSY3", "SNSY5", 
    "SNSY6", "SOND3", "SOND5", "SOND6", "TELB3", "TELB4", "TRAD3", "TXRX3", "TXRX4", 
    "VSPT3", "VSPT4", "IBOV"
}

def safe_float(v):
    try:
        f = float(v)
        if math.isnan(f): return None
        return f
    except:
        return None

def safe_int(v):
    try:
        i = int(v)
        if math.isnan(i): return 0
        return i
    except:
        return 0

def registrar_carga(status: str, registros: int, mensagem: str):
    supabase.table("etl_cargas").insert({
        "processo": "etl_cotacoes_yf",
        "inicio": datetime.now(UTC).isoformat(),
        "status": status,
        "registros": registros,
        "mensagem": mensagem,
    }).execute()

def carregar_ticker(ticker: str):
    start_date = f"{ANO_INICIAL}-01-01"
    end_date = f"{ANO_FINAL}-12-31"
    
    df = yf.download(
        f"{ticker}.SA",
        start=start_date,
        end=end_date,
        auto_adjust=True, 
        progress=False,
        threads=False
    )

    if df.empty:
        return 0

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    registros = []

    for data, row in df.iterrows():
        fechamento = safe_float(row["Close"])
        volume = safe_int(row["Volume"])
        
        vol_fin = (fechamento * volume) if fechamento and volume else 0.0

        registros.append({
            "ticker": ticker,
            "data": data.strftime("%Y-%m-%d"),
            "abertura": safe_float(row["Open"]),
            "maxima": safe_float(row["High"]),
            "minima": safe_float(row["Low"]),
            "fechamento": fechamento,
            "volume": volume,
            "volume_financeiro": vol_fin
        })

    if not registros:
        return 0
        
    lote = 500
    for i in range(0, len(registros), lote):
        supabase.table("cotacoes").upsert(
            registros[i:i + lote],
            on_conflict="ticker,data"
        ).execute()

    return len(registros)

def main():
    print(f"Iniciando carga de cotações via yfinance ({ANO_INICIAL}-{ANO_FINAL})...")
    
    total_registros = 0
    processados = 0
    ignorados = 0
    
    try:
        empresas = supabase.table("empresas").select("ticker").order("ticker").execute().data
        print(f"Empresas encontradas: {len(empresas)}\n")

                for i, empresa in enumerate(empresas, start=1):
            ticker = empresa["ticker"]

            if ticker in TICKERS_IGNORADOS:
                ignorados += 1
                continue

            print(f"[{i}/{len(empresas)}] {ticker}...", end=" ")
            
            try:
                total = carregar_ticker(ticker)
                
                # Se retornou 0, tenta novamente após 2 segundos (Retry para evitar timeout do Yahoo)
                if total == 0:
                    time.sleep(2)
                    total = carregar_ticker(ticker)

                total_registros += total
                processados += 1
                
                if total > 0:
                    print(f"{total} registros atualizados.")
                else:
                    print("Sem dados (Delistada ou erro no Yahoo).")
                
                # Regra 3: Sleep aumentado para 1.5s para evitar banimento/timeout
                time.sleep(1.5) 
                
            except Exception as e:
                print(f"ERRO: {e}")

        mensagem = f"{processados} tickers atualizados. {ignorados} ignorados."
        registrar_carga("SUCESSO", total_registros, mensagem)
        
        print("\n========== FINAL ==========")
        print(f"Tickers processados : {processados}")
        print(f"Tickers ignorados   : {ignorados}")
        print(f"Registros gravados  : {total_registros}")

    except Exception as e:
        registrar_carga("ERRO", 0, str(e))
        print(f"\n❌ ERRO FATAL: {e}")
        raise

if __name__ == "__main__":
    main()
