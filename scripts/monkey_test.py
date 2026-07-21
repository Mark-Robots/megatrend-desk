#!/usr/bin/env python3
"""
MONKEY TEST — test di permutazione sulla selezione dei titoli.

DOMANDA: a parita' di TUTTO il resto — calendario settoriale RRG (periodi IN/OUT),
panieri point-in-time (top-15 per dollar-volume, revisione semestrale), meccanica
di portafoglio (1/N slots, cash sui settori OUT) — la scelta del titolo fatta da
select_best_at_week batte una scelta CASUALE dallo stesso paniere?

COME: si costruiscono le operazioni del sistema esattamente come backtest_pit.py
(stessa FASE 1 e FASE 2). Poi si generano N_MONKEYS portafogli in cui ogni
operazione tiene lo STESSO settore, le STESSE date di ingresso/uscita e lo STESSO
paniere PIT, ma il ticker e' estratto a caso dal paniere. La distribuzione dei
CAGR casuali dice a quale percentile sta il sistema.

LETTURA ONESTA:
  < 80°  -> la selezione titolo e' indistinguibile dal caso
  80-94° -> segnale debole (potrebbe non sopravvivere ai costi)
  >= 95° -> evidenza di skill nella selezione (p <= 0.05)

NOTA: il test NON valuta il calendario settoriale RRG (che e' tenuto fisso,
quindi in comune tra sistema e scimmie). Valuta solo il valore aggiunto di
select_best_at_week rispetto al paniere da cui pesca.

Output: data/monkey_test.json (per ciascun mode: balanced, aggressive).
USO: workflow_dispatch su GitHub Actions (serve Yahoo Finance).
Config via env: MT_N (default 10000), MT_SEED (42), MT_QUALITY (roc), MT_ROC_MIN (0).
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
import backtest_pit as bp

N_MONKEYS = int(os.environ.get('MT_N', '10000'))
SEED = int(os.environ.get('MT_SEED', '42'))
QUALITY = os.environ.get('MT_QUALITY', 'roc') or None
ROC_MIN = float(os.environ.get('MT_ROC_MIN', '0'))
MODES = ('balanced', 'aggressive')


# ---------------------------------------------------------------------------
# 1) OPERAZIONI DEL SISTEMA — identiche a backtest_pit.run_pit (FASE 1 + 2),
#    ma ogni operazione conserva anche il paniere PIT completo.
# ---------------------------------------------------------------------------
def build_operations(prices, dollar_vol, mode):
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
        history = us.extract_signal_history_full(rrg, prices[sec].dropna(), 30)
        sector_data[sec] = [p for p in history if p['signal'] == 'IN']

    operations = []
    review_cache = {}
    for sec, in_periods in sector_data.items():
        for period in in_periods:
            sd, ed = period['start_date'], period['end_date']
            try:
                si = dates.get_loc(sd)
            except KeyError:
                si = dates.searchsorted(sd)
                if si >= n_weeks:
                    continue
            try:
                ei = dates.get_loc(ed)
            except KeyError:
                ei = dates.searchsorted(ed)
                if ei >= n_weeks:
                    ei = n_weeks - 1

            rev_idx = bp.review_index_for(dates[si], dates)
            key = (sec, rev_idx)
            if key not in review_cache:
                review_cache[key] = bp.basket_at(
                    sec, dollar_vol, rev_idx,
                    prices=prices, quality=QUALITY, roc_min=ROC_MIN)
            basket = review_cache[key]
            if not basket:
                continue

            best = us.select_best_at_week(sec, prices, si, {sec: basket}, mode=mode)
            if best is None:
                continue
            tk = best['ticker']
            if tk not in prices.columns:
                continue
            entry = prices[tk].iloc[si]
            if pd.isna(entry) or entry <= 0:
                continue

            # candidati validi per le scimmie: stesso paniere, prezzo valido all'ingresso
            cands = [c for c in basket
                     if c in prices.columns
                     and not pd.isna(prices[c].iloc[si])
                     and prices[c].iloc[si] > 0]
            if not cands:
                continue

            operations.append({
                'sector_etf': sec,
                'ticker': tk,
                'entry_date': str(dates[si].date()),
                'start_idx': int(si),
                'end_idx': int(ei),
                'basket': cands,
            })
    return operations


# ---------------------------------------------------------------------------
# 2) MOTORE EQUITY VETTORIALE — stessa meccanica della FASE 3 di backtest_pit:
#    rendimento settimana w = somma contributi delle op attive / N_SLOTS,
#    contributo op = ret settimanale del ticker per w in (start_idx, end_idx].
# ---------------------------------------------------------------------------
def weekly_returns_matrix(prices, tickers):
    """dict ticker -> np.array dei rendimenti settimanali, NaN -> 0 (stessa
    guardia della FASE 3: se p0 o p1 mancano il contributo e' zero)."""
    out = {}
    arr = prices[list(tickers)].to_numpy(dtype=float)
    cols = {tk: i for i, tk in enumerate(prices[list(tickers)].columns)}
    for tk in tickers:
        p = arr[:, cols[tk]]
        r = np.zeros(len(p))
        with np.errstate(invalid='ignore', divide='ignore'):
            rr = p[1:] / p[:-1] - 1.0
        valid = np.isfinite(rr) & (p[:-1] > 0)
        r[1:][valid] = rr[valid]
        out[tk] = r
    return out


def equity_metrics(ops, tickers_of, rets, n_weeks, n_slots, start_w):
    """CAGR% e MaxDD% dell'equity per una assegnazione ticker->operazioni."""
    acc = np.zeros(n_weeks)
    for i, op in enumerate(ops):
        tk = tickers_of[i]
        lo, hi = op['start_idx'] + 1, op['end_idx'] + 1  # w in (start, end]
        acc[lo:hi] += rets[tk][lo:hi]
    port = 1.0 + acc[start_w:] / n_slots
    eq = np.cumprod(port)
    n = len(eq)
    cagr = (eq[-1] ** (52.0 / n) - 1.0) * 100.0 if n else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1.0)) * 100.0 if n else 0.0
    return round(float(cagr), 2), round(mdd, 2), round(float(eq[-1] * 100), 1)


# ---------------------------------------------------------------------------
# 3) TEST
# ---------------------------------------------------------------------------
def run_mode(prices, dollar_vol, mode, rng):
    ops = build_operations(prices, dollar_vol, mode)
    if not ops:
        return None
    n_weeks = len(prices.index)
    n_slots = len(us.SECTORS_SYSTEM)
    start_w = max(56, min(op['start_idx'] for op in ops))

    all_tickers = set()
    for op in ops:
        all_tickers.update(op['basket'])
        all_tickers.add(op['ticker'])
    rets = weekly_returns_matrix(prices, sorted(all_tickers))

    strat_cagr, strat_mdd, strat_eq = equity_metrics(
        ops, [op['ticker'] for op in ops], rets, n_weeks, n_slots, start_w)

    monkey_cagrs = np.empty(N_MONKEYS)
    monkey_mdds = np.empty(N_MONKEYS)
    baskets = [op['basket'] for op in ops]
    for m in range(N_MONKEYS):
        picks = [b[rng.integers(len(b))] for b in baskets]
        c, d, _ = equity_metrics(ops, picks, rets, n_weeks, n_slots, start_w)
        monkey_cagrs[m] = c
        monkey_mdds[m] = d
        if (m + 1) % 1000 == 0:
            print(f"  [{mode}] {m+1}/{N_MONKEYS} scimmie...")

    below = int(np.sum(monkey_cagrs < strat_cagr))
    percentile = 100.0 * below / N_MONKEYS
    pval = (N_MONKEYS - below) / N_MONKEYS
    q = lambda p: float(np.quantile(monkey_cagrs, p))

    if percentile >= 95:
        verdict = 'SEGNALE'
    elif percentile >= 80:
        verdict = 'DEBOLE'
    else:
        verdict = 'CASO'

    n_open = sum(1 for op in ops if op['end_idx'] >= n_weeks - 1)
    return {
        'strategy': {'cagr': strat_cagr, 'max_drawdown': strat_mdd,
                     'equity_last': strat_eq, 'n_operations': len(ops),
                     'n_open': n_open,
                     'avg_basket_size': round(float(np.mean([len(b) for b in baskets])), 1)},
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
    prices, dollar_vol = bp.fetch_prices_and_volumes()
    rng = np.random.default_rng(SEED)
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'config': {'n_monkeys': N_MONKEYS, 'seed': SEED,
                   'quality': QUALITY, 'roc_min': ROC_MIN,
                   'top_n': sb.TOP_N, 'review_months': list(sb.REVIEW_MONTHS),
                   'dv_lookback_weeks': sb.DV_LOOKBACK_WEEKS,
                   'backtest_start': us.BACKTEST_START,
                   'question': 'select_best_at_week batte la scelta casuale dallo stesso paniere PIT?'},
        'modes': {},
    }
    for mode in MODES:
        print(f"\n[MONKEY] === {mode} ===")
        r = run_mode(prices, dollar_vol, mode, rng)
        if r is None:
            print(f"  [{mode}] nessuna operazione, salto")
            continue
        out['modes'][mode] = r
        print(f"  sistema CAGR {r['strategy']['cagr']}% · "
              f"scimmie mediana {r['monkeys']['cagr_median']}% · "
              f"percentile {r['percentile']}° · p={r['p_value']} · {r['verdict']}")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'monkey_test.json')
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    print(f"\n[MONKEY] scritto {path}")


if __name__ == '__main__':
    main()
