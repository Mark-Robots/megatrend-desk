#!/usr/bin/env python3
"""
TEST STOP-LOSS sull'Adaptive (PIT + ROC>0).

Per ogni trade, oltre all'uscita per rotazione del settore (NO_BAD), controlla
se il prezzo di CHIUSURA settimanale scende sotto -SL% dal prezzo d'ingresso.
In tal caso chiude il trade a quel close (uscita anticipata per stop).

Confronta scenari: nessuno stop, -15%, -20%, -25%.
Mostra total return, n. di stop scattati, e se i mega-winner vengono tagliati.

NON tocca produzione. workflow_dispatch. Scrive data/stoploss_test.json.
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


def basket_at(sec, dollar_vol, prices, w_idx):
    """Paniere PIT + filtro ROC13>0 (config Adaptive)."""
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
    return min(dates.searchsorted(max(cands)), len(dates) - 1) if cands else 0


def run_with_sl(prices, dollar_vol, mode, sl_pct=None):
    """sl_pct = soglia stop (es. 15 = -15%). None = nessuno stop."""
    dates = prices.index
    n_weeks = len(dates)

    sector_data = {}
    for sec in us.SECTORS_SYSTEM:
        if sec not in prices.columns:
            continue
        region = 'US' if sec in us.US_SECTORS_ETF else 'IT'
        bench = us.US_BENCHMARK if region == 'US' else us.EU_BENCHMARK
        if bench not in prices.columns:
            continue
        rrg = us.calculate_rrg(prices[sec].dropna(), prices[bench].dropna(), 14)
        if rrg is None or rrg.empty:
            continue
        hist = us.extract_signal_history_full(rrg, prices[sec].dropna(), 30)
        sector_data[sec] = [p for p in hist if p['signal'] == 'IN']

    review_cache = {}
    trades = []
    n_stops = 0
    stopped_winners = []  # trade che lo stop ha chiuso ma che POI sarebbero risaliti

    for sec, periods in sector_data.items():
        for period in periods:
            sd, ed = period['start_date'], period['end_date']
            try:
                si = dates.get_loc(sd)
            except KeyError:
                si = dates.searchsorted(sd)
                if si >= n_weeks: continue
            try:
                ei = dates.get_loc(ed)
            except KeyError:
                ei = dates.searchsorted(ed)
                if ei >= n_weeks: ei = n_weeks - 1

            rev = review_index_for(dates[si], dates)
            key = (sec, rev)
            if key not in review_cache:
                review_cache[key] = basket_at(sec, dollar_vol, prices, rev)
            bsk = review_cache[key]
            if not bsk:
                continue
            best = us.select_best_at_week(sec, prices, si, {sec: bsk}, mode=mode)
            if best is None:
                continue
            tk = best['ticker']
            if tk not in prices.columns:
                continue
            entry = float(prices[tk].iloc[si])
            if pd.isna(entry) or entry <= 0:
                continue

            is_open = (ed == last_date_global) or (ei == n_weeks - 1)
            natural_exit = ei if is_open else min(ei + 1, n_weeks - 1)

            # --- controllo stop-loss sul close, settimana per settimana ---
            stop_idx = None
            if sl_pct is not None:
                thresh = entry * (1 - sl_pct / 100.0)
                for w in range(si + 1, natural_exit + 1):
                    c = prices[tk].iloc[w]
                    if not pd.isna(c) and c <= thresh:
                        stop_idx = w
                        break

            if stop_idx is not None:
                exit_idx = stop_idx
                n_stops += 1
                # il titolo sarebbe risalito dopo lo stop? (per capire se taglia winner)
                future = prices[tk].iloc[stop_idx:natural_exit + 1].dropna()
                if len(future) > 1 and future.iloc[-1] > entry:
                    stopped_winners.append((tk, round((future.iloc[-1]/entry-1)*100, 1)))
            else:
                exit_idx = natural_exit

            exitp = float(prices[tk].iloc[exit_idx])
            if pd.isna(exitp) or exitp <= 0:
                continue
            trades.append((exitp / entry - 1) * 100)

    raw = sum(trades)
    wins = [t for t in trades if t > 0]
    return {
        'sl': sl_pct,
        'raw_sum': round(raw, 0),
        'n_trades': len(trades),
        'n_stops': n_stops,
        'win_rate': round(len(wins)/len(trades)*100, 1) if trades else 0,
        'worst': round(min(trades), 1) if trades else 0,
        'stopped_winners': stopped_winners[:10],  # esempi di winner tagliati
        'n_stopped_winners': len(stopped_winners),
    }


last_date_global = None


def main():
    global last_date_global
    import yfinance as yf
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK); tickers.add(us.EU_BENCHMARK)
    tickers = sorted(tickers)
    print(f"[SL] scarico {len(tickers)} ticker...")
    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = raw['Close']
    dollar_vol = raw['Close'] * raw['Volume']
    last_date_global = prices.index[-1]
    print(f"[SL] prezzi: {prices.shape[1]} x {prices.shape[0]} settimane")

    out = {'generated_at': datetime.now(timezone.utc).isoformat(), 'modes': {}}
    for mode in ('aggressive',):
        out['modes'][mode] = {}
        print(f"\n=== {mode.upper()} ===")
        for sl in (None, 15, 20, 25):
            r = run_with_sl(prices, dollar_vol, mode, sl_pct=sl)
            out['modes'][mode][str(sl)] = r
            label = 'NO STOP' if sl is None else f'-{sl}%'
            print(f"  {label:8} raw {r['raw_sum']:>7}% · {r['n_trades']} trade · "
                  f"{r['n_stops']} stop · win {r['win_rate']}% · worst {r['worst']}% · "
                  f"winner tagliati: {r['n_stopped_winners']}")
            if r['stopped_winners']:
                print(f"           es. winner tagliati dallo stop: {r['stopped_winners'][:5]}")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'stoploss_test.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n[SL] scritto {path}")


if __name__ == '__main__':
    main()
