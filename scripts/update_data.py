"""
Megatrend Sentinel ETF · Data Update
=====================================
Genera data/sector_data.json con:
- 13 settori (3 USA + 10 EU) — solo investibili a Milano
- Classifica di forza con ranking + delta vs snapshot precedente
- Info ETF Borsa Italiana per ogni settore

Workflow giornaliero alle 15:00 UTC (≈ 17:00 italiana).
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# UNIVERSO ETF — solo settori con ETF liquido a Borsa Italiana
# ============================================================
US_BENCHMARK = 'SPY'
US_SECTORS = {
    'XLK':     'Tecnologia USA',
    'SOXX':    'Semiconduttori',
    'IBB':     'Biotech',
    'XLF':     'Finanziari USA',
    'XLV':     'Sanità USA',
    'XLI':     'Industriali USA',
    'XLP':     'Beni di consumo difensivi',
    'XLE':     'Energia USA',
}

EU_BENCHMARK = 'EXSA.DE'
EU_SECTORS = {
    'EXV1.DE': 'Banche',
    'EXH1.DE': 'Energia',
    'EXH5.DE': 'Assicurazioni',
    'EXH4.DE': 'Industriali',
    'EXH6.DE': 'Beni personali',
}

# Cash benchmark: XEON.DE (Xtrackers II EUR Overnight Rate Swap UCITS ETF)
# ISIN LU0290358497, lanciato 23/05/2007. Replica €STR (ex-EONIA pre-2019).
# Duration zero, oscillazione prezzo ~0%, rendimento puro overnight EUR.
# Usato nel backtest per simulare il rendimento del cash durante i periodi OUT.
CASH_TICKER = 'XEON.DE'
CASH_TICKER_SHORT = 'XEON'
CASH_ISIN = 'LU0290358497'

# World benchmark: XDWD.DE (Xtrackers MSCI World UCITS ETF 1C)
# ISIN IE00BJ0KDQ92, lanciato 12/12/2006. MSCI World total return in EUR non-hedged.
# Usato in dashboard come terza curva di confronto contro Sistema e B&H equipesato.
# Più universale del B&H equipesato sui medesimi settori (che è un benchmark auto-bias).
WORLD_TICKER = 'XDWD.DE'
WORLD_TICKER_SHORT = 'XDWD'
WORLD_ISIN = 'IE00BJ0KDQ92'

# ============================================================
# ETF Info Borsa Italiana per ogni settore monitorato
# ============================================================
ETF_INFO = {
    'XLK': {
        'isin': 'IE00B3WJKG14',
        'name': 'iShares S&P 500 Information Technology Sector UCITS ETF',
        'ticker_short': 'IUIT',
        'ter': 0.15, 'aum_meur': 15457,
        'index': 'S&P 500 Capped 35/20 Information Technology',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    'SOXX': {
        'isin': 'IE00BMC38736',
        'name': 'VanEck Semiconductor UCITS ETF',
        'ticker_short': 'SMH',
        'ter': 0.35, 'aum_meur': 6297,
        'index': 'MarketVector US Listed Semiconductor 10% Capped',
        'issuer': 'VanEck',
        'replication': 'fisica', 'currency': 'USD',
    },
    'IBB': {
        'isin': 'IE00BYXG2H39',
        'name': 'iShares Nasdaq US Biotechnology UCITS ETF',
        'ticker_short': 'BTEC',
        'ter': 0.35, 'aum_meur': 779,
        'index': 'Nasdaq Biotechnology',
        'issuer': 'iShares',
        'replication': 'campionamento', 'currency': 'USD',
    },
    'XLF': {
        'isin': 'IE00B4JNQZ49',
        'name': 'iShares S&P 500 Financials Sector UCITS ETF',
        'ticker_short': 'IUFS',
        'ter': 0.15, 'aum_meur': 1500,
        'index': 'S&P 500 Capped 35/20 Financials',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    'XLV': {
        'isin': 'IE00B43HR379',
        'name': 'iShares S&P 500 Health Care Sector UCITS ETF',
        'ticker_short': 'IUHC',
        'ter': 0.15, 'aum_meur': 2500,
        'index': 'S&P 500 Capped 35/20 Health Care',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    'XLI': {
        'isin': 'IE00B4LN9N13',
        'name': 'iShares S&P 500 Industrials Sector UCITS ETF',
        'ticker_short': 'IUIS',
        'ter': 0.15, 'aum_meur': 500,
        'index': 'S&P 500 Capped 35/20 Industrials',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    'XLP': {
        'isin': 'IE00B40B8R38',
        'name': 'iShares S&P 500 Consumer Staples Sector UCITS ETF',
        'ticker_short': 'IUCS',
        'ter': 0.15, 'aum_meur': 600,
        'index': 'S&P 500 Capped 35/20 Consumer Staples',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    'XLE': {
        'isin': 'IE00B42NKQ00',
        'name': 'iShares S&P 500 Energy Sector UCITS ETF',
        'ticker_short': 'IUES',
        'ter': 0.15, 'aum_meur': 700,
        'index': 'S&P 500 Capped 35/20 Energy',
        'issuer': 'iShares',
        'replication': 'fisica totale', 'currency': 'USD',
    },
    # Europa · iShares STOXX 600 settoriali (quotati su ETFplus)
    'EXV1.DE': {
        'isin': 'DE000A0F5UJ7',
        'name': 'iShares STOXX Europe 600 Banks UCITS ETF (DE)',
        'ticker_short': 'EXV1',
        'ter': 0.47, 'aum_meur': 3465,
        'index': 'STOXX Europe 600 Banks',
        'issuer': 'iShares', 'replication': 'fisica', 'currency': 'EUR',
    },
    'EXH1.DE': {
        'isin': 'DE000A0H08M3',
        'name': 'iShares STOXX Europe 600 Oil & Gas UCITS ETF (DE)',
        'ticker_short': 'EXH1',
        'ter': 0.47, 'aum_meur': 900,
        'index': 'STOXX Europe 600 Oil & Gas',
        'issuer': 'iShares', 'replication': 'fisica', 'currency': 'EUR',
    },
    'EXH5.DE': {
        'isin': 'DE000A0H08K7',
        'name': 'iShares STOXX Europe 600 Insurance UCITS ETF (DE)',
        'ticker_short': 'EXH5',
        'ter': 0.47, 'aum_meur': 400,
        'index': 'STOXX Europe 600 Insurance',
        'issuer': 'iShares', 'replication': 'fisica', 'currency': 'EUR',
    },
    'EXH4.DE': {
        'isin': 'DE000A0H08J9',
        'name': 'iShares STOXX Europe 600 Industrial Goods & Services UCITS ETF (DE)',
        'ticker_short': 'EXH4',
        'ter': 0.47, 'aum_meur': 350,
        'index': 'STOXX Europe 600 Industrial Goods & Services',
        'issuer': 'iShares', 'replication': 'fisica', 'currency': 'EUR',
    },
    'EXH6.DE': {
        'isin': 'DE000A0H08N1',
        'name': 'iShares STOXX Europe 600 Personal & Household Goods UCITS ETF (DE)',
        'ticker_short': 'EXH6',
        'ter': 0.47, 'aum_meur': 250,
        'index': 'STOXX Europe 600 Personal & Household Goods',
        'issuer': 'iShares', 'replication': 'fisica', 'currency': 'EUR',
    },
}


# ============================================================
# MAPPATURA TICKER ETF EUROPEI per visualizzazione prezzi reali
# ============================================================
# Il backtest gira sui ticker SPDR USA (XLK, XLV, ecc.) perché hanno storia lunga
# dal 2008. I prezzi mostrati nelle tabelle (posizioni aperte, operazioni chiuse,
# movimenti settimana) provengono invece dagli ETF iShares UCITS effettivamente
# negoziati a Milano/Xetra in EUR. Per gli ETF EU (EXV1.DE, ecc.) usiamo gli
# stessi ticker del backtest perché sono già iShares europei.
# Se yfinance non ha dati EUR a una data (ETF non ancora quotato), uso il prezzo
# SPDR USA come fallback e segnalo la cosa con un flag.
ETF_EUR_TICKER_MAP = {
    # USA → ticker yfinance ETF iShares europei in EUR su Xetra (Deutsche Borse)
    # NB: usiamo .DE invece di .MI perché yfinance ha dati più affidabili su Xetra
    'XLK':  'QDVE.DE',   # iShares S&P 500 Information Technology
    'SOXX': 'SMH.DE',    # VanEck Semiconductor
    'IBB':  '2B76.DE',   # iShares Nasdaq US Biotechnology
    'XLF':  'QDVH.DE',   # iShares S&P 500 Financials
    'XLV':  'QDVG.DE',   # iShares S&P 500 Health Care
    'XLI':  'QDVI.DE',   # iShares S&P 500 Industrials
    'XLP':  'QDVS.DE',   # iShares S&P 500 Consumer Staples
    'XLE':  'QDVF.DE',   # iShares S&P 500 Energy
    # EU → ticker uguale (sono già iShares europei in EUR su Xetra)
    'EXV1.DE': 'EXV1.DE',
    'EXH1.DE': 'EXH1.DE',
    'EXH5.DE': 'EXH5.DE',
    'EXH4.DE': 'EXH4.DE',
    'EXH6.DE': 'EXH6.DE',
}


# ============================================================
# DATA FETCHING
# ============================================================
def fetch_prices(tickers, period='2y'):
    """Bulk download con fallback per-ticker su yfinance."""
    if isinstance(tickers, str):
        tickers = [tickers]
    
    try:
        data = yf.download(tickers, period=period, interval='1wk', 
                          auto_adjust=True, progress=False, group_by='ticker',
                          threads=True)
        if data.empty:
            raise ValueError("Empty dataframe")
        
        # Estrai Close da MultiIndex (group_by='ticker')
        if isinstance(data.columns, pd.MultiIndex):
            close_df = pd.DataFrame()
            for t in tickers:
                try:
                    if t in data.columns.get_level_values(0):
                        close_df[t] = data[t]['Close']
                except Exception:
                    continue
            data = close_df
        else:
            # Single ticker case
            if 'Close' in data.columns:
                data = data[['Close']].rename(columns={'Close': tickers[0]})
        
        # Drop ticker con tutti NaN
        data = data.dropna(axis=1, how='all')
        
        # Fallback per ticker mancanti
        missing = [t for t in tickers if t not in data.columns]
        for t in missing:
            try:
                single = yf.download(t, period=period, interval='1wk',
                                    auto_adjust=True, progress=False)
                if not single.empty and 'Close' in single.columns:
                    data[t] = single['Close']
                    print(f"  Fallback OK: {t}", file=sys.stderr)
            except Exception as e:
                print(f"  Fallback FAILED: {t} - {e}", file=sys.stderr)
        
        # Normalizza tz e index a date
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        
        # Forza il campionamento settimanale al venerdì (giorno di chiusura standard)
        # Garantisce coerenza tra esecuzioni a orari diversi del workflow.
        data = data.resample('W-FRI').last().dropna(how='all')
        
        # Escludi l'ultima settimana se NON è ancora chiusa (cioè se il venerdì di
        # riferimento è nel futuro rispetto a oggi). Evita di calcolare RRG su una
        # "settimana parziale" basata solo sui primi 1-2 giorni di trading.
        today = pd.Timestamp.now().normalize()
        if len(data) > 0 and data.index[-1] > today:
            data = data.iloc[:-1]
        
        return data.dropna(how='all')
    
    except Exception as e:
        print(f"ERRORE fetch_prices: {e}", file=sys.stderr)
        return pd.DataFrame()


def fetch_eur_prices_aligned(common_dates, period='10y'):
    """Scarica i prezzi ETF in EUR per la visualizzazione e li allinea sulle date
    settimanali del backtest. Restituisce un dict {ticker_raw_spdr: [prices...]}.
    
    Per ogni ticker SPDR USA del sistema, scarica il corrispondente ticker iShares EUR
    da Milano (es. XLK → IUIT.MI). Se yfinance non ha dati o l'ETF non era ancora
    quotato a una data, il valore è None.
    
    common_dates: lista di pd.Timestamp (date settimanali del backtest)
    Returns: dict {spdr_ticker: [float|None per ogni data]}
    """
    print("Fetching EUR prices for visualization...", file=sys.stderr)
    
    eur_tickers = list(set(ETF_EUR_TICKER_MAP.values()))
    result = {}
    
    try:
        data = yf.download(eur_tickers, period=period, interval='1wk',
                          auto_adjust=True, progress=False, group_by='ticker',
                          threads=True)
        
        # Estrai Close
        eur_prices_df = pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            for t in eur_tickers:
                try:
                    if t in data.columns.get_level_values(0):
                        eur_prices_df[t] = data[t]['Close']
                except Exception:
                    continue
        elif 'Close' in data.columns:
            eur_prices_df[eur_tickers[0]] = data['Close']
        
        # Drop tutti NaN
        eur_prices_df = eur_prices_df.dropna(axis=1, how='all')
        
        # Fallback per ticker mancanti
        for t in eur_tickers:
            if t not in eur_prices_df.columns:
                try:
                    single = yf.download(t, period=period, interval='1wk',
                                        auto_adjust=True, progress=False)
                    if not single.empty and 'Close' in single.columns:
                        eur_prices_df[t] = single['Close']
                        print(f"  EUR fallback OK: {t}", file=sys.stderr)
                except Exception as e:
                    print(f"  EUR fallback FAILED: {t} - {e}", file=sys.stderr)
        
        # Normalizza tz e resample al venerdì
        if eur_prices_df.index.tz is not None:
            eur_prices_df.index = eur_prices_df.index.tz_localize(None)
        eur_prices_df = eur_prices_df.resample('W-FRI').last()
        
    except Exception as e:
        print(f"ERRORE fetch_eur_prices_aligned: {e}", file=sys.stderr)
        return {spdr: [None] * len(common_dates) for spdr in ETF_EUR_TICKER_MAP.keys()}
    
    # Allinea sulle common_dates del backtest
    for spdr_ticker, eur_ticker in ETF_EUR_TICKER_MAP.items():
        aligned = []
        if eur_ticker in eur_prices_df.columns:
            series = eur_prices_df[eur_ticker]
            for d in common_dates:
                try:
                    p = series.loc[d]
                    if pd.isna(p):
                        aligned.append(None)
                    else:
                        aligned.append(float(round(p, 4)))
                except Exception:
                    aligned.append(None)
        else:
            aligned = [None] * len(common_dates)
        result[spdr_ticker] = aligned
        n_valid = sum(1 for p in aligned if p is not None)
        print(f"  EUR {spdr_ticker} → {eur_ticker}: {n_valid}/{len(aligned)} prezzi disponibili",
              file=sys.stderr)
    
    return result


def calculate_rrg(symbol_prices, benchmark_prices, window=14):
    """Calcola RS-Ratio e RS-Momentum (approssimazione JdK)."""
    common = symbol_prices.dropna().index.intersection(benchmark_prices.dropna().index)
    if len(common) < window * 3:
        return None
    
    rs_raw = (symbol_prices.loc[common] / benchmark_prices.loc[common]) * 100
    
    # RS-Ratio: smoothing + normalizzazione
    rs_ratio = rs_raw.rolling(window=window).mean()
    rs_ratio_mean = rs_ratio.rolling(window=window*4).mean()
    rs_ratio_std = rs_ratio.rolling(window=window*4).std()
    rs_ratio_norm = 100 + (rs_ratio - rs_ratio_mean) / rs_ratio_std.replace(0, 1) * 5
    
    # RS-Momentum: rate of change del RS-Ratio normalizzato
    rs_mom_raw = rs_ratio_norm.pct_change(periods=window//2) * 100 + 100
    rs_mom = rs_mom_raw.rolling(window=window//2).mean()
    
    return pd.DataFrame({'rsRatio': rs_ratio_norm, 'rsMom': rs_mom}).dropna()


def classify_quadrant(rs, mom):
    """Mappa RS,Mom in stato qualitativo."""
    if pd.isna(rs) or pd.isna(mom):
        return 'Debole'
    if rs >= 100 and mom >= 100: return 'Leader'
    if rs <  100 and mom >= 100: return 'Emergente'
    if rs >= 100 and mom <  100: return 'In rallentamento'
    return 'Debole'


def find_signal_dates(rrg_df, current_state, tolerance_weeks=3):
    """
    Trova la data di entrata nello stato corrente, con TOLLERANZA AI MICRO-RIMBALZI.
    
    Un segnale si considera "continuativo" anche se attraversa brevemente (≤3 settimane
    consecutive) uno stato diverso. Questo evita che oscillazioni statistiche di RS-Momentum
    attorno alla soglia 100 facciano "resettare" segnali di lungo periodo (es. un settore
    stabilmente sopra RS-Ratio 100 ma con RS-Mom che oscilla 99-101 non perde l'etichetta
    di Leader per una settimana isolata).
    
    Parametri:
        rrg_df: DataFrame con colonne rsRatio, rsMom
        current_state: stato corrente (Leader/Emergente/In rallentamento/Debole)
        tolerance_weeks: numero massimo di settimane consecutive in stato diverso che 
                         vengono "ignorate" come micro-rimbalzi (default 3)
    """
    if rrg_df is None or len(rrg_df) == 0:
        return None, None
    
    last_idx = len(rrg_df) - 1
    state_entry_idx = last_idx
    
    # Scorri indietro tenendo conto delle micro-rotture (tolleranza)
    consecutive_off = 0  # quante settimane consecutive in stato diverso
    
    for i in range(last_idx - 1, -1, -1):
        rs = rrg_df.iloc[i]['rsRatio']
        mom = rrg_df.iloc[i]['rsMom']
        observed_state = classify_quadrant(rs, mom)
        
        if observed_state == current_state:
            # Stato confermato → estendiamo l'entry indietro
            state_entry_idx = i
            consecutive_off = 0  # reset contatore micro-rotture
        else:
            consecutive_off += 1
            if consecutive_off > tolerance_weeks:
                # Troppe settimane consecutive in stato diverso → vera rottura
                # Il segnale è iniziato DOPO l'ultimo break confermato
                break
            # Altrimenti: questa è una micro-rottura, la ignoriamo e continuiamo a guardare indietro
    
    # signal_date: per ora uguale a state_entry (semplificazione)
    state_entry_date = rrg_df.index[state_entry_idx].strftime('%Y-%m-%d')
    signal_date = state_entry_date
    
    return state_entry_date, signal_date


def perf_since(prices, date_str):
    """Performance % di un asset da una data fino all'ultima disponibile."""
    if prices is None or len(prices) == 0:
        return None
    try:
        date = pd.to_datetime(date_str)
        if prices.index.tz is not None:
            prices = prices.copy()
            prices.index = prices.index.tz_localize(None)
        
        valid = prices.dropna()
        idx_after = valid.index[valid.index >= date]
        if len(idx_after) == 0:
            return None
        start_price = valid.loc[idx_after[0]]
        end_price = valid.iloc[-1]
        return float((end_price / start_price - 1) * 100)
    except Exception:
        return None


def weeks_between(date_str, end_date_str):
    """Numero di settimane tra due date."""
    try:
        d1 = pd.to_datetime(date_str)
        d2 = pd.to_datetime(end_date_str)
        return int((d2 - d1).days / 7)
    except Exception:
        return 0


## ============================================================
## CONFIGURAZIONE CLUSTER SISTEMA (calibrata su backtest 2010-2026)
## ============================================================
## Il sistema NO_BAD attivo solo sui settori dove statisticamente migliora
## il rapporto rendimento/rischio. Gli altri restano nella dashboard come
## INFO (stato + fase visibili, ma niente segnale operativo IN/OUT).
##
## Cluster TS6 (time-stop 6 settimane): SOXX, XLK, EXH6, EXV2
##   Settori trending: il sistema esce solo se dopo 6 settimane di posizione
##   il prezzo è ancora sotto entry * 0.99
##
## Cluster TS3 (time-stop 3 settimane): EXV1, EXH5, EXH4
##   Settori ciclici: time-stop più aggressivo, esce dopo 3 settimane
##
## INFO_ONLY: IBB, EXV3, EXH1, EXV4, EXV5, EXH9
##   Settori dove ogni regola sistema ha peggiorato i risultati vs B&H.
##   Mostrati nella dashboard ma senza segnale operativo.
## Cluster operativi:
##
## SECTORS_TS_OFF (default no time-stop): la regola NO_BAD pura, senza uscita
##   anticipata per time-stop. Più reattivo, lascia correre i trend.
##
## SECTORS_TS6 (time-stop 6 settimane): dopo 6 settimane in posizione, se prezzo
##   non è in guadagno → uscita anticipata.
##
## SECTORS_TS3 (time-stop 3 settimane): più aggressivo.
##
## Esclusi di default: EXH1 (Energia EU), EXH6 (Beni personali), IBB (Biotech),
## EXH4 (Industriali EU). L'utente può comunque attivarli da UI.
SECTORS_TS_OFF = (
    # USA operativi senza time-stop (7)
    'XLK', 'SOXX', 'XLF', 'XLV', 'XLI', 'XLP', 'XLE',
    # EU operativi senza time-stop (2)
    'EXV1.DE', 'EXH5.DE',
)
SECTORS_TS6 = ()  # cluster vuoto di default; l'utente può comunque scegliere TS=6 da UI
SECTORS_TS3 = ()  # cluster vuoto di default; l'utente può comunque scegliere TS=3 da UI
SECTORS_SYSTEM = SECTORS_TS_OFF + SECTORS_TS6 + SECTORS_TS3  # 9 settori operativi di default
TIME_STOP_LOSS_TOLERANCE = 0.0  # 0% = "dopo ts_weeks, se non sei in guadagno esci"


def get_time_stop_weeks(ticker):
    """Ritorna le settimane di time-stop per il ticker, o None se non applicabile."""
    if ticker in SECTORS_TS6:
        return 6
    if ticker in SECTORS_TS3:
        return 3
    return None


def is_system_active(ticker):
    """True se il settore ha sistema operativo attivo (segnale IN/OUT)."""
    return ticker in SECTORS_SYSTEM


def is_operational_in_base(state, stage):
    """
    REGOLA NO_BAD BASE (senza time-stop) · matrice 4×4 storica 2008-2026.
    
    Matrice:
                       Fase 1   Fase 2   Fase 3   Fase 4
    Leader             IN       IN       IN       OUT
    Emergente          IN       IN       IN       OUT
    In rallentamento   IN       IN       IN       OUT
    Debole             OUT      OUT      OUT      OUT
    
    NOTA: per i settori del sistema, dopo questa regola si applica
    anche apply_time_stop_to_records() che esegue l'uscita anticipata
    se il prezzo è ancora negativo dopo N settimane.
    """
    if state == 'Debole':
        return False
    if stage == '4':
        return False
    return state in ('Leader', 'Emergente', 'In rallentamento') and stage in ('1', '2', '3')


# Backward-compatibility: alias per non rompere altri call site
is_operational_in = is_operational_in_base


def apply_time_stop_to_records(weekly_records, prices, ts_weeks,
                                loss_tol=TIME_STOP_LOSS_TOLERANCE):
    """
    Applica logica time-stop a una serie temporale di segnali base.
    
    Regola:
    - IN da > ts_weeks settimane E prezzo < entry * (1 - loss_tol) → ESCO
    - Dopo uscita per time-stop, devo aspettare un OUT "pulito" prima di rientrare
    
    Input:
      weekly_records: lista di dict ordinata per data, con campo 'in' (bool)
      prices: pandas Series dei prezzi indicizzata per data
      ts_weeks: settimane di "prova" prima di applicare time-stop (3 o 6)
      loss_tol: tolleranza 1% prima di chiamare "negativo"
    
    Output: stessi record con campo 'in' aggiornato per riflettere il time-stop.
    """
    if ts_weeks is None or not weekly_records:
        return weekly_records
    
    in_position = False
    entry_price = None
    weeks_in = 0
    waiting_for_reset = False  # True se uscito per time-stop, attendo nuovo OUT base
    
    new_records = []
    for rec in weekly_records:
        is_in_base = rec['in']
        try:
            price = prices.loc[rec['date']]
        except (KeyError, IndexError):
            price = None
        
        if price is None or pd.isna(price):
            new_records.append({**rec, 'in': in_position})
            continue
        
        if in_position:
            weeks_in += 1
            if not is_in_base:
                # Uscita "naturale" perché segnale base è diventato OUT
                in_position = False
                entry_price = None
                weeks_in = 0
                waiting_for_reset = False
            elif weeks_in > ts_weeks and price < entry_price * (1 - loss_tol):
                # Time-stop triggered
                in_position = False
                entry_price = None
                weeks_in = 0
                waiting_for_reset = True
        else:
            if not is_in_base:
                # Tornato il "reset": posso rientrare al prossimo segnale
                waiting_for_reset = False
            if is_in_base and not waiting_for_reset:
                # Nuovo ingresso
                in_position = True
                entry_price = price
                weeks_in = 0
        
        new_records.append({**rec, 'in': in_position})
    return new_records


def extract_signal_history(rrg_df, prices, bench_prices, ma_weeks=30, lookback_weeks=52, ticker=None):
    """
    Estrae lo storico dei segnali operativi IN/OUT sulle ultime N settimane.
    
    Per ogni settimana nella finestra: segnale NO_BAD base. Poi, se il ticker è nel
    sistema (SECTORS_SYSTEM), applica anche il time-stop appropriato (TS3 o TS6).
    Se il ticker NON è nel sistema, ritorna i segnali base ma il chiamante può
    ignorarli (settori INFO_ONLY).
    """
    if rrg_df is None or len(rrg_df) == 0 or prices is None or len(prices) == 0:
        return []
    
    # Allinea le date tra RRG, prezzi settore e benchmark
    common = rrg_df.index.intersection(prices.dropna().index)
    if bench_prices is not None:
        common = common.intersection(bench_prices.dropna().index)
    if len(common) < 10:
        return []
    
    # Limita alla finestra di lookback
    if len(common) > lookback_weeks:
        common = common[-lookback_weeks:]
    
    # Calcola MA Weinstein settimanale sui prezzi
    valid_prices = prices.dropna()
    ma_series = valid_prices.rolling(window=ma_weeks).mean()
    
    # Per ogni settimana nella finestra: stato + fase + segnale base
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
            
            if above_ma and slope_up:        stage = '2'
            elif above_ma and not slope_up:  stage = '3'
            elif not above_ma and not slope_up: stage = '4'
            else:                            stage = '1'
        
        # Segnale base (NO_BAD puro)
        signal_in = is_operational_in_base(state, stage)
        weekly_records.append({
            'date': date,
            'state': state,
            'stage': stage,
            'in': signal_in,
        })
    
    # Applica time-stop sui settori del sistema (TS3 o TS6 a seconda del cluster)
    ts_weeks = get_time_stop_weeks(ticker) if ticker else None
    if ts_weeks is not None:
        weekly_records = apply_time_stop_to_records(weekly_records, valid_prices, ts_weeks)
    
    if len(weekly_records) == 0:
        return []
    
    # Raggruppa periodi consecutivi con stesso segnale
    periods = []
    current_period = {
        'signal': 'IN' if weekly_records[0]['in'] else 'OUT',
        'start_date': weekly_records[0]['date'],
        'end_date': weekly_records[0]['date'],
        'start_state': weekly_records[0]['state'],
        'start_stage': weekly_records[0]['stage'],
        'end_state': weekly_records[0]['state'],
        'end_stage': weekly_records[0]['stage'],
    }
    
    for rec in weekly_records[1:]:
        current_signal = 'IN' if rec['in'] else 'OUT'
        if current_signal == current_period['signal']:
            # Estendi periodo corrente
            current_period['end_date'] = rec['date']
            current_period['end_state'] = rec['state']
            current_period['end_stage'] = rec['stage']
        else:
            # Chiudi periodo corrente, apri nuovo
            periods.append(current_period)
            current_period = {
                'signal': current_signal,
                'start_date': rec['date'],
                'end_date': rec['date'],
                'start_state': rec['state'],
                'start_stage': rec['stage'],
                'end_state': rec['state'],
                'end_stage': rec['stage'],
            }
    periods.append(current_period)
    
    # Calcola metriche per ogni periodo
    last_date_overall = weekly_records[-1]['date']
    output = []
    for p in periods:
        start = p['start_date']
        end = p['end_date']
        
        # Performance settore nel periodo
        try:
            p_start = valid_prices.loc[start]
            p_end = valid_prices.loc[end]
            perf_sector = float((p_end / p_start - 1) * 100)
        except Exception:
            perf_sector = None
        
        # Performance benchmark nel periodo
        perf_bench = None
        if bench_prices is not None:
            try:
                bv = bench_prices.dropna()
                b_start = bv.loc[start]
                b_end = bv.loc[end]
                perf_bench = float((b_end / b_start - 1) * 100)
            except Exception:
                perf_bench = None
        
        alpha = None
        if perf_sector is not None and perf_bench is not None:
            alpha = round(perf_sector - perf_bench, 1)
        
        is_current = (end == last_date_overall)
        weeks = max(1, weeks_between(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')))
        
        # Etichetta motivo
        reason_label = f"{p['start_state']} · Fase {p['start_stage']}"
        if p['start_state'] != p['end_state'] or p['start_stage'] != p['end_stage']:
            reason_label += f" → {p['end_state']} · Fase {p['end_stage']}"
        
        output.append({
            'signal': p['signal'],
            'start_date': start.strftime('%Y-%m-%d'),
            'end_date': end.strftime('%Y-%m-%d'),
            'weeks': weeks,
            'perf_sector': round(perf_sector, 1) if perf_sector is not None else None,
            'perf_bench': round(perf_bench, 1) if perf_bench is not None else None,
            'alpha': alpha,
            'start_state': p['start_state'],
            'start_stage': p['start_stage'],
            'end_state': p['end_state'],
            'end_stage': p['end_stage'],
            'reason': reason_label,
            'is_current': is_current,
        })
    
    return output


def compute_sector_equity(prices, signal_history):
    """
    Calcola l'equity curve di un singolo settore confrontando il sistema 
    (IN/OUT) con il buy & hold dell'ETF.
    
    Capitale di partenza: 100.
    Quando IN: segue il prezzo dell'ETF.
    Quando OUT: cash 0%.
    
    Restituisce: {
      dates: [...],
      equity_system: [...],
      equity_bh: [...],
      stats_system: {total_return, cagr, max_drawdown, final_value},
      stats_bh: {...},
    }
    """
    if prices is None or len(prices) == 0 or not signal_history:
        return None
    
    valid_prices = prices.dropna()
    if len(valid_prices) < 10:
        return None
    
    # Inizio: data del primo periodo storico
    try:
        portfolio_start = pd.to_datetime(signal_history[0]['start_date'])
    except Exception:
        return None
    
    # Filtra prezzi dall'inizio della history
    series = valid_prices[valid_prices.index >= portfolio_start]
    if len(series) < 5:
        return None
    
    # Costruisci serie IN/OUT settimanale
    in_out = pd.Series(False, index=series.index)
    for period in signal_history:
        try:
            start = pd.to_datetime(period['start_date'])
            end = pd.to_datetime(period['end_date'])
            mask = (in_out.index >= start) & (in_out.index <= end)
            in_out.loc[mask] = (period['signal'] == 'IN')
        except Exception:
            continue
    
    # Simulazione: capitale 100 partenza, ribilanciamento settimanale
    eq_sys = 100.0
    eq_bh = 100.0
    
    equity_system = [eq_sys]
    equity_bh = [eq_bh]
    dates_out = [series.index[0].strftime('%Y-%m-%d')]
    
    prev_date = series.index[0]
    for i in range(1, len(series)):
        date = series.index[i]
        try:
            p_prev = series.iloc[i-1]
            p_curr = series.iloc[i]
            if pd.isna(p_prev) or pd.isna(p_curr) or p_prev == 0:
                continue
            ret = p_curr / p_prev - 1.0
            
            # Buy & Hold: sempre dentro
            eq_bh *= (1 + ret)
            
            # Sistema: solo se IN nella settimana precedente
            was_in = in_out.loc[prev_date] if prev_date in in_out.index else False
            if was_in:
                eq_sys *= (1 + ret)
            # else: cash 0%, eq_sys invariato
        except Exception:
            continue
        
        equity_system.append(round(eq_sys, 3))
        equity_bh.append(round(eq_bh, 3))
        dates_out.append(date.strftime('%Y-%m-%d'))
        prev_date = date
    
    def compute_stats(eq):
        if len(eq) < 2:
            return None
        total_ret = (eq[-1] / eq[0] - 1) * 100
        weeks = len(eq) - 1
        years = weeks / 52.0
        cagr = ((eq[-1] / eq[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
        peak = eq[0]
        max_dd = 0
        for v in eq:
            if v > peak:
                peak = v
            dd = (v / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd
        return {
            'total_return': round(total_ret, 1),
            'cagr': round(cagr, 1),
            'max_drawdown': round(max_dd, 1),
            'final_value': round(eq[-1], 1),
        }
    
    return {
        'dates': dates_out,
        'equity_system': equity_system,
        'equity_bh': equity_bh,
        'stats_system': compute_stats(equity_system),
        'stats_bh': compute_stats(equity_bh),
        'start_date': dates_out[0] if dates_out else None,
        'end_date': dates_out[-1] if dates_out else None,
    }


def compute_history_stats(history):
    """
    Calcola statistiche aggregate sullo storico:
    - tempo totale IN, percentuale del lookback
    - performance cumulata aggregata nei periodi IN
    - hit rate (entrate profittevoli / entrate totali)
    - breakdown per anno
    """
    if not history:
        return None
    
    in_periods = [h for h in history if h['signal'] == 'IN']
    completed_in = [h for h in in_periods if not h.get('is_current')]
    
    total_weeks = sum(h['weeks'] for h in history) or 1
    weeks_in = sum(h['weeks'] for h in in_periods)
    pct_in = round(weeks_in / total_weeks * 100, 0)
    
    # Performance cumulata IN: compongo i singoli rendimenti
    cum_perf_in = 1.0
    valid_perfs = [h['perf_sector'] for h in in_periods if h.get('perf_sector') is not None]
    for p in valid_perfs:
        cum_perf_in *= (1 + p / 100)
    cum_perf_in_pct = round((cum_perf_in - 1) * 100, 1)
    
    # Hit rate (solo su completati)
    profitable = [h for h in completed_in if (h.get('perf_sector') or 0) > 0]
    hit_rate = round(len(profitable) / len(completed_in) * 100, 0) if completed_in else None
    
    avg_weeks = round(sum(h['weeks'] for h in in_periods) / len(in_periods), 1) if in_periods else 0
    
    # Alpha cumulato (somma alphas semplice come proxy, perché sono già rendimenti relativi)
    valid_alphas = [h['alpha'] for h in in_periods if h.get('alpha') is not None]
    sum_alpha_in = round(sum(valid_alphas), 1) if valid_alphas else None
    
    # Range temporale
    start_date = history[0]['start_date'] if history else None
    end_date = history[-1]['end_date'] if history else None
    years_span = None
    if start_date and end_date:
        try:
            d1 = pd.to_datetime(start_date)
            d2 = pd.to_datetime(end_date)
            years_span = round((d2 - d1).days / 365.25, 1)
        except Exception:
            pass
    
    # Breakdown per anno
    yearly = {}
    for h in history:
        try:
            year = h['start_date'][:4]
        except Exception:
            continue
        if year not in yearly:
            yearly[year] = {
                'year': year,
                'periods_in': 0,
                'periods_out': 0,
                'weeks_in': 0,
                'weeks_out': 0,
                'cum_perf_in': 1.0,
                'sum_alpha_in': 0.0,
                'periods': [],
            }
        yearly[year]['periods'].append(h)
        if h['signal'] == 'IN':
            yearly[year]['periods_in'] += 1
            yearly[year]['weeks_in'] += h['weeks']
            if h.get('perf_sector') is not None:
                yearly[year]['cum_perf_in'] *= (1 + h['perf_sector'] / 100)
            if h.get('alpha') is not None:
                yearly[year]['sum_alpha_in'] += h['alpha']
        else:
            yearly[year]['periods_out'] += 1
            yearly[year]['weeks_out'] += h['weeks']
    
    # Finalizza yearly stats
    yearly_list = []
    for year, y in sorted(yearly.items(), reverse=True):
        tot_w = y['weeks_in'] + y['weeks_out'] or 1
        yearly_list.append({
            'year': year,
            'periods_in': y['periods_in'],
            'periods_out': y['periods_out'],
            'weeks_in': y['weeks_in'],
            'weeks_out': y['weeks_out'],
            'pct_in': round(y['weeks_in'] / tot_w * 100, 0),
            'cum_perf_in': round((y['cum_perf_in'] - 1) * 100, 1) if y['periods_in'] > 0 else None,
            'sum_alpha_in': round(y['sum_alpha_in'], 1) if y['periods_in'] > 0 else None,
        })
    
    return {
        'total_weeks': total_weeks,
        'weeks_in': weeks_in,
        'pct_in': pct_in,
        'cum_perf_in': cum_perf_in_pct,
        'hit_rate': hit_rate,
        'in_count': len(in_periods),
        'in_completed': len(completed_in),
        'in_profitable': len(profitable),
        'avg_weeks_in': avg_weeks,
        'sum_alpha_in': sum_alpha_in,
        'years_span': years_span,
        'start_date': start_date,
        'end_date': end_date,
        'yearly': yearly_list,
    }


def classify_stage(prices, ma_weeks=30):
    """Weinstein stage analysis: prezzo vs MA30 + slope MA."""
    if prices is None or len(prices) < ma_weeks + 5:
        return '—'
    
    valid = prices.dropna()
    if len(valid) < ma_weeks + 5:
        return '—'
    
    ma = valid.rolling(window=ma_weeks).mean()
    last_price = valid.iloc[-1]
    last_ma = ma.iloc[-1]
    
    if pd.isna(last_ma):
        return '—'
    
    # Slope MA: confronto MA attuale vs MA di 5 settimane fa
    ma_5w_ago = ma.iloc[-6] if len(ma) >= 6 else last_ma
    slope_up = last_ma > ma_5w_ago
    
    above_ma = last_price > last_ma
    
    if above_ma and slope_up:        return '2'  # uptrend
    if above_ma and not slope_up:    return '3'  # topping
    if not above_ma and not slope_up: return '4'  # downtrend
    return '1'                                    # basing


def compute_sector_metrics(prices_df, bench_ticker, sector_dict):
    """Calcola RS, fase, signal info per ogni settore della regione."""
    if bench_ticker not in prices_df.columns:
        print(f"  Benchmark {bench_ticker} mancante!", file=sys.stderr)
        return []
    
    bench_series = prices_df[bench_ticker].dropna()
    if bench_series.index.tz is not None:
        bench_series.index = bench_series.index.tz_localize(None)
    
    rows = []
    last_data_date = prices_df.index[-1].strftime('%Y-%m-%d') if len(prices_df) > 0 else None
    
    for ticker, name in sector_dict.items():
        if ticker not in prices_df.columns:
            print(f"  Settore {ticker} mancante, skip", file=sys.stderr)
            continue
        
        sec_prices = prices_df[ticker].dropna()
        if len(sec_prices) < 60:
            continue
        if sec_prices.index.tz is not None:
            sec_prices = sec_prices.copy()
            sec_prices.index = sec_prices.index.tz_localize(None)
        
        rrg = calculate_rrg(sec_prices, bench_series, window=14)
        if rrg is None or len(rrg) < 5:
            continue
        
        last_rs = rrg.iloc[-1]['rsRatio']
        last_mom = rrg.iloc[-1]['rsMom']
        prev_rs = rrg.iloc[-6]['rsRatio'] if len(rrg) >= 6 else last_rs
        
        quadrant = classify_quadrant(last_rs, last_mom)
        stage = classify_stage(sec_prices, ma_weeks=30)
        
        # ROC indicators
        roc_13w = ((sec_prices.iloc[-1] / sec_prices.iloc[-14]) - 1) * 100 if len(sec_prices) >= 14 else 0
        roc_52w = ((sec_prices.iloc[-1] / sec_prices.iloc[-53]) - 1) * 100 if len(sec_prices) >= 53 else 0
        
        bench_for_rel = bench_series.copy()
        common = sec_prices.index.intersection(bench_for_rel.index)
        if len(common) >= 14:
            sec_norm = sec_prices.loc[common] / sec_prices.loc[common].iloc[-14]
            bench_norm = bench_for_rel.loc[common] / bench_for_rel.loc[common].iloc[-14]
            rel_13w = (sec_norm.iloc[-1] / bench_norm.iloc[-1] - 1) * 100
        else:
            rel_13w = 0
        
        # Tail RS/Mom per chart (ultime 5)
        tail_rs = [round(float(x), 2) for x in rrg['rsRatio'].iloc[-5:].tolist()]
        tail_mom = [round(float(x), 2) for x in rrg['rsMom'].iloc[-5:].tolist()]
        
        # Serie completa RS-Ratio (ultime 26 settimane = 6 mesi)
        rs_series = [
            {'date': idx.strftime('%Y-%m-%d'), 'value': round(float(val), 2)}
            for idx, val in rrg['rsRatio'].dropna().iloc[-26:].items()
        ]
        
        # Signal info
        state_entry, signal_dt = find_signal_dates(rrg, quadrant)
        signal_info = None
        
        if state_entry and signal_dt:
            perf_from_state = perf_since(sec_prices, state_entry)
            perf_from_signal = perf_since(sec_prices, signal_dt)
            
            bench_for_perf = bench_series.copy()
            if bench_for_perf.index.tz is not None:
                bench_for_perf.index = bench_for_perf.index.tz_localize(None)
            perf_bench_state = perf_since(bench_for_perf, state_entry)
            perf_bench_signal = perf_since(bench_for_perf, signal_dt)
            
            signal_info = {
                'stateEntryDate': state_entry,
                'signalDate': signal_dt,
                'weeksFromState': weeks_between(state_entry, last_data_date),
                'weeksFromSignal': weeks_between(signal_dt, last_data_date),
                'perfFromState': round(perf_from_state, 1) if perf_from_state is not None else None,
                'perfFromSignal': round(perf_from_signal, 1) if perf_from_signal is not None else None,
                'benchFromState': round(perf_bench_state, 1) if perf_bench_state is not None else None,
                'benchFromSignal': round(perf_bench_signal, 1) if perf_bench_signal is not None else None,
                'benchTicker': bench_ticker,
                'relFromState': round(perf_from_state - perf_bench_state, 1) if (perf_from_state is not None and perf_bench_state is not None) else None,
                'relFromSignal': round(perf_from_signal - perf_bench_signal, 1) if (perf_from_signal is not None and perf_bench_signal is not None) else None,
            }
        
        display_ticker = ticker.replace('.DE', '').replace('.US', '')
        etf_info = ETF_INFO.get(ticker)
        
        # Storico segnali completo (lookback ~28 anni: copre l'intera serie disponibile).
        # Per i settori del sistema, extract_signal_history applica anche
        # il time-stop appropriato (TS3 o TS6). Per i settori INFO_ONLY
        # la serie viene calcolata ma non usata per il segnale operativo.
        signal_history = extract_signal_history(rrg, sec_prices, bench_series, 
                                                 ma_weeks=30, lookback_weeks=1500,
                                                 ticker=ticker)
        history_stats = compute_history_stats(signal_history)
        
        # Equity curve del singolo settore (sistema vs buy & hold).
        # Disabilitata per settori INFO_ONLY perché il sistema non si applica.
        if is_system_active(ticker):
            sector_equity = compute_sector_equity(sec_prices, signal_history)
        else:
            sector_equity = None
        
        # Segnale operativo IN/OUT/INFO corrente
        if not is_system_active(ticker):
            # Settori INFO_ONLY: nessun segnale operativo, solo stato/fase visibili
            op_signal = 'INFO'
            current_period = None
        else:
            # Settori del sistema: prendi l'ultimo segnale dalla serie con time-stop
            current_period = signal_history[-1] if signal_history else None
            if current_period:
                op_signal = current_period.get('signal', 'OUT')
            else:
                # Fallback al segnale base se la storia non è disponibile
                op_signal = 'IN' if is_operational_in_base(quadrant, stage) else 'OUT'
        
        # Pre-calcola record settimanali BASE per la simulazione frontend
        base_records_full = compute_weekly_base_records(rrg, sec_prices, ma_weeks=30)
        region = 'USA' if bench_ticker == US_BENCHMARK else 'EU'

        rows.append({
            'ticker': display_ticker,
            'ticker_raw': ticker,
            'name': name,
            'region': region,
            'stage': stage,
            'state': quadrant,
            'opSignal': op_signal,
            'opCurrent': current_period,
            'opHistory': signal_history,
            'opStats': history_stats,
            'opEquity': sector_equity,
            'rsRatio': round(last_rs, 2),
            'rsMom': round(last_mom, 2),
            'delta5w': round(last_rs - prev_rs, 2),
            'roc13w': round(float(roc_13w), 1),
            'roc52w': round(float(roc_52w), 1),
            'rel13w': round(float(rel_13w), 1),
            'tailRS': tail_rs,
            'tailMom': tail_mom,
            'rsRatioSeries': rs_series,
            'signal': signal_info,
            'etfInfo': etf_info,
            '_base_records': base_records_full,  # interno, rimosso prima del JSON
        })
    
    return rows


# ============================================================
# CLASSIFICA DI FORZA con Δ vs snapshot precedente
# ============================================================
def score_sector(sector):
    """Punteggio di forza 0-200+."""
    state = sector.get('state')
    rs_ratio = sector.get('rsRatio') or 100
    signal = sector.get('signal') or {}
    weeks = signal.get('weeksFromState') or 0
    rel_perf = signal.get('relFromState') or 0
    stage = sector.get('stage', '')
    
    # Base per stato
    score = 0
    if state == 'Leader': score = 100
    elif state == 'Emergente': score = 70
    elif state == 'In rallentamento': score = 40
    else: score = 10
    
    # Bonus rsRatio (oltre 100)
    score += max(0, rs_ratio - 100) * 2
    
    # Bonus/malus alpha vs benchmark
    score += max(-30, min(30, rel_perf * 0.6))
    
    # Penalità maturità (per Leader)
    if state == 'Leader':
        if weeks > 60: score -= 20
        elif weeks > 40: score -= 10
    
    # Bonus/malus fase
    if '2' in stage: score += 5
    elif '4' in stage: score -= 5
    
    return round(score, 1)


def compute_sector_ranking(us_metrics, eu_metrics, history_path='data/ranking_history.json'):
    """Costruisce classifica USA+EU con Δ vs snapshot ~7 giorni fa."""
    
    all_sectors = []
    for s in us_metrics:
        all_sectors.append({
            'ticker': s.get('ticker'),
            'ticker_raw': s.get('ticker_raw'),
            'name': s.get('name'),
            'region': 'USA',
            'state': s.get('state'),
            'stage': s.get('stage'),
            'opSignal': s.get('opSignal'),
            'opCurrent': s.get('opCurrent'),
            'opHistory': s.get('opHistory'),
            'opStats': s.get('opStats'),
            'opEquity': s.get('opEquity'),
            'rsRatio': s.get('rsRatio'),
            'rsMom': s.get('rsMom'),
            'signal': s.get('signal'),
            'etfInfo': s.get('etfInfo'),
            'score': score_sector(s),
        })
    for s in eu_metrics:
        all_sectors.append({
            'ticker': s.get('ticker'),
            'ticker_raw': s.get('ticker_raw'),
            'name': s.get('name'),
            'region': 'EU',
            'state': s.get('state'),
            'stage': s.get('stage'),
            'opSignal': s.get('opSignal'),
            'opCurrent': s.get('opCurrent'),
            'opHistory': s.get('opHistory'),
            'opStats': s.get('opStats'),
            'opEquity': s.get('opEquity'),
            'rsRatio': s.get('rsRatio'),
            'rsMom': s.get('rsMom'),
            'signal': s.get('signal'),
            'etfInfo': s.get('etfInfo'),
            'score': score_sector(s),
        })
    
    # Ordina per punteggio decrescente
    all_sectors.sort(key=lambda x: x['score'], reverse=True)
    
    # Assegna rank corrente
    for i, s in enumerate(all_sectors):
        s['rank'] = i + 1
    
    # Carica storico
    prev_ranks = {}
    prev_date = None
    history = []
    try:
        if os.path.exists(history_path):
            with open(history_path, 'r') as f:
                history = json.load(f)
    except Exception as e:
        print(f"  Storico ranking non disponibile: {e}", file=sys.stderr)
        history = []
    
    # Trova snapshot 5-9 giorni fa
    today = datetime.now(timezone.utc).date()
    for snap in reversed(history):
        try:
            snap_date = datetime.fromisoformat(snap['date']).date()
            days_diff = (today - snap_date).days
            if 5 <= days_diff <= 9:
                prev_ranks = {r['ticker']: r['rank'] for r in snap.get('ranks', [])}
                prev_date = snap['date']
                break
        except Exception:
            continue
    
    # Aggiungi delta vs snapshot precedente
    for s in all_sectors:
        prev = prev_ranks.get(s['ticker'])
        if prev is not None:
            delta = prev - s['rank']
            if delta > 0:
                s['rank_change'] = delta
                s['rank_direction'] = 'up'
            elif delta < 0:
                s['rank_change'] = abs(delta)
                s['rank_direction'] = 'down'
            else:
                s['rank_change'] = 0
                s['rank_direction'] = 'flat'
            s['prev_rank'] = prev
        else:
            s['rank_change'] = None
            s['rank_direction'] = 'new'
            s['prev_rank'] = None
    
    # Salva snapshot odierno (max 35 giorni di storia)
    today_snapshot = {
        'date': datetime.now(timezone.utc).isoformat(),
        'ranks': [{'ticker': s['ticker'], 'rank': s['rank'], 'score': s['score']} for s in all_sectors],
    }
    history = [h for h in history if not h.get('date', '').startswith(today.isoformat())]
    history.append(today_snapshot)
    if len(history) > 35:
        history = history[-35:]
    
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)
        print(f"  Snapshot salvato in {history_path}")
    except Exception as e:
        print(f"  Errore salvataggio storico: {e}", file=sys.stderr)
    
    return {
        'ranking': all_sectors,
        'prev_snapshot_date': prev_date,
    }


def compute_portfolio_equity(all_metrics, prices_df, ma_weeks=30):
    """
    Simula un portafoglio sistemico equipesato sui SOLI settori del sistema (7 settori).
    
    Logica:
    - Capitale di partenza: 100
    - Sono inclusi solo i settori in SECTORS_SYSTEM (TS6 + TS3 = 7 settori)
    - I settori INFO_ONLY sono ESCLUSI dal portafoglio sistemico
    - Ogni settore ha un peso fisso di 1/7
    - Quando il settore è IN (regola NO_BAD + time-stop) → segue il prezzo
    - Quando il settore è OUT → il suo peso resta in cash (0% rendimento)
    - Equity totale = somma di tutti i sub-portafogli ad ogni settimana
    
    Genera anche curva "Buy & Hold equipesato" sui 7 settori per confronto.
    """
    if not all_metrics:
        return None
    
    # Filtra solo i settori del sistema (escludi INFO_ONLY)
    system_metrics = [s for s in all_metrics if is_system_active(s.get('ticker_raw', ''))]
    if not system_metrics:
        return None
    
    n_sectors = len(system_metrics)
    weight = 100.0 / n_sectors
    
    # Costruisci tabella settimanale: per ogni data, per ogni settore: (in_out, price)
    # Uso prices_df che è settimanale W-FRI
    
    # Trova la data comune più antica fra tutti i settori del sistema
    common_dates = None
    sector_data = {}  # ticker -> (prices_series, in_out_series)
    
    for s in system_metrics:
        ticker_raw = s.get('ticker_raw')
        if not ticker_raw or ticker_raw not in prices_df.columns:
            continue
        sec_prices = prices_df[ticker_raw].dropna()
        if len(sec_prices) < ma_weeks + 14:
            continue
        if sec_prices.index.tz is not None:
            sec_prices = sec_prices.copy()
            sec_prices.index = sec_prices.index.tz_localize(None)
        
        # Per ogni settimana, ricalcola stato RRG + fase Weinstein
        # Uso il rrg già calcolato? No, qui devo ricalcolare per coerenza temporale
        # Però possiamo riutilizzare la opHistory che già sappiamo
        history = s.get('opHistory') or []
        if not history:
            continue
        
        # Crea serie IN/OUT settimanale dalla opHistory
        in_out_series = pd.Series(False, index=sec_prices.index)
        for period in history:
            try:
                start = pd.to_datetime(period['start_date'])
                end = pd.to_datetime(period['end_date'])
                mask = (in_out_series.index >= start) & (in_out_series.index <= end)
                in_out_series.loc[mask] = (period['signal'] == 'IN')
            except Exception:
                continue
        
        sector_data[ticker_raw] = (sec_prices, in_out_series)
        
        if common_dates is None:
            common_dates = set(sec_prices.index)
        else:
            common_dates = common_dates & set(sec_prices.index)
    
    if not sector_data or not common_dates:
        return None
    
    common_dates = sorted(common_dates)
    if len(common_dates) < 10:
        return None
    
    # Limita alla finestra dello storico segnali (cioè dove tutti hanno almeno dati significativi)
    # Inizia dalla data più antica della history fra tutti i settori
    histories_starts = []
    for s in all_metrics:
        h = s.get('opHistory') or []
        if h:
            try:
                histories_starts.append(pd.to_datetime(h[0]['start_date']))
            except Exception:
                pass
    
    if histories_starts:
        portfolio_start = max(histories_starts)  # parti dalla data dove TUTTI hanno storia
        common_dates = [d for d in common_dates if d >= portfolio_start]
    
    if len(common_dates) < 10:
        return None
    
    # Simulazione equity settimana per settimana
    # Stato: per ogni settore, sub-equity corrente
    sub_equity_system = {t: weight for t in sector_data.keys()}
    sub_equity_bh = {t: weight for t in sector_data.keys()}
    
    equity_system = []
    equity_bh = []
    dates_out = []
    
    prev_date = None
    for date in common_dates:
        if prev_date is None:
            # Primo punto: equity totale = N * weight = 100
            equity_system.append(sum(sub_equity_system.values()))
            equity_bh.append(sum(sub_equity_bh.values()))
            dates_out.append(date.strftime('%Y-%m-%d'))
            prev_date = date
            continue
        
        for ticker, (prices, in_out) in sector_data.items():
            try:
                p_prev = prices.loc[prev_date]
                p_curr = prices.loc[date]
                if pd.isna(p_prev) or pd.isna(p_curr) or p_prev == 0:
                    continue
                ret = p_curr / p_prev - 1.0
                
                # Buy & Hold: sempre dentro
                sub_equity_bh[ticker] *= (1 + ret)
                
                # Sistema: solo se IN nella settimana prev_date (decisione presa la settimana prima)
                was_in = in_out.loc[prev_date] if prev_date in in_out.index else False
                if was_in:
                    sub_equity_system[ticker] *= (1 + ret)
                # se OUT, sub_equity_system[ticker] resta invariato (cash 0%)
            except Exception:
                continue
        
        equity_system.append(round(sum(sub_equity_system.values()), 3))
        equity_bh.append(round(sum(sub_equity_bh.values()), 3))
        dates_out.append(date.strftime('%Y-%m-%d'))
        prev_date = date
    
    # Calcola statistiche
    def compute_stats(eq):
        if len(eq) < 2:
            return None
        start_val = eq[0]
        end_val = eq[-1]
        total_ret = (end_val / start_val - 1) * 100
        
        # CAGR
        weeks = len(eq) - 1
        years = weeks / 52.0
        cagr = ((end_val / start_val) ** (1 / years) - 1) * 100 if years > 0 else 0
        
        # Max drawdown
        peak = eq[0]
        max_dd = 0
        for v in eq:
            if v > peak:
                peak = v
            dd = (v / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd
        
        return {
            'total_return': round(total_ret, 1),
            'cagr': round(cagr, 1),
            'max_drawdown': round(max_dd, 1),
            'final_value': round(end_val, 1),
        }
    
    # Calcola anche tempo % medio investito dal sistema
    avg_pct_invested = 0
    if equity_system and equity_bh:
        # In ogni settimana: quanti settori erano IN?
        in_counts = []
        for date in common_dates:
            cnt = sum(1 for t, (_, io) in sector_data.items() 
                     if date in io.index and io.loc[date])
            in_counts.append(cnt)
        if in_counts:
            avg_pct_invested = round(sum(in_counts) / len(in_counts) / n_sectors * 100, 0)
    
    return {
        'dates': dates_out,
        'equity_system': equity_system,
        'equity_bh': equity_bh,
        'n_sectors': n_sectors,
        'weight_per_sector': round(weight, 2),
        'stats_system': compute_stats(equity_system),
        'stats_bh': compute_stats(equity_bh),
        'avg_pct_invested': avg_pct_invested,
        'start_date': dates_out[0] if dates_out else None,
        'end_date': dates_out[-1] if dates_out else None,
    }


# ============================================================
# SIGNAL SMOOTHING + PORTFOLIO SIMULATION GRID
# ============================================================
# Tolleranza temporale per smoothing del segnale base: ignora oscillazioni di durata
# ≤ tolerance_weeks settimane consecutive (riduce whipsaw sulle soglie RS 100/100).
SIGNAL_SMOOTHING_TOLERANCE_WEEKS = 3
TS_OPTIONS = ['off', '1', '2', '3', '4', '5', '6', '7', '8', '9']


def smooth_signal_binary(signals, tolerance_weeks=SIGNAL_SMOOTHING_TOLERANCE_WEEKS):
    """Liscia una serie binaria ignorando transizioni che durano ≤ tolerance_weeks
    settimane consecutive. Tolerance=3: [T,T,F,T,T,T,T] → [T,T,T,T,T,T,T]."""
    if not signals or len(signals) <= 1:
        return list(signals)
    smoothed = []
    current = signals[0]
    pending_count = 0
    for s in signals:
        if s == current:
            pending_count = 0
            smoothed.append(current)
        else:
            pending_count += 1
            if pending_count > tolerance_weeks:
                current = s
                pending_count = 0
            smoothed.append(current)
    return smoothed


def _get_default_ts_label(ticker):
    """Restituisce la label TS di default per un ticker (per il dropdown frontend).
    'off' = operativo senza time-stop. '6'/'3' = operativo con time-stop.
    'excluded' = settore escluso di default (non in portafoglio sistemico)."""
    if ticker in SECTORS_TS_OFF:
        return 'off'
    if ticker in SECTORS_TS6:
        return '6'
    if ticker in SECTORS_TS3:
        return '3'
    return 'excluded'


def compute_weekly_base_records(rrg_df, prices, ma_weeks=30,
                                  smoothing_weeks=SIGNAL_SMOOTHING_TOLERANCE_WEEKS):
    """Serie settimanale base (state, stage, signal smoothed) senza time-stop."""
    if rrg_df is None or len(rrg_df) == 0 or prices is None or len(prices) == 0:
        return []
    valid_prices = prices.dropna()
    common = rrg_df.index.intersection(valid_prices.index)
    if len(common) < 5:
        return []
    ma_series = valid_prices.rolling(window=ma_weeks).mean()
    records = []
    for date in common:
        try:
            rs = rrg_df.loc[date, 'rsRatio']
            mom = rrg_df.loc[date, 'rsMom']
        except Exception:
            continue
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
        records.append({
            'date': date, 'state': state, 'stage': stage,
            'in': is_operational_in_base(state, stage),
        })
    if smoothing_weeks and smoothing_weeks > 0 and len(records) > 1:
        raw_signals = [r['in'] for r in records]
        smoothed = smooth_signal_binary(raw_signals, tolerance_weeks=smoothing_weeks)
        for i, r in enumerate(records):
            r['in'] = smoothed[i]
    return records


def compute_portfolio_simulation(all_metrics, prices_df, ma_weeks=30):
    """Pre-calcola griglia di simulazione: per ogni settore + ogni opzione TS,
    serie settimanale di segnali IN/OUT. Alimenta dropdown TS interattivo frontend."""
    if not all_metrics:
        return None
    common_dates = None
    sector_prices = {}
    for s in all_metrics:
        ticker_raw = s.get('ticker_raw')
        if not ticker_raw or ticker_raw not in prices_df.columns:
            continue
        sec_prices = prices_df[ticker_raw].dropna()
        if len(sec_prices) < ma_weeks + 14:
            continue
        if sec_prices.index.tz is not None:
            sec_prices = sec_prices.copy()
            sec_prices.index = sec_prices.index.tz_localize(None)
        sector_prices[ticker_raw] = sec_prices
        idx_set = set(sec_prices.index)
        common_dates = idx_set if common_dates is None else common_dates & idx_set
    if not sector_prices or not common_dates:
        return None
    common_dates = sorted(common_dates)
    if len(common_dates) < 10:
        return None

    histories_starts = []
    for s in all_metrics:
        h = s.get('opHistory') or []
        if h:
            try:
                histories_starts.append(pd.to_datetime(h[0]['start_date']))
            except Exception:
                pass
    if histories_starts:
        portfolio_start = max(histories_starts)
        common_dates = [d for d in common_dates if d >= portfolio_start]
    if len(common_dates) < 10:
        return None
    
    # === PREZZI EUR per visualizzazione ===
    # Scarica i prezzi degli ETF iShares europei (Milano) e allinea sulle date del backtest.
    # Usati nelle tabelle posizioni aperte, operazioni chiuse, movimenti settimanali.
    # Backtest, equity, performance: continuano a usare i prezzi SPDR USA (sectors_out[..]['prices']).
    eur_prices_by_ticker = fetch_eur_prices_aligned(common_dates)

    sectors_out = {}
    n_default_operational = 0
    for s in all_metrics:
        ticker_raw = s.get('ticker_raw')
        if not ticker_raw or ticker_raw not in sector_prices:
            continue
        base_records = s.get('_base_records')
        if not base_records:
            continue
        sec_prices = sector_prices[ticker_raw]
        records_by_date = {r['date']: r for r in base_records}
        aligned_base = []
        prices_aligned = []
        for d in common_dates:
            r = records_by_date.get(d)
            if r is None:
                aligned_base.append({'date': d, 'state': '—', 'stage': '—', 'in': False})
            else:
                aligned_base.append(r)
            try:
                p = sec_prices.loc[d]
                prices_aligned.append(None if pd.isna(p) else float(round(p, 4)))
            except Exception:
                prices_aligned.append(None)
        signals_by_ts = {}
        for ts_label in TS_OPTIONS:
            ts_weeks = None if ts_label == 'off' else int(ts_label)
            adjusted = apply_time_stop_to_records(aligned_base, sec_prices, ts_weeks)
            signals_by_ts[ts_label] = [bool(r['in']) for r in adjusted]
        states_aligned = [r.get('state', '—') for r in aligned_base]
        stages_aligned = [r.get('stage', '—') for r in aligned_base]
        default_ts = _get_default_ts_label(ticker_raw)
        if default_ts != 'excluded':
            n_default_operational += 1
        sectors_out[ticker_raw] = {
            'name': s.get('name', ticker_raw),
            'ticker_display': s.get('ticker') or ticker_raw,
            'region': s.get('region', 'EU'),
            'default_ts': default_ts,
            'prices': prices_aligned,
            'prices_eur': eur_prices_by_ticker.get(ticker_raw, [None] * len(common_dates)),
            'states': states_aligned,
            'stages': stages_aligned,
            'signals_by_ts': signals_by_ts,
        }
    if not sectors_out:
        return None

    benchmarks_out = {}
    for region, bench_ticker in (('USA', US_BENCHMARK), ('EU', EU_BENCHMARK), ('WORLD', WORLD_TICKER)):
        if bench_ticker in prices_df.columns:
            bench_series = prices_df[bench_ticker].dropna()
            if bench_series.index.tz is not None:
                bench_series = bench_series.copy()
                bench_series.index = bench_series.index.tz_localize(None)
            bench_aligned = []
            for d in common_dates:
                try:
                    p = bench_series.loc[d]
                    bench_aligned.append(None if pd.isna(p) else float(round(p, 4)))
                except Exception:
                    bench_aligned.append(None)
            benchmarks_out[region] = bench_aligned

    return {
        'dates': [d.strftime('%Y-%m-%d') for d in common_dates],
        'default_n_operational': n_default_operational,
        'sectors': sectors_out,
        'benchmarks': benchmarks_out,
        'smoothing_weeks': SIGNAL_SMOOTHING_TOLERANCE_WEEKS,
    }


# ============================================================
# MAIN
# ============================================================
def main():
    print("Megatrend Sentinel ETF · Data Update")
    print("=" * 60)
    
    all_tickers = (
        [US_BENCHMARK] + list(US_SECTORS.keys()) +
        [EU_BENCHMARK] + list(EU_SECTORS.keys()) +
        [CASH_TICKER, WORLD_TICKER]
    )
    all_tickers = list(set(all_tickers))
    
    # Data di inizio del backtest: fissa a 2008-01-01 (copre 2008 GFC, EuroDebt 2011,
    # taper 2013, Cina 2015, trade-war 2018, COVID 2020, 2022 inflazione, 2024+ AI rally).
    # Usiamo period='max' per scaricare tutto il disponibile da yfinance, poi tagliamo.
    BACKTEST_START_DATE = '2008-01-01'
    print(f"Scarico {len(all_tickers)} ticker da yfinance (max history)...")
    prices = fetch_prices(all_tickers, period='max')
    
    # === DEBUG: stampa prima/ultima data e numero settimane per ogni ticker ===
    if not prices.empty:
        print("\n  Storico disponibile per ticker (PRIMA del filtro 2008):")
        ticker_first_dates = {}
        for col in prices.columns:
            col_series = prices[col].dropna()
            if len(col_series) > 0:
                first_d = col_series.index[0].strftime('%Y-%m-%d')
                last_d = col_series.index[-1].strftime('%Y-%m-%d')
                ticker_first_dates[col] = col_series.index[0]
                print(f"    {col:<12} {first_d} → {last_d}  ({len(col_series)} sett)")
            else:
                print(f"    {col:<12} <vuoto>")
        # Identifica il ticker più "giovane" (limita la finestra del backtest)
        if ticker_first_dates:
            youngest_ticker = max(ticker_first_dates, key=ticker_first_dates.get)
            youngest_date = ticker_first_dates[youngest_ticker].strftime('%Y-%m-%d')
            print(f"\n  ⚠ Ticker più giovane (limita backtest portafoglio): {youngest_ticker} ({youngest_date})")
    
    # Filtra dalla data di inizio backtest
    if not prices.empty:
        cutoff = pd.Timestamp(BACKTEST_START_DATE)
        if prices.index.tz is not None:
            cutoff = cutoff.tz_localize(prices.index.tz)
        before_filter = len(prices)
        prices = prices[prices.index >= cutoff]
        after_filter = len(prices)
        print(f"\n  Filtro dal {BACKTEST_START_DATE}: {before_filter} → {after_filter} settimane totali")
    
    obtained = list(prices.columns)
    missing = [t for t in all_tickers if t not in obtained]
    print(f"  Ottenuti: {len(obtained)}/{len(all_tickers)}")
    if missing:
        print(f"  Mancanti: {', '.join(missing)}")
    
    if prices.empty:
        print("ERRORE: nessun dato scaricato.", file=sys.stderr)
        sys.exit(1)
    
    print("\nCalcolo metriche USA...")
    us_metrics = compute_sector_metrics(prices, US_BENCHMARK, US_SECTORS)
    print(f"  {len(us_metrics)} settori USA elaborati")
    
    print("Calcolo metriche EU...")
    eu_metrics = compute_sector_metrics(prices, EU_BENCHMARK, EU_SECTORS)
    print(f"  {len(eu_metrics)} settori EU elaborati")
    
    print("\nCostruzione classifica di forza...")
    ranking_data = compute_sector_ranking(us_metrics, eu_metrics)
    print(f"  {len(ranking_data['ranking'])} settori classificati")
    if ranking_data.get('prev_snapshot_date'):
        print(f"  Confronto con snapshot del {ranking_data['prev_snapshot_date'][:10]}")
    
    print("\nCalcolo equity di portafoglio sistemico (1/N equipesato)...")
    all_sector_metrics = us_metrics + eu_metrics
    portfolio_equity = compute_portfolio_equity(all_sector_metrics, prices, ma_weeks=30)
    if portfolio_equity:
        print(f"  Sistema: {portfolio_equity['stats_system']['total_return']:+.1f}% "
              f"(CAGR {portfolio_equity['stats_system']['cagr']:+.1f}%, "
              f"MaxDD {portfolio_equity['stats_system']['max_drawdown']:.1f}%)")
        print(f"  B&H eq: {portfolio_equity['stats_bh']['total_return']:+.1f}% "
              f"(CAGR {portfolio_equity['stats_bh']['cagr']:+.1f}%, "
              f"MaxDD {portfolio_equity['stats_bh']['max_drawdown']:.1f}%)")
        print(f"  Tempo medio investito: {portfolio_equity['avg_pct_invested']}%")
    
    print("\nCalcolo griglia simulazione (dropdown TS interattivo)...")
    portfolio_simulation = compute_portfolio_simulation(all_sector_metrics, prices, ma_weeks=30)
    if portfolio_simulation:
        n_sec = len(portfolio_simulation['sectors'])
        n_dates = len(portfolio_simulation['dates'])
        n_def = portfolio_simulation['default_n_operational']
        print(f"  {n_sec} settori × {n_dates} settimane × {len(TS_OPTIONS)} opzioni TS")
        print(f"  Default operativi: {n_def} settori")
    else:
        print("  ⚠ Griglia simulazione non disponibile")
    
    # Rimuovi campi interni (_base_records) prima della serializzazione JSON
    def _strip_internal(metrics_list):
        for m in metrics_list:
            m.pop('_base_records', None)
    _strip_internal(us_metrics)
    _strip_internal(eu_metrics)
    
    last_data_date = prices.index[-1].strftime('%Y-%m-%d')
    
    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': last_data_date,
        'tickers_obtained': len(obtained),
        'tickers_total': len(all_tickers),
        'tickers_missing': missing,
        'us': {
            'benchmark': US_BENCHMARK,
            'benchmark_label': 'S&P 500',
            'sectors': us_metrics,
        },
        'eu': {
            'benchmark': EU_BENCHMARK,
            'benchmark_label': 'STOXX 600',
            'sectors': eu_metrics,
        },
        'ranking': ranking_data,
        'portfolio_equity': portfolio_equity,
        'portfolio_simulation': portfolio_simulation,
    }
    
    out_path = Path(__file__).parent.parent / 'data' / 'sector_data.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ Salvato in {out_path}")
    print(f"  Dimensione: {out_path.stat().st_size / 1024:.1f} KB")
    print(f"  Data ultimi dati: {last_data_date}")


if __name__ == '__main__':
    main()
