#!/usr/bin/env python3
"""
ADAPTIVE ENGINE — terza modalita' del sistema Azioni.

Identico a Balanced/Aggressive nella ROTATION dei settori e in TUTTA la meccanica
(equity, statistiche, weekly moves), ma la selezione del titolo dentro ogni settore
NON usa la lista statica curata: usa panieri PIT auto-aggiornati ogni 6 mesi
(top per dollar-volume) con filtro qualita' ROC13>0.

Onesto/point-in-time: ogni revisione semestrale usa solo dati fino a quella data.
Si auto-aggiorna: pesca i nuovi leader emergenti senza intervento manuale.

NON tocca update_stocks.py / produzione. Riusa run_backtest() via monkey-patch
della sola funzione di selezione, cosi' l'output e' IDENTICO al 100% agli altri
mode (stessa FASE 3, stesse stats) e non puo' divergere nel tempo.

USO: workflow_dispatch su GitHub Actions. Scrive data/adaptive_data.json.
"""
import json
import sys
import os
from datetime import datetime, timezone

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb


# ---------------------------------------------------------------------------
# Paniere point-in-time + filtro ROC13>0 (lo scenario vincente del backtest)
# ---------------------------------------------------------------------------
def basket_at(sec, dollar_vol, prices, w_idx):
    cands = sb.BASKETS.get(sec, [])
    lo = max(0, w_idx - sb.DV_LOOKBACK_WEEKS)
    scores = []
    for tk in cands:
        if tk not in dollar_vol.columns:
            continue
        window = dollar_vol[tk].iloc[lo:w_idx + 1].dropna()
        if len(window) < sb.DV_LOOKBACK_WEEKS // 2:
            continue
        avg_dv = float(window.mean())
        if avg_dv <= 0:
            continue
        # filtro qualita' ROC13>0 (point-in-time)
        if tk in prices.columns:
            s = prices[tk].iloc[:w_idx + 1].dropna()
            if len(s) < 14:
                continue
            roc13 = (s.iloc[-1] / s.iloc[-14] - 1) * 100
            if roc13 <= 0:
                continue
        scores.append((avg_dv, tk))
    scores.sort(reverse=True)
    return [tk for _, tk in scores[:sb.TOP_N]]


def review_index_for(date, dates):
    y = date.year
    cands = []
    for ry in (y - 1, y):
        for m in sb.REVIEW_MONTHS:
            rd = pd.Timestamp(year=ry, month=m, day=1)
            if rd <= date:
                cands.append(rd)
    if not cands:
        return 0
    return min(dates.searchsorted(max(cands)), len(dates) - 1)


# ---------------------------------------------------------------------------
# Selezione adattiva: stessa firma di select_best_at_week, ma universo = paniere PIT
# ---------------------------------------------------------------------------
_DOLLAR_VOL = None  # popolato in main
_REVIEW_CACHE = {}


def adaptive_select(sector_etf, prices_df, w_idx, universe, mode='balanced'):
    """
    Drop-in replacement di us.select_best_at_week.
    Ignora 'universe' (la lista statica) e usa il paniere PIT+roc valido alla
    revisione semestrale <= w_idx. Poi delega alla logica di scoring originale.
    """
    rev_idx = review_index_for(prices_df.index[w_idx], prices_df.index)
    key = (sector_etf, rev_idx)
    if key not in _REVIEW_CACHE:
        _REVIEW_CACHE[key] = basket_at(sector_etf, _DOLLAR_VOL, prices_df, rev_idx)
    pit_basket = _REVIEW_CACHE[key]
    if not pit_basket:
        return None
    # riusa la VERA funzione di selezione, ma con universo = paniere adattivo
    mini_uni = {sector_etf: pit_basket}
    return _ORIG_SELECT(sector_etf, prices_df, w_idx, mini_uni, mode=mode)


_ORIG_SELECT = us.select_best_at_week
_ORIG_HISTORY = us.extract_signal_history_full

# Stop-loss: soglia % sul close dall'ingresso (None = disattivato)
STOP_LOSS_PCT = 20.0
_PRICES_REF = None  # popolato in main, serve al patch della history


def history_with_stoploss(rrg, sec_prices, ma_weeks=30):
    """
    Wrapper di extract_signal_history_full: dopo aver ottenuto i periodi IN,
    per ciascuno individua il titolo che la selezione adattiva sceglierebbe,
    e se quel titolo sfonda -STOP_LOSS_PCT% sul close ACCORCIA il periodo IN
    alla settimana dello stop. Cosi' operations ED equity (che derivano entrambe
    dai periodi) vedono la stessa uscita anticipata: coerenza garantita.
    """
    periods = _ORIG_HISTORY(rrg, sec_prices, ma_weeks)
    if STOP_LOSS_PCT is None or _PRICES_REF is None:
        return periods

    # identifica il settore corrente dal nome della serie prezzi dell'ETF
    sec = getattr(sec_prices, 'name', None)
    if sec is None or sec not in sb.BASKETS:
        return periods  # non e' un settore operativo con bacino: nessuno stop

    dates = _PRICES_REF.index
    n = len(dates)
    new_periods = []
    for p in periods:
        if p['signal'] != 'IN':
            new_periods.append(p)
            continue
        # indici del periodo
        try:
            si = dates.get_loc(p['start_date'])
        except KeyError:
            si = dates.searchsorted(p['start_date'])
        try:
            ei = dates.get_loc(p['end_date'])
        except KeyError:
            ei = dates.searchsorted(p['end_date'])
        if si >= n or ei >= n or ei <= si:
            new_periods.append(p)
            continue

        # titolo selezionato all'ingresso (stessa logica adattiva)
        rev = review_index_for(dates[si], dates)
        key = (sec, rev)
        if key not in _REVIEW_CACHE:
            _REVIEW_CACHE[key] = basket_at(sec, _DOLLAR_VOL, _PRICES_REF, rev)
        bsk = _REVIEW_CACHE[key]
        if not bsk:
            new_periods.append(p)
            continue
        best = _ORIG_SELECT(sec, _PRICES_REF, si, {sec: bsk}, mode=_CURRENT_MODE)
        if best is None or best['ticker'] not in _PRICES_REF.columns:
            new_periods.append(p)
            continue

        tk = best['ticker']
        entry = _PRICES_REF[tk].iloc[si]
        if pd.isna(entry) or entry <= 0:
            new_periods.append(p)
            continue
        thresh = entry * (1 - STOP_LOSS_PCT / 100.0)

        # cerca la prima settimana in cui il close sfonda lo stop
        stop_w = None
        for w in range(si + 1, ei + 1):
            c = _PRICES_REF[tk].iloc[w]
            if not pd.isna(c) and c <= thresh:
                stop_w = w
                break

        if stop_w is not None:
            # accorcia il periodo: end_date = settimana dello stop
            p = dict(p)
            p['end_date'] = dates[stop_w]
        new_periods.append(p)

    return new_periods


_CURRENT_MODE = 'aggressive'


def build_full_output(prices, mode):
    """Chiama il VERO build_mode_output con selezione adattiva + stop-loss montati.
    Il doppio patch (select + history) garantisce stop coerente in operations ED equity."""
    global _PRICES_REF, _CURRENT_MODE
    _PRICES_REF = prices
    _CURRENT_MODE = mode
    us.select_best_at_week = adaptive_select       # patch selezione
    us.extract_signal_history_full = history_with_stoploss  # patch stop-loss
    try:
        result = us.build_mode_output(prices, us.SECTORS_SYSTEM, mode)
    finally:
        us.select_best_at_week = _ORIG_SELECT          # ripristino sempre
        us.extract_signal_history_full = _ORIG_HISTORY
    return result


def main():
    global _DOLLAR_VOL
    import yfinance as yf

    # universo da scaricare: bacini PIT + ETF + benchmark + cash + world
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK); tickers.add(us.EU_BENCHMARK)
    tickers.add(us.CASH_TICKER); tickers.add(us.WORLD_TICKER)
    tickers = sorted(tickers)
    print(f"[ADAPTIVE] scarico {len(tickers)} ticker da {us.BACKTEST_START}...")

    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = raw['Close']
    _DOLLAR_VOL = raw['Close'] * raw['Volume']
    print(f"[ADAPTIVE] prezzi: {prices.shape[1]} colonne x {prices.shape[0]} settimane")

    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': str(prices.index[-1].date()),
        'stock_names': getattr(us, 'STOCK_NAMES', {}),
        'mode_label': 'Adaptive',
        'modes': {},
    }
    # solo aggressive: l'Adaptive affianca l'Aggressive statico con la stessa filosofia momentum
    for mode in ('aggressive',):
        print(f"\n[ADAPTIVE·{mode}] backtest con panieri auto-aggiornati...")
        _REVIEW_CACHE.clear()
        result = build_full_output(prices, mode)
        out['modes'][mode] = result
        st = result.get('stats', {})
        print(f"  total {st.get('total_return')}% · CAGR {st.get('cagr')}% · "
              f"MaxDD {st.get('max_drawdown')}% · Sharpe {st.get('sharpe')} · "
              f"{st.get('n_operations_total')} op")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'adaptive_data.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[ADAPTIVE] scritto {path}")


if __name__ == '__main__':
    main()
