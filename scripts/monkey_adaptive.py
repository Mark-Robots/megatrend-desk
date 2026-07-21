#!/usr/bin/env python3
"""
MONKEY TEST · ADAPTIVE — test di permutazione sulla selezione titoli dell'Adaptive.

DOMANDA: a parita' di calendario settoriale RRG, panieri adattivi (top dollar-volume
+ ROC13>0, revisione semestrale, deduplicati) e stop-loss -20%, la scelta del titolo
di select_best_at_week (filosofia aggressive) batte una scelta CASUALE dal paniere?

DIFFERENZA CHIAVE vs monkey_test.py: qui l'uscita dipende dal titolo. Ogni candidato
del paniere ha il SUO stop-loss: la scimmia che pesca un titolo diverso esce quando
QUEL titolo tocca il -20% (o alla fine naturale del periodo IN, come nell'engine).
Per ogni periodo si precalcola quindi l'uscita effettiva di ciascun candidato.

Meccanica equity replicata da adaptive_engine.run_adaptive FASE 3 (1/N_MAX slots,
cash XEON sugli slot non attivi, contributo su w-1 in [start, end]).

LETTURA ONESTA: < 80° caso · 80-94° debole · >= 95° segnale (p <= 0.05).
Il calendario RRG e' in comune: il test valuta SOLO il picking, non la rotation.

Output: data/monkey_adaptive.json (stesso schema di monkey_test.json).
USO: workflow_dispatch. Config via env: MT_N (10000), MT_SEED (42).
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb
import adaptive_engine as ae

N_MONKEYS = int(os.environ.get('MT_N', '10000'))
SEED = int(os.environ.get('MT_SEED', '42'))
MODE = 'aggressive'          # l'Adaptive gira solo aggressive
STOP = ae.STOP_LOSS_PCT      # -20% come in produzione


# ---------------------------------------------------------------------------
# 1) OPERAZIONI: identiche a adaptive_engine.run_adaptive (FASE 1 + 2), ma per
#    ogni periodo si conserva il paniere con l'uscita stop-adjusted PER TICKER.
# ---------------------------------------------------------------------------
def stop_exit_for(prices, tk, start_idx, natural_exit):
    """Indice di uscita effettivo del ticker: stop -20% sul close, altrimenti
    uscita naturale del periodo (stessa scansione dell'engine)."""
    entry = prices[tk].iloc[start_idx]
    if pd.isna(entry) or entry <= 0:
        return None
    if STOP is None:
        return int(natural_exit), False
    thresh = float(entry) * (1 - STOP / 100.0)
    col = prices[tk]
    for w in range(start_idx + 1, natural_exit + 1):
        c = col.iloc[w]
        if not pd.isna(c) and c <= thresh:
            return int(w), True
    return int(natural_exit), False


def build_operations(prices, dollar_vol):
    dates = prices.index
    n_weeks = len(dates)
    last_data_date = dates[-1]

    sector_data = {}
    for sec in us.SECTORS_SYSTEM:
        if sec not in prices.columns:
            continue
        region = 'US' if sec in us.US_SECTORS_ETF else 'IT'
        bench = us.US_BENCHMARK if region == 'US' else us.EU_BENCHMARK
        if bench not in prices.columns:
            continue
        rrg = us.calculate_rrg(prices[sec].dropna(), prices[bench].dropna(), window=14)
        if rrg is None or rrg.empty:
            continue
        history = us.extract_signal_history_full(rrg, prices[sec].dropna(), ma_weeks=30)
        sector_data[sec] = [p for p in history if p['signal'] == 'IN']

    review_cache = {}
    operations = []
    for sec, in_periods in sector_data.items():
        for period in in_periods:
            sd, ed = period['start_date'], period['end_date']
            try:
                start_idx = dates.get_loc(sd)
            except KeyError:
                start_idx = dates.searchsorted(sd)
                if start_idx >= n_weeks:
                    continue
            try:
                end_idx = dates.get_loc(ed)
            except KeyError:
                end_idx = dates.searchsorted(ed)
                if end_idx >= n_weeks:
                    end_idx = n_weeks - 1

            rev = ae.review_index_for(dates[start_idx], dates)
            key = (sec, rev)
            if key not in review_cache:
                review_cache[key] = ae.basket_at(sec, dollar_vol, prices, rev)
            bsk = review_cache[key]
            if not bsk:
                continue

            best = us.select_best_at_week(sec, prices, start_idx, {sec: bsk}, mode=MODE)
            if best is None:
                continue
            strat_tk = best['ticker']
            if strat_tk not in prices.columns:
                continue

            is_open = (ed == last_data_date) or (end_idx == n_weeks - 1)
            natural_exit = end_idx if is_open else min(end_idx + 1, n_weeks - 1)

            # uscita stop-adjusted del titolo scelto dal sistema
            se = stop_exit_for(prices, strat_tk, start_idx, natural_exit)
            if se is None:
                continue
            strat_end, strat_stopped = se

            # candidati per le scimmie: stesso paniere, ognuno con la SUA uscita
            cands = []
            for tk in bsk:
                if tk not in prices.columns:
                    continue
                e = stop_exit_for(prices, tk, start_idx, natural_exit)
                if e is None:
                    continue
                cands.append((tk, e[0]))
            if not cands:
                continue

            operations.append({
                'sector_etf': sec,
                'start_idx': int(start_idx),
                'strat_tk': strat_tk,
                'strat_end': strat_end,
                'strat_stopped': strat_stopped,
                'cands': cands,
            })
    return operations


# ---------------------------------------------------------------------------
# 2) MOTORE EQUITY VETTORIALE — replica FASE 3 di run_adaptive:
#    week_ret[w] = pos_sum[w]/N_MAX + cash_ret[w]*(N_MAX - n_valid[w])/N_MAX,
#    con contributo dell'op alla settimana w se start <= w-1 <= end,
#    cioe' w in [start+1, end+1].
# ---------------------------------------------------------------------------
def returns_and_valid(prices, tickers):
    rets, valids = {}, {}
    sub = prices[list(tickers)]
    for tk in tickers:
        p = sub[tk].to_numpy(dtype=float)
        r = np.zeros(len(p))
        v = np.zeros(len(p))
        with np.errstate(invalid='ignore', divide='ignore'):
            rr = p[1:] / p[:-1] - 1.0
        ok = np.isfinite(rr) & (p[:-1] > 0)
        r[1:][ok] = rr[ok]
        v[1:][ok] = 1.0
        rets[tk] = r
        valids[tk] = v
    return rets, valids


def cash_returns(prices, n_weeks):
    c = np.zeros(n_weeks)
    if us.CASH_TICKER in prices.columns:
        p = prices[us.CASH_TICKER].to_numpy(dtype=float)
        with np.errstate(invalid='ignore', divide='ignore'):
            rr = p[1:] / p[:-1] - 1.0
        ok = np.isfinite(rr) & (p[:-1] > 0)
        c[1:][ok] = rr[ok]
    return c


def equity_metrics(ops, ends, tickers_of, rets, valids, cash, n_weeks, n_max, start_w):
    acc = np.zeros(n_weeks)
    cnt = np.zeros(n_weeks)
    for i, op in enumerate(ops):
        tk = tickers_of[i]
        lo = op['start_idx'] + 1
        hi = min(ends[i] + 1, n_weeks - 1) + 1   # settimane [start+1, end+1]
        acc[lo:hi] += rets[tk][lo:hi]
        cnt[lo:hi] += valids[tk][lo:hi]
    w0 = start_w + 1
    week_ret = acc[w0:] / n_max + cash[w0:] * (n_max - cnt[w0:]) / n_max
    eq = np.cumprod(1.0 + week_ret)
    n = len(eq)
    cagr = (eq[-1] ** (52.0 / n) - 1.0) * 100.0 if n else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1.0)) * 100.0 if n else 0.0
    return round(float(cagr), 2), round(mdd, 2)


# ---------------------------------------------------------------------------
# 3) TEST
# ---------------------------------------------------------------------------
def run_test(prices, dollar_vol, rng):
    ops = build_operations(prices, dollar_vol)
    if not ops:
        return None
    n_weeks = len(prices.index)
    n_max = len(us.SECTORS_SYSTEM)
    start_w = max(56, min(op['start_idx'] for op in ops))

    all_tk = set()
    for op in ops:
        all_tk.add(op['strat_tk'])
        all_tk.update(tk for tk, _ in op['cands'])
    rets, valids = returns_and_valid(prices, sorted(all_tk))
    cash = cash_returns(prices, n_weeks)

    strat_cagr, strat_mdd = equity_metrics(
        ops, [op['strat_end'] for op in ops], [op['strat_tk'] for op in ops],
        rets, valids, cash, n_weeks, n_max, start_w)
    n_stopped = sum(1 for op in ops if op['strat_stopped'])

    monkey_cagrs = np.empty(N_MONKEYS)
    monkey_mdds = np.empty(N_MONKEYS)
    monkey_stops = np.empty(N_MONKEYS)
    cand_lists = [op['cands'] for op in ops]
    nat_ends = {}   # per contare gli stop delle scimmie
    for m in range(N_MONKEYS):
        picks, ends, stops = [], [], 0
        for i, cl in enumerate(cand_lists):
            tk, e = cl[rng.integers(len(cl))]
            picks.append(tk)
            ends.append(e)
        c, d = equity_metrics(ops, ends, picks, rets, valids, cash,
                              n_weeks, n_max, start_w)
        monkey_cagrs[m] = c
        monkey_mdds[m] = d
        if (m + 1) % 1000 == 0:
            print(f"  {m+1}/{N_MONKEYS} scimmie...")

    below = int(np.sum(monkey_cagrs < strat_cagr))
    percentile = 100.0 * below / N_MONKEYS
    pval = (N_MONKEYS - below) / N_MONKEYS
    q = lambda p: float(np.quantile(monkey_cagrs, p))
    verdict = 'SEGNALE' if percentile >= 95 else ('DEBOLE' if percentile >= 80 else 'CASO')

    return {
        'strategy': {'cagr': strat_cagr, 'max_drawdown': strat_mdd,
                     'n_operations': len(ops), 'n_stop_loss': n_stopped,
                     'avg_basket_size': round(float(np.mean([len(c) for c in cand_lists])), 1)},
        'monkeys': {'n': N_MONKEYS, 'seed': SEED,
                    'cagr_median': round(q(0.5), 2),
                    'cagr_p05': round(q(0.05), 2),
                    'cagr_p95': round(q(0.95), 2),
                    'mdd_median': round(float(np.quantile(monkey_mdds, 0.5)), 2),
                    'mdd_worse_than_system_pct': round(
                        100.0 * float(np.mean(monkey_mdds < strat_mdd)), 1)},
        'percentile': round(percentile, 1),
        'p_value': round(pval, 4),
        'verdict': verdict,
        'monkey_cagrs': [round(float(x), 3) for x in monkey_cagrs],
    }


def main():
    import yfinance as yf
    removed = us.deduplicate_universes()
    if removed:
        print(f"[DEDUP] {len(removed)} titoli rimossi da settori duplicati")
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.update([us.US_BENCHMARK, us.EU_BENCHMARK, us.CASH_TICKER, us.WORLD_TICKER])
    tickers = sorted(tickers)
    print(f"[MONKEY·ADAPTIVE] scarico {len(tickers)} ticker da {us.BACKTEST_START}...")
    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = us.align_weekly_index(raw['Close'], us.BACKTEST_START)
    dollar_vol = us.align_weekly_index(raw['Close'] * raw['Volume'], us.BACKTEST_START)
    print(f"[MONKEY·ADAPTIVE] prezzi: {prices.shape[1]} x {prices.shape[0]} settimane")

    rng = np.random.default_rng(SEED)
    r = run_test(prices, dollar_vol, rng)
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'config': {'n_monkeys': N_MONKEYS, 'seed': SEED, 'mode': MODE,
                   'stop_loss_pct': STOP, 'top_n': sb.TOP_N,
                   'review_months': list(sb.REVIEW_MONTHS),
                   'dv_lookback_weeks': sb.DV_LOOKBACK_WEEKS,
                   'backtest_start': us.BACKTEST_START,
                   'quality': 'roc13>0 (paniere adattivo)',
                   'question': 'il picking Adaptive batte la scelta casuale dallo stesso paniere, a parita di stop-loss?'},
        'modes': {},
    }
    if r:
        out['modes']['adaptive'] = r
        s = r['strategy']; m = r['monkeys']
        print(f"\n  sistema CAGR {s['cagr']}% (MaxDD {s['max_drawdown']}%, "
              f"{s['n_operations']} op, {s['n_stop_loss']} stop) · "
              f"scimmie mediana {m['cagr_median']}% · "
              f"percentile {r['percentile']}° · p={r['p_value']} · {r['verdict']}")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'monkey_adaptive.json')
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    print(f"\n[MONKEY·ADAPTIVE] scritto {path}")


if __name__ == '__main__':
    main()
