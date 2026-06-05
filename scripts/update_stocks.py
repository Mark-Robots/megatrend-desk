"""
Megatrend Sentinel STOCKS · Data Update v2 (Historical Backtest)
=================================================================
Replica completa del sistema settoriale ETF, applicato alle azioni:
- Backtest storico dal 2018-01-01 a oggi
- Per ogni settimana storica: ricostruzione stati settori + pinning azione
- Simulazione portfolio equipesato sulle azioni pinnate
- Tre curve: Sistema Azioni, Cash (XEON), MSCI World (XDWD)
- Statistiche: CAGR, Sharpe, Max DD, Win Rate, P/L ratio, totale operazioni
- Storico completo operazioni (entry/exit, prezzo, perf%)

Output: data/stocks_data.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
STOCKS_DATA_JSON = DATA_DIR / 'stocks_data.json'

BACKTEST_START = '2018-01-01'
SHARPE_RF = 0.0034

US_BENCHMARK = 'SPY'
EU_BENCHMARK = 'EXSA.DE'
CASH_TICKER = 'XEON.DE'
WORLD_TICKER = 'XDWD.DE'

US_SECTORS_ETF = ['XLK', 'SOXX', 'XLF', 'XLV', 'IBB', 'XLY', 'XLP', 'XLE',
                   'XLI', 'ITA', 'XLB', 'XLU', 'XLRE', 'XLC', 'KRE', 'XHB', 'XRT']

EU_SECTORS_ETF = ['EXV1.DE', 'EXH1.DE', 'EXH5.DE', 'EXH4.DE', 'EXH6.DE',
                   'EXV5.DE', 'EXV3.DE', 'EXV2.DE', 'EXV4.DE', 'EXH7.DE',
                   'EXV6.DE', 'EXH8.DE', 'EXH9.DE', 'EXH3.DE', 'EXV7.DE', 'EXV9.DE']

SECTOR_NAMES = {
    'XLK': 'Tecnologia USA', 'SOXX': 'Semiconduttori',
    'XLF': 'Finanziari USA', 'XLV': 'Sanità USA',
    'IBB': 'Biotech', 'XLY': 'Consumi voluttuari',
    'XLP': 'Consumi essenziali', 'XLE': 'Energia USA',
    'XLI': 'Industriali USA', 'ITA': 'Aerospazio & Difesa',
    'XLB': 'Materiali base', 'XLU': 'Utility USA',
    'XLRE': 'Immobiliare', 'XLC': 'Comunicazioni',
    'KRE': 'Banche regionali', 'XHB': 'Costruttori case',
    'XRT': 'Retail USA',
    'EXV1.DE': 'Banche EU', 'EXH1.DE': 'Energia EU',
    'EXH5.DE': 'Assicurazioni', 'EXH4.DE': 'Industriali EU',
    'EXH6.DE': 'Beni personali', 'EXV5.DE': 'Automobili',
    'EXV3.DE': 'Tecnologia EU', 'EXV2.DE': 'Telecomunicazioni',
    'EXV4.DE': 'Sanità EU', 'EXH7.DE': 'Alimentari & Bevande',
    'EXV6.DE': 'Risorse base', 'EXH8.DE': 'Media',
    'EXH9.DE': 'Utility EU', 'EXH3.DE': 'Servizi finanziari',
    'EXV7.DE': 'Chimica', 'EXV9.DE': 'Viaggi & Tempo libero',
}

US_UNIVERSE = {
    'XLK':  ['NVDA', 'MSFT', 'AAPL', 'AVGO', 'ORCL', 'CSCO', 'AMD', 'IBM', 'QCOM', 'TXN'],
    'SOXX': ['NVDA', 'TSM', 'AVGO', 'MU', 'AMD', 'ASML', 'AMAT', 'LRCX', 'KLAC', 'ADI'],
    'XLF':  ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'BX', 'C', 'AXP', 'SPGI', 'BLK'],
    'XLV':  ['LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR', 'ISRG'],
    'IBB':  ['AMGN', 'GILD', 'VRTX', 'REGN', 'BIIB', 'ILMN', 'INCY', 'BMRN'],
    'XLY':  ['AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'LOW', 'BKNG', 'SBUX', 'TJX', 'CMG'],
    'XLP':  ['WMT', 'COST', 'PG', 'KO', 'PEP', 'PM', 'MDLZ', 'MO', 'CL', 'KMB'],
    'XLE':  ['XOM', 'CVX', 'COP', 'EOG', 'SLB', 'MPC', 'PSX', 'OXY', 'VLO', 'KMI'],
    'XLI':  ['GE', 'RTX', 'CAT', 'HON', 'UNP', 'BA', 'DE', 'ETN', 'LMT'],
    'ITA':  ['GE', 'RTX', 'BA', 'LMT', 'GD', 'NOC', 'TDG', 'LHX', 'HII'],
    'XLB':  ['LIN', 'SHW', 'APD', 'FCX', 'ECL', 'NEM', 'NUE', 'DOW', 'DD', 'CTVA'],
    'XLU':  ['NEE', 'DUK', 'SO', 'AEP', 'D', 'SRE', 'EXC', 'XEL', 'AES'],
    'XLRE': ['PLD', 'AMT', 'EQIX', 'WELL', 'SPG', 'PSA', 'CCI', 'DLR', 'O', 'EXR'],
    'XLC':  ['META', 'GOOGL', 'NFLX', 'T', 'VZ', 'CMCSA', 'DIS', 'EA', 'TMUS'],
    'KRE':  ['USB', 'PNC', 'TFC', 'MTB', 'KEY', 'RF', 'CFG', 'FITB', 'ZION', 'HBAN'],
    'XHB':  ['DHI', 'LEN', 'PHM', 'NVR', 'MTH', 'TOL', 'BLDR', 'WHR', 'MAS'],
    'XRT':  ['COST', 'AMZN', 'HD', 'LOW', 'TGT', 'KSS', 'TJX', 'ROST', 'DG', 'DLTR'],
}

IT_UNIVERSE = {
    'EXV1.DE': ['ISP.MI', 'UCG.MI', 'BAMI.MI', 'BMPS.MI', 'MB.MI', 'BPSO.MI', 'BPER.MI', 'FBK.MI'],
    'EXH1.DE': ['ENI.MI', 'SRG.MI', 'TEN.MI', 'HER.MI', 'A2A.MI'],
    'EXH5.DE': ['G.MI', 'UNI.MI', 'PST.MI'],
    'EXH4.DE': ['PRY.MI', 'LDO.MI', 'CNHI.MI', 'IP.MI', 'DAN.MI', 'AVIO.MI', 'WBD.MI', 'BZU.MI'],
    'EXH6.DE': ['MONC.MI', 'BC.MI', 'TPRO.MI', 'FCT.MI', 'RACE.MI'],
    'EXV5.DE': ['STLAM.MI', 'RACE.MI', 'BRE.MI', 'PIRC.MI', 'IVG.MI', 'CNHI.MI'],
    'EXV3.DE': ['STM.MI', 'REY.MI', 'TPRO.MI', 'TXT.MI', 'DEA.MI'],
    'EXV2.DE': ['TIT.MI', 'INW.MI'],
    'EXV4.DE': ['REC.MI', 'DIA.MI', 'AMP.MI', 'GVS.MI'],
    'EXH7.DE': ['CPR.MI', 'DLG.MI'],
    'EXV6.DE': ['TEN.MI', 'PRY.MI', 'BZU.MI'],
    'EXH8.DE': ['MN.MI', 'MFEA.MI', 'RCS.MI', 'CAI.MI'],
    'EXH9.DE': ['ENEL.MI', 'TRN.MI', 'HER.MI', 'A2A.MI', 'IG.MI'],
    'EXH3.DE': ['BGN.MI', 'AZM.MI', 'FBK.MI'],
    'EXV7.DE': ['ECNL.MI'],
    'EXV9.DE': ['MARR.MI', 'IG.MI'],
}

POSITIVE_TAGS = {'top_momentum', 'value_momentum', 'premium_ok'}
DISQUALIFYING_TAGS = {'value_trap', 'expensive_flat', 'stagnant'}

# Mappa ticker → nome esteso per la dashboard cliente
STOCK_NAMES = {
    # USA — Tecnologia (XLK)
    'NVDA': 'NVIDIA', 'MSFT': 'Microsoft', 'AAPL': 'Apple', 'AVGO': 'Broadcom',
    'ORCL': 'Oracle', 'CSCO': 'Cisco', 'AMD': 'AMD', 'IBM': 'IBM',
    'QCOM': 'Qualcomm', 'TXN': 'Texas Instruments',
    # USA — Semiconduttori (SOXX) — alcuni già sopra
    'TSM': 'TSMC', 'MU': 'Micron', 'ASML': 'ASML', 'AMAT': 'Applied Materials',
    'LRCX': 'Lam Research', 'KLAC': 'KLA', 'ADI': 'Analog Devices',
    # USA — Finanziari (XLF)
    'JPM': 'JP Morgan', 'BAC': 'Bank of America', 'WFC': 'Wells Fargo',
    'GS': 'Goldman Sachs', 'MS': 'Morgan Stanley', 'BX': 'Blackstone',
    'C': 'Citigroup', 'AXP': 'American Express', 'SPGI': 'S&P Global', 'BLK': 'BlackRock',
    # USA — Salute (XLV)
    'LLY': 'Eli Lilly', 'UNH': 'UnitedHealth', 'JNJ': 'Johnson & Johnson',
    'ABBV': 'AbbVie', 'MRK': 'Merck', 'PFE': 'Pfizer', 'TMO': 'Thermo Fisher',
    'ABT': 'Abbott', 'DHR': 'Danaher', 'ISRG': 'Intuitive Surgical',
    # USA — Biotech (IBB)
    'AMGN': 'Amgen', 'GILD': 'Gilead', 'VRTX': 'Vertex Pharma', 'REGN': 'Regeneron',
    'BIIB': 'Biogen', 'ILMN': 'Illumina', 'INCY': 'Incyte', 'BMRN': 'BioMarin',
    # USA — Consumer Discretionary (XLY)
    'AMZN': 'Amazon', 'TSLA': 'Tesla', 'HD': 'Home Depot', 'MCD': "McDonald's",
    'NKE': 'Nike', 'LOW': "Lowe's", 'BKNG': 'Booking Holdings', 'SBUX': 'Starbucks',
    'TJX': 'TJX Companies', 'CMG': 'Chipotle',
    # USA — Consumer Staples (XLP)
    'WMT': 'Walmart', 'COST': 'Costco', 'PG': 'Procter & Gamble', 'KO': 'Coca-Cola',
    'PEP': 'PepsiCo', 'PM': 'Philip Morris', 'MDLZ': 'Mondelez', 'MO': 'Altria',
    'CL': 'Colgate-Palmolive', 'KMB': 'Kimberly-Clark',
    # USA — Energia (XLE)
    'XOM': 'ExxonMobil', 'CVX': 'Chevron', 'COP': 'ConocoPhillips', 'EOG': 'EOG Resources',
    'SLB': 'Schlumberger', 'MPC': 'Marathon Petroleum', 'PSX': 'Phillips 66',
    'OXY': 'Occidental Petroleum', 'VLO': 'Valero Energy', 'KMI': 'Kinder Morgan',
    # USA — Industriali (XLI)
    'GE': 'General Electric', 'RTX': 'RTX (Raytheon)', 'CAT': 'Caterpillar',
    'HON': 'Honeywell', 'UNP': 'Union Pacific', 'BA': 'Boeing', 'DE': 'John Deere',
    'ETN': 'Eaton', 'LMT': 'Lockheed Martin',
    # USA — Difesa (ITA)
    'GD': 'General Dynamics', 'NOC': 'Northrop Grumman', 'TDG': 'TransDigm',
    'LHX': 'L3Harris', 'HII': 'Huntington Ingalls',
    # USA — Materiali (XLB)
    'LIN': 'Linde', 'SHW': 'Sherwin-Williams', 'APD': 'Air Products',
    'FCX': 'Freeport-McMoRan', 'ECL': 'Ecolab', 'NEM': 'Newmont',
    'NUE': 'Nucor', 'DOW': 'Dow', 'DD': 'DuPont', 'CTVA': 'Corteva',
    # USA — Utilities (XLU)
    'NEE': 'NextEra Energy', 'DUK': 'Duke Energy', 'SO': 'Southern Co',
    'AEP': 'American Electric Power', 'D': 'Dominion Energy', 'SRE': 'Sempra',
    'EXC': 'Exelon', 'XEL': 'Xcel Energy', 'AES': 'AES Corp',
    # USA — Real Estate (XLRE)
    'PLD': 'Prologis', 'AMT': 'American Tower', 'EQIX': 'Equinix',
    'WELL': 'Welltower', 'SPG': 'Simon Property', 'PSA': 'Public Storage',
    'CCI': 'Crown Castle', 'DLR': 'Digital Realty', 'O': 'Realty Income', 'EXR': 'Extra Space',
    # USA — Communications (XLC)
    'META': 'Meta', 'GOOGL': 'Alphabet (Google)', 'NFLX': 'Netflix',
    'T': 'AT&T', 'VZ': 'Verizon', 'CMCSA': 'Comcast', 'DIS': 'Disney',
    'EA': 'Electronic Arts', 'TMUS': 'T-Mobile',
    # USA — Banche regionali (KRE)
    'USB': 'US Bancorp', 'PNC': 'PNC Financial', 'TFC': 'Truist',
    'MTB': 'M&T Bank', 'KEY': 'KeyCorp', 'RF': 'Regions Financial',
    'CFG': 'Citizens Financial', 'FITB': 'Fifth Third', 'ZION': 'Zions Bancorp', 'HBAN': 'Huntington',
    # USA — Edilizia (XHB)
    'DHI': 'DR Horton', 'LEN': 'Lennar', 'PHM': 'PulteGroup',
    'NVR': 'NVR Inc', 'MTH': 'Meritage Homes', 'TOL': 'Toll Brothers',
    'BLDR': 'Builders FirstSource', 'WHR': 'Whirlpool', 'MAS': 'Masco',
    # USA — Retail (XRT)
    'TGT': 'Target', 'KSS': "Kohl's", 'ROST': 'Ross Stores',
    'DG': 'Dollar General', 'DLTR': 'Dollar Tree',
    
    # IT — Banche EU (EXV1.DE)
    'ISP.MI': 'Intesa Sanpaolo', 'UCG.MI': 'UniCredit', 'BAMI.MI': 'Banco BPM',
    'BMPS.MI': 'Monte dei Paschi', 'MB.MI': 'Mediobanca', 'BPSO.MI': 'BPER Sondrio',
    'BPER.MI': 'BPER Banca', 'FBK.MI': 'FinecoBank',
    # IT — Energia (EXH1.DE)
    'ENI.MI': 'Eni', 'SRG.MI': 'Snam', 'TEN.MI': 'Tenaris',
    'HER.MI': 'Hera', 'A2A.MI': 'A2A',
    # IT — Assicurazioni (EXH5.DE)
    'G.MI': 'Generali', 'UNI.MI': 'Unipol', 'PST.MI': 'Poste Italiane',
    # IT — Industriali (EXH4.DE)
    'PRY.MI': 'Prysmian', 'LDO.MI': 'Leonardo', 'CNHI.MI': 'CNH Industrial',
    'IP.MI': 'Interpump', 'DAN.MI': 'Danieli', 'AVIO.MI': 'Avio',
    'WBD.MI': 'Webuild', 'BZU.MI': 'Buzzi',
    # IT — Consumer Discretionary (EXH6.DE)
    'MONC.MI': 'Moncler', 'BC.MI': 'Brunello Cucinelli', 'TPRO.MI': 'Technoprobe',
    'FCT.MI': 'Ferretti', 'RACE.MI': 'Ferrari',
    # IT — Auto (EXV5.DE)
    'STLAM.MI': 'Stellantis', 'BRE.MI': 'Brembo', 'PIRC.MI': 'Pirelli',
    'IVG.MI': 'Iveco',
    # IT — Tech (EXV3.DE)
    'STM.MI': 'STMicroelectronics', 'REY.MI': 'Reply', 'TXT.MI': 'TXT e-solutions',
    'DEA.MI': 'DeA Capital',
    # IT — Telecom (EXV2.DE)
    'TIT.MI': 'Telecom Italia', 'INW.MI': 'Inwit',
    # IT — Salute (EXV4.DE)
    'REC.MI': 'Recordati', 'DIA.MI': 'Diasorin', 'AMP.MI': 'Amplifon', 'GVS.MI': 'GVS',
    # IT — Food (EXH7.DE)
    'CPR.MI': 'Davide Campari', 'DLG.MI': 'De\'Longhi',
    # IT — Media (EXH8.DE)
    'MN.MI': 'Mondadori', 'MFEA.MI': 'MFE-MediaForEurope A', 'RCS.MI': 'RCS MediaGroup',
    'CAI.MI': 'Cairo Communication',
    # IT — Utilities (EXH9.DE)
    'ENEL.MI': 'Enel', 'TRN.MI': 'Terna', 'IG.MI': 'Italgas',
    # IT — Asset Management (EXH3.DE)
    'BGN.MI': 'Banca Generali', 'AZM.MI': 'Azimut',
    # IT — Servizi (EXV7.DE / EXV9.DE)
    'ECNL.MI': 'Eurocom Net Logic', 'MARR.MI': 'MARR',
}

# ============================================================
# SISTEMA OPERATIVO: stessi 9 settori di update_data.py (SECTORS_TS_OFF)
# Solo questi settori generano segnali operativi e quindi operazioni.
# Gli altri 24 settori sono "INFO_ONLY": niente operazioni nel backtest.
# ============================================================
SECTORS_SYSTEM = (
    'XLK', 'SOXX', 'XLF', 'XLV', 'XLI', 'XLP', 'XLE',  # USA (7)
    'EXV1.DE', 'EXH5.DE',                               # EU (2)
)


def is_operational_in_base(state, stage):
    """
    REGOLA NO_BAD BASE: stessa di update_data.py · matrice 4×4.
    
                       Fase 1   Fase 2   Fase 3   Fase 4
    Leader             IN       IN       IN       OUT
    Emergente          IN       IN       IN       OUT
    In rallentamento   IN       IN       IN       OUT
    Debole             OUT      OUT      OUT      OUT
    
    OUT solo se stato == 'Debole' OPPURE stage == '4'.
    "In rallentamento" è considerato IN (è un buffer prima dell'uscita).
    """
    if state == 'Debole':
        return False
    if stage == '4':
        return False
    return state in ('Leader', 'Emergente', 'In rallentamento') and stage in ('1', '2', '3')


def fetch_all_prices(start=BACKTEST_START):
    all_tickers = set()
    for tks in US_UNIVERSE.values():
        all_tickers.update(tks)
    for tks in IT_UNIVERSE.values():
        all_tickers.update(tks)
    all_tickers.update(US_SECTORS_ETF)
    all_tickers.update(EU_SECTORS_ETF)
    all_tickers.update([US_BENCHMARK, EU_BENCHMARK, CASH_TICKER, WORLD_TICKER])
    all_tickers = sorted(all_tickers)
    print(f"\n[FETCH] Scarico {len(all_tickers)} ticker da {start}...")
    df = yf.download(all_tickers, start=start, interval='1wk',
                     auto_adjust=True, progress=False,
                     group_by='ticker', threads=True)
    if df.empty:
        return pd.DataFrame()
    if len(all_tickers) == 1:
        close = df[['Close']].rename(columns={'Close': all_tickers[0]})
    else:
        try:
            close = df.xs('Close', level=1, axis=1)
        except KeyError:
            close = df['Close']
    close = close.dropna(how='all')
    # Allinea l'indice al VENERDÌ (close della settimana) — stesso comportamento di update_data.py
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    close = close.resample('W-FRI').last().dropna(how='all')
    
    # PRIMA del rimapping ai trading days: scarta le settimane con W-FRI label > oggi.
    # Esempio: oggi è giovedì 04/06 → la W-FRI 05/06 è ancora futura (mercato non ha chiuso il venerdì)
    # → quella settimana NON deve essere inclusa nel backtest, perché il prezzo è intra-settimana.
    # Includiamo solo settimane il cui venerdì è già passato (o è oggi se è venerdì).
    today = pd.Timestamp.now().normalize()
    mask_completed = close.index <= today
    n_future = (~mask_completed).sum()
    if n_future > 0:
        last_future = close.index[-1]
        print(f"[FETCH] Scarto {n_future} settimana/e in corso (W-FRI > oggi): ultima = {last_future.date()}")
        close = close[mask_completed]
    
    # Ri-etichetta l'indice all'ULTIMO GIORNO EFFETTIVO DI TRADING della settimana,
    # combinando i calendari USA (SPY) e IT (ENI.MI). Una settimana viene etichettata
    # all'ultimo giorno in cui ALMENO UNA delle due borse era aperta.
    # Esempi:
    #   - Good Friday (USA e IT entrambe chiuse) → settimana mappata a giovedì
    #   - 1 maggio venerdì (IT chiusa, USA aperta) → settimana mappata a venerdì
    #   - 4 luglio venerdì (USA chiusa, IT aperta) → settimana mappata a venerdì
    print("[FETCH] Allineo date all'ultimo giorno di trading USA o IT (unione calendari)...")
    try:
        # Calendario USA (SPY) + Calendario IT (ENI.MI super liquido)
        cal_usa = yf.download(US_BENCHMARK, start=start, interval='1d',
                              auto_adjust=True, progress=False)
        cal_it = yf.download('ENI.MI', start=start, interval='1d',
                             auto_adjust=True, progress=False)
        
        def normalize_idx(df):
            if df.empty: return pd.DatetimeIndex([])
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            col = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
            return col.dropna().index if hasattr(col, 'dropna') else col.index
        
        usa_dates = set(normalize_idx(cal_usa))
        it_dates = set(normalize_idx(cal_it))
        # Unione: settimana è aperta se almeno una delle due borse ha trading quel giorno
        union_dates = sorted(usa_dates | it_dates)
        
        if union_dates:
            union_series = pd.Series(1, index=pd.DatetimeIndex(union_dates))
            last_td_per_week = (union_series.groupby(pd.Grouper(freq='W-FRI'))
                                            .apply(lambda x: x.index.max() if len(x) > 0 else pd.NaT))
            mapping = {fri: ltd for fri, ltd in last_td_per_week.items() if pd.notna(ltd)}
            new_index = [mapping.get(d, d) for d in close.index]
            
            shifted = sum(1 for orig, new in zip(close.index, new_index)
                          if new != orig)
            close.index = pd.DatetimeIndex(new_index)
            print(f"[FETCH] ✓ Calendari: USA {len(usa_dates)} giorni, IT {len(it_dates)} giorni, "
                  f"unione {len(union_dates)} giorni. Settimane shiftate: {shifted}")
    except Exception as e:
        print(f"[FETCH] ⚠ Impossibile rimappare festivi (uso venerdì calendario): {e}")
    
    missing = [t for t in all_tickers if t not in close.columns]
    if missing:
        print(f"[FETCH] ⚠ Mancanti: {missing}")
    print(f"[FETCH] ✓ {close.shape[1]} ticker × {close.shape[0]} settimane (date = ultimo close effettivo)")
    return close


def calculate_rrg(symbol_prices, benchmark_prices, window=14):
    """
    Calcola RS-Ratio e RS-Momentum — STESSA FORMULA ESATTA di update_data.py.
    Critico replicare bit-for-bit perché i segnali settoriali dipendono da questa.
    """
    common = symbol_prices.dropna().index.intersection(benchmark_prices.dropna().index)
    if len(common) < window * 3:
        return None
    
    rs_raw = (symbol_prices.loc[common] / benchmark_prices.loc[common]) * 100
    
    # RS-Ratio: smoothing + normalizzazione
    rs_ratio = rs_raw.rolling(window=window).mean()
    rs_ratio_mean = rs_ratio.rolling(window=window * 4).mean()
    rs_ratio_std = rs_ratio.rolling(window=window * 4).std()
    rs_ratio_norm = 100 + (rs_ratio - rs_ratio_mean) / rs_ratio_std.replace(0, 1) * 5
    
    # RS-Momentum: rate of change del RS-Ratio normalizzato
    rs_mom_raw = rs_ratio_norm.pct_change(periods=window // 2) * 100 + 100
    rs_mom = rs_mom_raw.rolling(window=window // 2).mean()
    
    return pd.DataFrame({'rsRatio': rs_ratio_norm, 'rsMom': rs_mom}).dropna()


def classify_quadrant(rs, mom):
    """STESSA FORMULA di update_data.py."""
    if pd.isna(rs) or pd.isna(mom):
        return 'Debole'
    if rs >= 100 and mom >= 100: return 'Leader'
    if rs <  100 and mom >= 100: return 'Emergente'
    if rs >= 100 and mom <  100: return 'In rallentamento'
    return 'Debole'


def classify_state(rs_ratio, rs_mom):
    """Alias per compatibilità."""
    return classify_quadrant(rs_ratio, rs_mom)


def extract_signal_history_full(rrg_df, prices, ma_weeks=30):
    """
    Per ogni settimana di rrg_df: calcola state + stage + segnale IN/OUT.
    Restituisce una lista di periodi consecutivi con stesso segnale.
    STESSA logica di extract_signal_history di update_data.py.
    """
    if rrg_df is None or len(rrg_df) == 0 or prices is None or len(prices) == 0:
        return []
    
    common = rrg_df.index.intersection(prices.dropna().index)
    if len(common) < 10:
        return []
    
    valid_prices = prices.dropna()
    ma_series = valid_prices.rolling(window=ma_weeks).mean()
    
    weekly_records = []
    for date in common:
        rs = rrg_df.loc[date, 'rsRatio']
        mom = rrg_df.loc[date, 'rsMom']
        state = classify_quadrant(rs, mom)
        
        try:
            price_at_date = valid_prices.loc[date]
            ma_at_date = ma_series.loc[date] if date in ma_series.index else None
        except Exception:
            continue
        
        if ma_at_date is None or pd.isna(ma_at_date):
            stage = '—'
        else:
            idx_pos = valid_prices.index.get_loc(date) if date in valid_prices.index else None
            if idx_pos is not None and idx_pos >= 5:
                ma_5w_ago = ma_series.iloc[idx_pos - 5]
            else:
                ma_5w_ago = ma_at_date
            slope_up = ma_at_date > ma_5w_ago
            above_ma = price_at_date > ma_at_date
            if above_ma and slope_up:           stage = '2'
            elif above_ma and not slope_up:     stage = '3'
            elif not above_ma and not slope_up: stage = '4'
            else:                               stage = '1'
        
        signal_in = is_operational_in_base(state, stage)
        weekly_records.append({
            'date': date,
            'state': state,
            'stage': stage,
            'in': signal_in,
        })
    
    if not weekly_records:
        return []
    
    # Raggruppa in periodi consecutivi (questo è cruciale: 1 periodo IN = 1 operazione)
    periods = []
    current = {
        'signal': 'IN' if weekly_records[0]['in'] else 'OUT',
        'start_date': weekly_records[0]['date'],
        'end_date': weekly_records[0]['date'],
        'start_state': weekly_records[0]['state'],
        'start_stage': weekly_records[0]['stage'],
        'end_state': weekly_records[0]['state'],
        'end_stage': weekly_records[0]['stage'],
    }
    for rec in weekly_records[1:]:
        sig = 'IN' if rec['in'] else 'OUT'
        if sig == current['signal']:
            current['end_date'] = rec['date']
            current['end_state'] = rec['state']
            current['end_stage'] = rec['stage']
        else:
            periods.append(current)
            current = {
                'signal': sig,
                'start_date': rec['date'],
                'end_date': rec['date'],
                'start_state': rec['state'],
                'start_stage': rec['stage'],
                'end_state': rec['state'],
                'end_stage': rec['stage'],
            }
    periods.append(current)
    return periods


def compute_roc(series, weeks):
    if len(series) < weeks + 1: return None
    last = series.iloc[-1]
    past = series.iloc[-(weeks + 1)]
    if pd.isna(past) or pd.isna(last) or past == 0: return None
    return round((last / past - 1) * 100, 2)


def classify_stage(series, ma_weeks=30):
    if len(series) < ma_weeks + 5: return '1'
    ma = series.rolling(ma_weeks).mean()
    last_price = series.iloc[-1]
    last_ma = ma.iloc[-1]
    slope = ma.iloc[-1] - ma.iloc[-5]
    if pd.isna(last_ma) or pd.isna(slope): return '1'
    above = last_price > last_ma
    rising = slope > 0
    if above and rising: return '2'
    if above and not rising: return '3'
    if not above and not rising: return '4'
    return '1'


def assign_tag(roc13, roc52):
    if roc13 is None: return None
    roc52 = roc52 or 0
    if roc13 > 25: return 'top_momentum'
    if 10 < roc13 <= 25 and roc52 < roc13 * 2: return 'value_momentum'
    if 5 < roc13 <= 25 and roc52 > 30: return 'premium_ok'
    if roc13 < -15: return 'value_trap'
    if -5 <= roc13 <= 5 and roc52 > 40: return 'expensive_flat'
    if -10 <= roc13 <= 10: return 'stagnant'
    return None


def composite_score(roc4, roc13, roc52, mode='balanced'):
    """
    Calcola lo score composito per la selezione azione.
    
    Mode:
      - balanced (default): ROC13 × 0.6 + ROC52 × 0.4
        Equilibrio tra momentum recente (3 mesi) e lungo (1 anno)
      - aggressive: ROC4 × 0.7 + ROC13 × 0.3
        Premia il momentum del MESE (ROC 4 settimane): cattura i rally più freschi.
        Sceglie ticker che stanno correndo ADESSO, non quelli stabilmente sopra.
    """
    if mode == 'aggressive':
        return (roc4 or 0) * 0.7 + (roc13 or 0) * 0.3
    return (roc13 or 0) * 0.6 + (roc52 or 0) * 0.4


def select_best_at_week(sector_etf, prices_df, w_idx, universe, mode='balanced'):
    candidates = universe.get(sector_etf, [])
    if not candidates: return None
    scored = []
    for tk in candidates:
        if tk not in prices_df.columns: continue
        s = prices_df[tk].iloc[:w_idx + 1].dropna()
        if len(s) < 14: continue
        roc4 = compute_roc(s, 4)    # NUOVO: momentum mensile per Aggressive
        roc13 = compute_roc(s, 13)
        roc52 = compute_roc(s, 52)
        tag = assign_tag(roc13, roc52)
        sc = composite_score(roc4, roc13, roc52, mode)
        scored.append({'ticker': tk, 'roc4': roc4, 'roc13': roc13, 'roc52': roc52, 'tag': tag, 'score': sc})
    if not scored: return None
    
    if mode == 'aggressive':
        # Aggressive: filtro più permissivo (basato su ROC4w > 0)
        # Cerca chi sta correndo ADESSO, indipendentemente dal tag long-term
        rising = [s for s in scored if (s['roc4'] or 0) > 0 and s['tag'] not in DISQUALIFYING_TAGS]
        if rising:
            rising.sort(key=lambda x: x['score'], reverse=True)
            return rising[0]
        # Fallback: chiunque con score positivo
        any_pos = [s for s in scored if s['score'] > 0]
        if any_pos:
            any_pos.sort(key=lambda x: x['score'], reverse=True)
            return any_pos[0]
        return None
    
    # Balanced: tutti i tag positivi
    positives = [s for s in scored if s['tag'] in POSITIVE_TAGS]
    if positives:
        positives.sort(key=lambda x: x['score'], reverse=True)
        return positives[0]
    # Fallback finale: non disqualifying con score > 0
    fallback = [s for s in scored if s['tag'] not in DISQUALIFYING_TAGS and s['score'] > 0]
    if fallback:
        fallback.sort(key=lambda x: x['score'], reverse=True)
        return fallback[0]
    return None


def run_backtest(prices, sector_etfs, mode='balanced'):
    """
    Backtest event-driven basato sui periodi IN/OUT dei settori.
    
    Mode:
      - balanced: selezione equilibrata (ROC13×0.6 + ROC52×0.4, tutti i tag positivi)
      - aggressive: selezione momentum-only (ROC13×0.9 + ROC52×0.1, preferenza top_momentum)
    
    La logica di compra/vendi NON cambia tra le modalità: stessi 9 settori operativi,
    stessi periodi IN, stesse date di apertura/chiusura. Cambia SOLO la scelta dell'azione.
    """
    dates = prices.index
    n_weeks = len(dates)
    print(f"\n[BACKTEST·{mode.upper()}] {n_weeks} settimane ({dates[0].date()} → {dates[-1].date()})")
    print(f"[BACKTEST] Settori SECTORS_SYSTEM: {len(SECTORS_SYSTEM)} (gli altri sono INFO_ONLY)")
    
    # ============================================================
    # FASE 1: per ogni settore, estrai signal_history su tutta la storia
    # ============================================================
    sector_data = {}
    for sec in SECTORS_SYSTEM:
        if sec not in prices.columns:
            print(f"  [SKIP] {sec}: prezzo non disponibile")
            continue
        region = 'US' if sec in US_SECTORS_ETF else 'IT'
        bench_tk = US_BENCHMARK if region == 'US' else EU_BENCHMARK
        if bench_tk not in prices.columns:
            print(f"  [SKIP] {sec}: benchmark {bench_tk} non disponibile")
            continue
        
        sec_prices = prices[sec].dropna()
        bench_prices = prices[bench_tk].dropna()
        
        rrg = calculate_rrg(sec_prices, bench_prices, window=14)
        if rrg is None or rrg.empty:
            print(f"  [SKIP] {sec}: RRG vuoto")
            continue
        
        history = extract_signal_history_full(rrg, sec_prices, ma_weeks=30)
        in_periods = [p for p in history if p['signal'] == 'IN']
        print(f"  [{sec}] {SECTOR_NAMES.get(sec, sec)}: {len(in_periods)} periodi IN su {len(history)} totali")
        
        sector_data[sec] = {
            'region': region,
            'history': history,
            'in_periods': in_periods,
            'last_history_date': history[-1]['end_date'] if history else None,
        }
    
    # ============================================================
    # FASE 2: crea una operazione per ogni periodo IN
    # ============================================================
    operations = []
    last_data_date = dates[-1]
    
    for sec, data in sector_data.items():
        region = data['region']
        uni = US_UNIVERSE if region == 'US' else IT_UNIVERSE
        
        for period in data['in_periods']:
            start_date = period['start_date']
            end_date = period['end_date']
            
            # Trova indici nella df prezzi (start_date/end_date sono Timestamp da rrg index)
            try:
                start_idx = dates.get_loc(start_date)
            except KeyError:
                # Fallback: cerca data più vicina
                start_idx = dates.searchsorted(start_date)
                if start_idx >= n_weeks: continue
            try:
                end_idx = dates.get_loc(end_date)
            except KeyError:
                end_idx = dates.searchsorted(end_date)
                if end_idx >= n_weeks: end_idx = n_weeks - 1
            
            # Seleziona azione del momento all'inizio del periodo (in base alla modalità)
            best = select_best_at_week(sec, prices, start_idx, uni, mode=mode)
            if best is None:
                # Universo vuoto o nessun candidato qualificato
                continue
            
            tk = best['ticker']
            if tk not in prices.columns: continue
            
            entry_price = float(prices[tk].iloc[start_idx])
            exit_price = float(prices[tk].iloc[end_idx])
            if pd.isna(entry_price) or pd.isna(exit_price) or entry_price <= 0:
                continue
            
            # È "open" se il periodo IN finisce all'ultima data disponibile
            # (il segnale è ancora attivo, l'operazione non è stata chiusa)
            is_open = (end_date == last_data_date) or (end_idx == n_weeks - 1)
            
            perf = (exit_price / entry_price - 1) * 100
            weeks_held = end_idx - start_idx + 1
            
            operations.append({
                'sector_etf': sec,
                'sector_name': SECTOR_NAMES.get(sec, sec),
                'region': region,
                'ticker': tk,
                'entry_date': str(start_date.date()) if hasattr(start_date, 'date') else str(start_date)[:10],
                'exit_date': None if is_open else (str(end_date.date()) if hasattr(end_date, 'date') else str(end_date)[:10]),
                'entry_price': round(entry_price, 4),
                'exit_price': round(exit_price, 4),
                'perf_pct': round(perf, 2),
                'weeks_held': weeks_held,
                'status': 'open' if is_open else 'closed',
                'entry_tag': best['tag'],
                'entry_state': period['start_state'],
                'entry_stage': period['start_stage'],
                'exit_state': period['end_state'],
                'exit_stage': period['end_stage'],
                '_start_idx': start_idx,
                '_end_idx': end_idx,
            })
    
    print(f"\n[BACKTEST] Generate {len(operations)} operazioni totali ({sum(1 for o in operations if o['status']=='closed')} chiuse, {sum(1 for o in operations if o['status']=='open')} aperte)")
    
    # ============================================================
    # FASE 3: costruisci equity curve settimanale aggregando operazioni
    # ============================================================
    portfolio = 100.0
    cash_v = 100.0
    world_v = 100.0
    cash_series = prices[CASH_TICKER] if CASH_TICKER in prices.columns else None
    world_series = prices[WORLD_TICKER] if WORLD_TICKER in prices.columns else None
    
    equity_curve = []
    
    # Trova prima settimana che vede almeno un'operazione aperta
    if operations:
        start_w = max(56, min(op['_start_idx'] for op in operations))
    else:
        start_w = 56  # almeno 56 settimane per il calcolo RRG window*4
    
    for w in range(start_w, n_weeks):
        date = dates[w]
        
        # Rendimento settimanale: posizioni attive all'inizio della settimana w
        # (entrate <= w-1 E uscita >= w-1 → posizione ancora in portfolio inizio settimana).
        # Ogni posizione pesa SEMPRE 1/N_MAX (= 1/9 = 11.1%). Il resto va in CASH.
        # Rendimento portfolio = Σ(pos_ret × 1/N) + cash_ret × (N - n_active)/N
        N_MAX = len(SECTORS_SYSTEM)  # 9 settori operativi totali
        if w > start_w:
            active_at_open = [
                op for op in operations
                if op['_start_idx'] <= w - 1 and op['_end_idx'] >= w - 1
            ]
            
            # Calcolo cash_ret della settimana (sempre, indipendentemente da n_active)
            cash_ret_week = 0.0
            if cash_series is not None and w < len(cash_series):
                pc = cash_series.iloc[w - 1]
                cc = cash_series.iloc[w]
                if not pd.isna(pc) and not pd.isna(cc) and pc > 0:
                    cash_ret_week = (cc / pc - 1)
                    cash_v *= (cc / pc)
            
            # Calcolo rendimenti delle posizioni attive (somma)
            pos_sum_ret = 0.0
            n_valid = 0
            for op in active_at_open:
                tk = op['ticker']
                if tk not in prices.columns: continue
                pp = prices[tk].iloc[w - 1]
                cp = prices[tk].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp == 0: continue
                pos_sum_ret += (cp / pp - 1)
                n_valid += 1
            
            # Aggregato: Σ(pos × 1/N) + cash × (N - n_valid)/N
            week_ret = (pos_sum_ret / N_MAX) + cash_ret_week * (N_MAX - n_valid) / N_MAX
            portfolio *= (1 + week_ret)
            
            # World benchmark
            if world_series is not None and w < len(world_series):
                pw = world_series.iloc[w - 1]
                cw = world_series.iloc[w]
                if not pd.isna(pw) and not pd.isna(cw) and pw > 0:
                    world_v *= (cw / pw)
        
        # Conta posizioni attive in questa settimana per il display
        active_now = [op for op in operations if op['_start_idx'] <= w <= op['_end_idx']]
        
        # Calcolo pos_ret_sum della settimana (per ricalcolo on-the-fly con cash rate custom nel JS)
        pos_ret_sum_w = 0.0
        n_active_w = 0
        if w > start_w:
            active_at_open_for_export = [
                op for op in operations
                if op['_start_idx'] <= w - 1 and op['_end_idx'] >= w - 1
            ]
            for op in active_at_open_for_export:
                tk = op['ticker']
                if tk not in prices.columns: continue
                pp = prices[tk].iloc[w - 1]
                cp = prices[tk].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp == 0: continue
                pos_ret_sum_w += (cp / pp - 1)
                n_active_w += 1
        
        equity_curve.append({
            'date': str(date.date()),
            'system': round(portfolio, 4),
            'cash': round(cash_v, 4),
            'world': round(world_v, 4),
            'n_positions': len(active_now),
            'pos_ret_sum': round(pos_ret_sum_w, 6),
            'n_active_for_ret': n_active_w,
        })
    
    # Posizioni attualmente aperte (per il rendering dashboard)
    current_pins = {}
    for op in operations:
        if op['status'] == 'open':
            current_pins[op['sector_etf']] = {
                'ticker': op['ticker'],
                'entry_date': op['entry_date'],
                'entry_price': op['entry_price'],
                'weeks_held': op['weeks_held'],
                'region': op['region'],
                'entry_tag': op.get('entry_tag'),
                'entry_state': op.get('entry_state'),
                'entry_stage': op.get('entry_stage'),
            }
    
    # Rimuovi campi interni prima del salvataggio
    for op in operations:
        op.pop('_start_idx', None)
        op.pop('_end_idx', None)
    
    return {'equity_curve': equity_curve, 'operations': operations, 'current_pins': current_pins}


def compute_statistics(equity, operations):
    if not equity: return {}
    values = [e['system'] for e in equity]
    cash_v = [e['cash'] for e in equity]
    world_v = [e['world'] for e in equity]
    initial = values[0]
    final = values[-1]
    total_ret = (final / initial - 1) * 100
    n_years = len(values) / 52
    cagr = ((final / initial) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak: peak = v
        dd = (v / peak - 1) * 100
        if dd < max_dd: max_dd = dd
    
    rets = pd.Series(values).pct_change().dropna()
    if len(rets) > 1:
        annual_vol = rets.std() * np.sqrt(52)
        ann_ret = (1 + rets.mean()) ** 52 - 1
        sharpe = (ann_ret - SHARPE_RF) / annual_vol if annual_vol > 0 else 0
    else:
        annual_vol = sharpe = 0
    
    closed = [op for op in operations if op['status'] == 'closed']
    n_closed = len(closed)
    if n_closed > 0:
        wins = [op for op in closed if op['perf_pct'] > 0]
        losses = [op for op in closed if op['perf_pct'] <= 0]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = n_wins / n_closed * 100
        avg_gain = np.mean([op['perf_pct'] for op in wins]) if wins else 0
        avg_loss = np.mean([op['perf_pct'] for op in losses]) if losses else 0
        avg_perf = np.mean([op['perf_pct'] for op in closed])
        pl_ratio = abs(avg_gain / avg_loss) if avg_loss != 0 else None
        best = max(closed, key=lambda x: x['perf_pct'])
        worst = min(closed, key=lambda x: x['perf_pct'])
    else:
        win_rate = avg_gain = avg_loss = avg_perf = 0
        n_wins = n_losses = 0
        pl_ratio = None
        best = worst = None
    
    return {
        'total_return': round(total_ret, 2),
        'cagr': round(cagr, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'annual_vol': round(annual_vol * 100, 2),
        'n_operations_total': len(operations),
        'n_operations_closed': n_closed,
        'n_operations_open': len([op for op in operations if op['status'] == 'open']),
        'n_wins': n_wins, 'n_losses': n_losses,
        'win_rate': round(win_rate, 2),
        'avg_gain': round(avg_gain, 2),
        'avg_loss': round(avg_loss, 2),
        'avg_perf_per_trade': round(avg_perf, 2),
        'profit_loss_ratio': round(pl_ratio, 2) if pl_ratio else None,
        'best_operation': {
            'ticker': best['ticker'], 'sector': best['sector_name'],
            'perf_pct': best['perf_pct'],
        } if best else None,
        'worst_operation': {
            'ticker': worst['ticker'], 'sector': worst['sector_name'],
            'perf_pct': worst['perf_pct'],
        } if worst else None,
        'cash_total_return': round((cash_v[-1] / cash_v[0] - 1) * 100, 2) if cash_v else 0,
        'world_total_return': round((world_v[-1] / world_v[0] - 1) * 100, 2) if world_v else 0,
        'weeks_simulated': len(equity),
    }


def build_mode_output(prices, sector_etfs, mode):
    """Esegue un backtest per la modalità data e ritorna la struttura completa."""
    result = run_backtest(prices, sector_etfs, mode=mode)
    stats = compute_statistics(result['equity_curve'], result['operations'])
    last_date = result['equity_curve'][-1]['date'] if result['equity_curve'] else None
    
    # Posizioni aperte attuali con indicatori freschi
    current_list = []
    for sec, pin in result['current_pins'].items():
        tk = pin['ticker']
        if tk not in prices.columns: continue
        s = prices[tk].dropna()
        if s.empty: continue
        cp = float(s.iloc[-1])
        roc13 = compute_roc(s, 13)
        roc52 = compute_roc(s, 52)
        stage = classify_stage(s)
        perf = (cp / pin['entry_price'] - 1) * 100 if pin['entry_price'] > 0 else 0
        current_list.append({
            'sector_etf': sec, 'sector_name': SECTOR_NAMES.get(sec, sec),
            'region': pin['region'], 'ticker': tk,
            'entry_date': pin['entry_date'],
            'entry_price': round(pin['entry_price'], 4),
            'current_price': round(cp, 4),
            'perf_pct': round(perf, 2),
            'weeks_held': pin['weeks_held'],
            'roc13w': roc13, 'roc52w': roc52,
            'stage': stage, 'tag': assign_tag(roc13, roc52),
        })
    
    buys = [op for op in result['operations'] if op.get('entry_date') == last_date and op['status'] == 'open']
    sells = [op for op in result['operations'] if op.get('exit_date') == last_date and op['status'] == 'closed']
    
    print(f"\n[MODE·{mode.upper()}] Riepilogo:")
    print(f"  Total Return: {stats.get('total_return', 0):+.2f}%")
    print(f"  CAGR: {stats.get('cagr', 0):+.2f}%")
    print(f"  Sharpe: {stats.get('sharpe', 0):.2f}")
    print(f"  Max DD: {stats.get('max_drawdown', 0):.2f}%")
    print(f"  Operazioni: {stats.get('n_operations_total', 0)} ({stats.get('n_operations_closed', 0)} chiuse + {stats.get('n_operations_open', 0)} aperte)")
    print(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
    
    return {
        'stats': stats,
        'equity_curve': result['equity_curve'],
        'operations': sorted(result['operations'],
                             key=lambda x: x.get('exit_date') or x.get('entry_date') or '',
                             reverse=True),
        'current_positions': sorted(current_list, key=lambda x: x['perf_pct'], reverse=True),
        'weekly_moves': {'buys': buys, 'sells': sells, 'date': last_date},
    }


def main():
    print("=" * 70)
    print("MEGATREND SENTINEL STOCKS · v3 Multi-Mode Backtest")
    print("=" * 70)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Backtest start: {BACKTEST_START}")
    
    prices = fetch_all_prices()
    if prices.empty:
        print("ERROR: nessun dato")
        sys.exit(1)
    
    sector_etfs = US_SECTORS_ETF + EU_SECTORS_ETF
    
    # Esegui backtest per ogni modalità
    modes_output = {}
    for mode in ['balanced', 'aggressive']:
        modes_output[mode] = build_mode_output(prices, sector_etfs, mode)
    
    last_date = modes_output['balanced']['weekly_moves']['date']
    
    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': last_date,
        'backtest_start': BACKTEST_START,
        'universe_size': {
            'us_stocks': sum(len(v) for v in US_UNIVERSE.values()),
            'it_stocks': sum(len(v) for v in IT_UNIVERSE.values()),
            'us_sectors': len(US_SECTORS_ETF),
            'eu_sectors': len(EU_SECTORS_ETF),
        },
        'stock_names': STOCK_NAMES,
        'modes': modes_output,
        'benchmarks': {
            'cash': {'ticker': CASH_TICKER, 'name': 'XEON · €STR overnight'},
            'world': {'ticker': WORLD_TICKER, 'name': 'XDWD · MSCI World'},
            'us': {'ticker': US_BENCHMARK, 'name': 'S&P 500'},
            'eu': {'ticker': EU_BENCHMARK, 'name': 'STOXX 600'},
        },
    }
    
    DATA_DIR.mkdir(exist_ok=True)
    with open(STOCKS_DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n{'=' * 70}")
    print("RIEPILOGO COMPLESSIVO")
    print(f"{'=' * 70}")
    for mode in ['balanced', 'aggressive']:
        s = modes_output[mode]['stats']
        print(f"{mode.upper():12s} | CAGR {s.get('cagr', 0):+.2f}% | Sharpe {s.get('sharpe', 0):.2f} | MDD {s.get('max_drawdown', 0):.2f}% | Op {s.get('n_operations_total', 0)}")
    print(f"\n✓ Output: {STOCKS_DATA_JSON}")


if __name__ == '__main__':
    main()
