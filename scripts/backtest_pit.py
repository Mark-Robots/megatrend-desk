#!/usr/bin/env python3
"""
BACKTEST POINT-IN-TIME — selezione semestrale dei titoli per dollar-volume.

OBIETTIVO: misurare quanto del risultato del sistema Azioni e' merito della logica
(rotation + momentum) e quanto era selection bias (lista curata col senno di poi).

COME: identica logica di rotation dei settori (NO_BAD / RRG) e identica scelta del
titolo (select_best_at_week), MA il paniere dei candidati di ogni settore NON e' la
lista statica curata: e' ricalcolato ogni 6 mesi (gen/lug) pescando i TOP_N titoli
per DOLLAR-VOLUME medio nei 6 mesi precedenti quella data. Tutto point-in-time:
ogni revisione usa solo dati fino a quella data -> nessun senno di poi.

NON tocca update_stocks.py / produzione. Gira separato e scrive data/backtest_pit.json.

USO: workflow_dispatch su GitHub Actions (serve Yahoo Finance).
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
# 1) FETCH: scarica prezzi E volumi di tutto il bacino + ETF/benchmark/cash/world
# ---------------------------------------------------------------------------
def fetch_prices_and_volumes():
    import yfinance as yf
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    # settori operativi (ETF) + benchmark + cash + world servono per la rotation
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK)
    tickers.add(us.EU_BENCHMARK)
    tickers.add(us.CASH_TICKER)
    tickers.add(us.WORLD_TICKER)
    tickers = sorted(tickers)
    print(f"[PIT] scarico {len(tickers)} ticker da {us.BACKTEST_START}...")

    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    close = raw['Close']
    vol = raw['Volume']
    # dollar-volume settimanale = close * volume
    dollar_vol = close * vol
    print(f"[PIT] prezzi: {close.shape[1]} colonne x {close.shape[0]} settimane")
    return close, dollar_vol


# ---------------------------------------------------------------------------
# 2) PANIERE POINT-IN-TIME: dato un indice settimana, per ogni settore ritorna
#    i TOP_N titoli per dollar-volume medio nelle DV_LOOKBACK_WEEKS precedenti.
# ---------------------------------------------------------------------------
def basket_at(sec, dollar_vol, w_idx, prices=None, quality=None, roc_min=0.0):
    """
    Paniere point-in-time: top TOP_N per dollar-volume medio nelle ultime
    DV_LOOKBACK_WEEKS settimane PRIMA di w_idx.

    quality (filtro qualita', point-in-time):
      None  -> nessun filtro (solo dollar-volume)
      'ma'  -> il titolo deve essere SOPRA la sua media mobile 30w a w_idx (trend up)
      'rs'  -> il titolo deve battere l'ETF di settore negli ultimi 26w (forza relativa)
      'roc' -> il titolo deve avere ROC13 > roc_min a w_idx (momentum sopra soglia)
    """
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

        # ---- filtro qualita' (usa solo dati fino a w_idx: point-in-time) ----
        if quality and prices is not None and tk in prices.columns:
            s = prices[tk].iloc[:w_idx + 1].dropna()
            if len(s) < 40:
                continue
            if quality == 'ma':
                ma = s.iloc[-30:].mean()
                if s.iloc[-1] <= ma:
                    continue
            elif quality == 'roc':
                if len(s) < 14:
                    continue
                roc13 = (s.iloc[-1] / s.iloc[-14] - 1) * 100
                if roc13 <= roc_min:
                    continue
            elif quality == 'rs':
                if sec not in prices.columns:
                    continue
                etf = prices[sec].iloc[:w_idx + 1].dropna()
                if len(etf) < 27 or len(s) < 27:
                    continue
                stock_ret = s.iloc[-1] / s.iloc[-27] - 1
                etf_ret = etf.iloc[-1] / etf.iloc[-27] - 1
                if stock_ret <= etf_ret:
                    continue

        scores.append((avg_dv, tk))
    scores.sort(reverse=True)
    return [tk for _, tk in scores[:sb.TOP_N]]


def review_index_for(date, dates):
    """Indice dell'ultima revisione semestrale (gen/lug) <= date."""
    # trova la revisione valida: 1 gennaio o 1 luglio dell'anno, la piu' recente <= date
    y = date.year
    candidates = []
    for ry in (y - 1, y):
        for m in sb.REVIEW_MONTHS:
            rd = pd.Timestamp(year=ry, month=m, day=1)
            if rd <= date:
                candidates.append(rd)
    if not candidates:
        return 0
    rd = max(candidates)
    idx = dates.searchsorted(rd)
    return min(idx, len(dates) - 1)


# ---------------------------------------------------------------------------
# 3) BACKTEST: replica fedele di run_backtest FASE 2+3, ma paniere = PIT
# ---------------------------------------------------------------------------
def run_pit(prices, dollar_vol, mode, quality=None, roc_min=0.0):
    dates = prices.index
    n_weeks = len(dates)

    # FASE 1 — rotation dei settori (identica all'originale)
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
        history = us.extract_signal_history_full(rrg, prices[sec].dropna(), 30)
        in_periods = [p for p in history if p['signal'] == 'IN']
        sector_data[sec] = {'region': region, 'in_periods': in_periods}

    # FASE 2 — un'operazione per periodo IN, con paniere POINT-IN-TIME
    operations = []
    last_date = dates[-1]
    review_cache = {}

    for sec, data in sector_data.items():
        region = data['region']
        for period in data['in_periods']:
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

            # paniere valido alla data di INGRESSO (ultima revisione semestrale <= start)
            rev_idx = review_index_for(dates[si], dates)
            key = (sec, rev_idx)
            if key not in review_cache:
                review_cache[key] = basket_at(sec, dollar_vol, rev_idx, prices=prices, quality=quality, roc_min=roc_min)
            pit_basket = review_cache[key]
            if not pit_basket:
                continue

            # selezione titolo: stessa funzione di produzione, universo = paniere PIT
            mini_uni = {sec: pit_basket}
            best = us.select_best_at_week(sec, prices, si, mini_uni, mode=mode)
            if best is None:
                continue
            tk = best['ticker']
            if tk not in prices.columns:
                continue
            entry = float(prices[tk].iloc[si])
            if pd.isna(entry) or entry <= 0:
                continue

            is_open = (ed == last_date) or (ei == n_weeks - 1)
            exit_idx = ei if is_open else min(ei + 1, n_weeks - 1)
            exitp = float(prices[tk].iloc[exit_idx])
            if pd.isna(exitp) or exitp <= 0:
                continue
            perf = (exitp / entry - 1) * 100
            weeks_held = (exit_idx - si + 1) if is_open else (exit_idx - si)

            operations.append({
                'sector_etf': sec, 'ticker': tk, 'region': region,
                'entry_date': str(dates[si].date()),
                'exit_date': None if is_open else str(dates[exit_idx].date()),
                'entry_price': round(entry, 4), 'exit_price': round(exitp, 4),
                'perf_pct': round(perf, 2), 'weeks_held': int(weeks_held),
                'status': 'open' if is_open else 'closed',
                'pit_basket_size': len(pit_basket),
                '_start_idx': si, '_end_idx': ei,
            })

    # FASE 3 — equity curve (stessa meccanica dell'originale)
    cash_series = prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    world_series = prices[us.WORLD_TICKER] if us.WORLD_TICKER in prices.columns else None
    portfolio = 100.0; world_v = 100.0
    start_w = max(56, min((op['_start_idx'] for op in operations), default=56))
    equity = []
    N_SLOTS = len(us.SECTORS_SYSTEM)

    for w in range(start_w, n_weeks):
        # rendimento settimanale del portafoglio = media dei rendimenti delle posizioni attive
        wk_ret = 0.0; active = 0
        for op in operations:
            if op['_start_idx'] <= w <= op['_end_idx'] and op['_start_idx'] < w:
                tk = op['ticker']
                p0 = prices[tk].iloc[w - 1]; p1 = prices[tk].iloc[w]
                if p0 and p1 and p0 > 0 and not pd.isna(p0) and not pd.isna(p1):
                    wk_ret += (p1 / p0 - 1); active += 1
        # peso fisso 1/N: i settori non attivi sono in cash (rendimento ~0 settimanale)
        port_week = wk_ret / N_SLOTS if N_SLOTS else 0.0
        portfolio *= (1 + port_week)
        if world_series is not None and w > 0:
            w0 = world_series.iloc[w - 1]; w1 = world_series.iloc[w]
            if w0 and w1 and w0 > 0 and not pd.isna(w0) and not pd.isna(w1):
                world_v *= (w1 / w0)
        equity.append({'date': str(dates[w].date()), 'system': round(portfolio, 2),
                       'world': round(world_v, 2), 'n_positions': active})

    # statistiche
    closed = [o for o in operations if o['status'] == 'closed']
    perfs = [o['perf_pct'] for o in closed]
    wins = [p for p in perfs if p > 0]
    tot_ret = portfolio - 100
    n = len(equity)
    cagr = ((portfolio / 100) ** (52 / n) - 1) * 100 if n > 0 else 0
    peak = 100; mdd = 0
    for e in equity:
        peak = max(peak, e['system']); mdd = min(mdd, (e['system'] / peak - 1) * 100)
    rets = [equity[i]['system'] / equity[i-1]['system'] - 1 for i in range(1, len(equity))]
    sharpe = (np.mean(rets) / (np.std(rets) or 1e-9) * np.sqrt(52)) if rets else 0

    return {
        'total_return': round(tot_ret, 1),
        'world_total_return': round(world_v - 100, 1),
        'cagr': round(cagr, 2),
        'max_drawdown': round(mdd, 1),
        'sharpe': round(sharpe, 2),
        'n_operations': len(operations),
        'n_closed': len(closed),
        'win_rate': round(len(wins) / len(closed) * 100, 1) if closed else 0,
        'top5_share': round(sum(sorted(perfs, reverse=True)[:5]) / sum(perfs) * 100, 1) if sum(perfs) > 0 else 0,
        'equity_last': round(portfolio, 1),
        # elenco operazioni per confronto settore-per-settore (statico vs PIT)
        'operations': [{
            'sector_etf': o['sector_etf'],
            'ticker': o['ticker'],
            'region': o['region'],
            'entry_date': o['entry_date'],
            'exit_date': o['exit_date'],
            'perf_pct': o['perf_pct'],
            'weeks_held': o['weeks_held'],
            'status': o['status'],
        } for o in operations],
    }


def main():
    prices, dollar_vol = fetch_prices_and_volumes()
    # test soglie ROC crescenti per vedere se DG/DLTR spariscono e cosa fa il totale
    SCENARIOS = [('roc0', 'roc', 0.0), ('roc5', 'roc', 5.0), ('roc10', 'roc', 10.0)]
    out = {'generated_at': datetime.now(timezone.utc).isoformat(),
           'config': {'top_n': sb.TOP_N, 'review_months': list(sb.REVIEW_MONTHS),
                      'lookback_weeks': sb.DV_LOOKBACK_WEEKS,
                      'n_candidates': sum(len(v) for v in sb.BASKETS.values()),
                      'scenarios': [s[0] for s in SCENARIOS]},
           'scenarios': {}}

    for label, q, rmin in SCENARIOS:
        out['scenarios'][label] = {'modes': {}}
        for mode in ('balanced', 'aggressive'):
            print(f"\n[PIT·{label}] === {mode} ===")
            r = run_pit(prices, dollar_vol, mode, quality=q, roc_min=rmin)
            out['scenarios'][label]['modes'][mode] = r
            xlp = [o for o in r['operations'] if o['sector_etf'] == 'XLP' and o['status'] == 'closed']
            xlp_sum = sum(o['perf_pct'] for o in xlp)
            # traccia DG e DLTR
            dgdltr = [o for o in r['operations'] if o['ticker'] in ('DG', 'DLTR')]
            dg_str = ', '.join(f"{o['ticker']}{o['perf_pct']:+.0f}%" for o in dgdltr) or 'nessuno'
            print(f"  total {r['total_return']:>7}% · Consumi {xlp_sum:+.0f}% · Sharpe {r['sharpe']} · DG/DLTR: {dg_str}")

    print(f"\n{'='*64}\nRIASSUNTO soglie ROC (aggressive)\n{'='*64}")
    for label, _, rmin in SCENARIOS:
        r = out['scenarios'][label]['modes']['aggressive']
        xlp = sum(o['perf_pct'] for o in r['operations'] if o['sector_etf'] == 'XLP' and o['status'] == 'closed')
        dgdltr = [o for o in r['operations'] if o['ticker'] in ('DG', 'DLTR')]
        dg_str = ', '.join(f"{o['ticker']}{o['perf_pct']:+.0f}%" for o in dgdltr) or 'NESSUNO'
        print(f"  ROC>{rmin:>4.0f}%  total {r['total_return']:>7}% · Consumi {xlp:+.0f}% · Sharpe {r['sharpe']} · DG/DLTR: {dg_str}")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'backtest_pit.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n[PIT] scritto {path}")


if __name__ == '__main__':
    main()
