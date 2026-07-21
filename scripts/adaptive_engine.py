#!/usr/bin/env python3
"""
ADAPTIVE ENGINE — terza modalita' del sistema Azioni (con stop-loss -20%).

Selezione titoli auto-aggiornata ogni 6 mesi (top dollar-volume + ROC13>0),
filosofia 'aggressive'. Stop-loss fisso -20% sul close, integrato nel punto
GIUSTO: dopo la selezione del titolo, durante la gestione del trade, cosi'
operations ed equity usano lo STESSO exit (coerenza per costruzione).

Engine AUTONOMO: replica FASE 2 (operations) e FASE 3 (equity) di run_backtest
ma con lo stop integrato. Riusa le funzioni helper di update_stocks (calculate_rrg,
extract_signal_history_full, compute_statistics, select_best_at_week, compute_roc,
classify_stage, assign_tag) senza patcharle -> niente fragilita'.

NON tocca produzione. workflow_dispatch. Scrive data/adaptive_data.json.
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

STOP_LOSS_PCT = 20.0   # None per disattivare


# --- paniere PIT + ROC>0 -----------------------------------------------------
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


# --- backtest autonomo con stop-loss nel punto giusto ------------------------
def run_adaptive(prices, dollar_vol, mode):
    dates = prices.index
    n_weeks = len(dates)
    last_data_date = dates[-1]

    # FASE 1: rotation settori (identica a produzione)
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
        in_periods = [p for p in history if p['signal'] == 'IN']
        sector_data[sec] = {'region': region, 'in_periods': in_periods}

    review_cache = {}
    operations = []

    # FASE 2: un'operazione per periodo IN, con paniere adattivo e STOP-LOSS
    for sec, data in sector_data.items():
        region = data['region']
        for period in data['in_periods']:
            sd, ed = period['start_date'], period['end_date']
            try:
                start_idx = dates.get_loc(sd)
            except KeyError:
                start_idx = dates.searchsorted(sd)
                if start_idx >= n_weeks: continue
            try:
                end_idx = dates.get_loc(ed)
            except KeyError:
                end_idx = dates.searchsorted(ed)
                if end_idx >= n_weeks: end_idx = n_weeks - 1

            rev = review_index_for(dates[start_idx], dates)
            key = (sec, rev)
            if key not in review_cache:
                review_cache[key] = basket_at(sec, dollar_vol, prices, rev)
            bsk = review_cache[key]
            if not bsk:
                continue

            best = us.select_best_at_week(sec, prices, start_idx, {sec: bsk}, mode=mode)
            if best is None:
                continue
            tk = best['ticker']
            if tk not in prices.columns:
                continue
            entry_price = float(prices[tk].iloc[start_idx])
            if pd.isna(entry_price) or entry_price <= 0:
                continue

            is_open = (ed == last_data_date) or (end_idx == n_weeks - 1)
            natural_exit = end_idx if is_open else min(end_idx + 1, n_weeks - 1)

            # --- STOP-LOSS: conosco titolo ed entry, e' il punto giusto ---
            stop_idx = None
            if STOP_LOSS_PCT is not None:
                thresh = entry_price * (1 - STOP_LOSS_PCT / 100.0)
                for w in range(start_idx + 1, natural_exit + 1):
                    c = prices[tk].iloc[w]
                    if not pd.isna(c) and c <= thresh:
                        stop_idx = w
                        break

            if stop_idx is not None:
                exit_idx = stop_idx
                eff_open = False
                exit_reason = 'stop_loss'
            else:
                exit_idx = natural_exit
                eff_open = is_open
                exit_reason = 'rotation'

            exit_price = float(prices[tk].iloc[exit_idx])
            if pd.isna(exit_price) or exit_price <= 0:
                continue
            perf = (exit_price / entry_price - 1) * 100
            weeks_held = (exit_idx - start_idx + 1) if eff_open else (exit_idx - start_idx)

            operations.append({
                'sector_etf': sec, 'sector_name': us.SECTOR_NAMES.get(sec, sec),
                'region': region, 'ticker': tk,
                'entry_date': str(dates[start_idx].date()),
                'exit_date': None if eff_open else str(dates[exit_idx].date()),
                'entry_price': round(entry_price, 4),
                'exit_price': round(exit_price, 4),
                'perf_pct': round(perf, 2),
                'weeks_held': int(weeks_held),
                'status': 'open' if eff_open else 'closed',
                'exit_reason': exit_reason,
                'entry_tag': best.get('tag'),
                'entry_state': period.get('start_state'),
                'entry_stage': period.get('start_stage'),
                'exit_state': period.get('end_state'),
                'exit_stage': period.get('end_stage'),
                '_start_idx': start_idx,
                '_end_idx': exit_idx,
            })

    # FASE 3: equity curve (stessa meccanica di produzione)
    cash_series = prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    world_series = prices[us.WORLD_TICKER] if us.WORLD_TICKER in prices.columns else None
    portfolio = 100.0; cash_v = 100.0; world_v = 100.0
    N_MAX = len(us.SECTORS_SYSTEM)
    start_w = max(56, min((op['_start_idx'] for op in operations), default=56))
    equity_curve = []

    for w in range(start_w, n_weeks):
        date = dates[w]
        if w > start_w:
            active_at_open = [op for op in operations
                              if op['_start_idx'] <= w - 1 and op['_end_idx'] >= w - 1]
            cash_ret_week = 0.0
            if cash_series is not None and w < len(cash_series):
                pc = cash_series.iloc[w - 1]; cc = cash_series.iloc[w]
                if not pd.isna(pc) and not pd.isna(cc) and pc > 0:
                    cash_ret_week = (cc / pc - 1); cash_v *= (cc / pc)
            pos_sum_ret = 0.0; n_valid = 0
            for op in active_at_open:
                tk = op['ticker']
                if tk not in prices.columns: continue
                pp = prices[tk].iloc[w - 1]; cp = prices[tk].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp == 0: continue
                pos_sum_ret += (cp / pp - 1); n_valid += 1
            week_ret = (pos_sum_ret / N_MAX) + cash_ret_week * (N_MAX - n_valid) / N_MAX
            portfolio *= (1 + week_ret)
            if world_series is not None and w < len(world_series):
                pw = world_series.iloc[w - 1]; cw = world_series.iloc[w]
                if not pd.isna(pw) and not pd.isna(cw) and pw > 0:
                    world_v *= (cw / pw)
        active_now = [op for op in operations if op['_start_idx'] <= w <= op['_end_idx']]
        pos_ret_sum_w = 0.0; n_active_w = 0
        if w > start_w:
            for op in [o for o in operations if o['_start_idx'] <= w - 1 and o['_end_idx'] >= w - 1]:
                tk = op['ticker']
                if tk not in prices.columns: continue
                pp = prices[tk].iloc[w - 1]; cp = prices[tk].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp == 0: continue
                pos_ret_sum_w += (cp / pp - 1); n_active_w += 1
        equity_curve.append({
            'date': str(date.date()), 'system': round(portfolio, 4),
            'cash': round(cash_v, 4), 'world': round(world_v, 4),
            'n_positions': len(active_now),
            'pos_ret_sum': round(pos_ret_sum_w, 6), 'n_active_for_ret': n_active_w,
        })

    current_pins = {}
    for op in operations:
        if op['status'] == 'open':
            current_pins[op['sector_etf']] = {
                'ticker': op['ticker'], 'entry_date': op['entry_date'],
                'entry_price': op['entry_price'], 'weeks_held': op['weeks_held'],
                'region': op['region'], 'entry_tag': op.get('entry_tag'),
                'entry_state': op.get('entry_state'), 'entry_stage': op.get('entry_stage'),
            }
    for op in operations:
        op.pop('_start_idx', None); op.pop('_end_idx', None)

    return {'equity_curve': equity_curve, 'operations': operations, 'current_pins': current_pins}


def build_full_output(prices, dollar_vol, mode):
    result = run_adaptive(prices, dollar_vol, mode)
    stats = us.compute_statistics(result['equity_curve'], result['operations'])
    last_date = result['equity_curve'][-1]['date'] if result['equity_curve'] else None

    current_list = []
    for sec, pin in result['current_pins'].items():
        tk = pin['ticker']
        if tk not in prices.columns: continue
        s = prices[tk].dropna()
        if s.empty: continue
        cp = float(s.iloc[-1])
        roc13 = us.compute_roc(s, 13); roc52 = us.compute_roc(s, 52)
        stage = us.classify_stage(s)
        perf = (cp / pin['entry_price'] - 1) * 100 if pin['entry_price'] > 0 else 0
        current_list.append({
            'sector_etf': sec, 'sector_name': us.SECTOR_NAMES.get(sec, sec),
            'region': pin['region'], 'ticker': tk, 'entry_date': pin['entry_date'],
            'entry_price': round(pin['entry_price'], 4), 'current_price': round(cp, 4),
            'perf_pct': round(perf, 2), 'weeks_held': pin['weeks_held'],
            'roc13w': roc13, 'roc52w': roc52, 'stage': stage,
            'tag': us.assign_tag(roc13, roc52),
        })

    buys = [op for op in result['operations'] if op.get('entry_date') == last_date and op['status'] == 'open']
    sells = [op for op in result['operations'] if op.get('exit_date') == last_date and op['status'] == 'closed']

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
    import yfinance as yf
    # Deduplica i panieri PRIMA di usarli: nessun titolo in due settori operativi
    # (stessa dedup di update_stocks; pulisce sb.BASKETS usati qui sotto).
    removed = us.deduplicate_universes()
    if removed:
        print(f"[DEDUP] {len(removed)} titoli rimossi da settori duplicati:")
        for tk, tolto_da, tenuto_da in removed:
            print(f"  {tk}: rimosso da {tolto_da} (resta in {tenuto_da})")
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
    dollar_vol = raw['Close'] * raw['Volume']
    # Allineo alla STESSA griglia W-FRI + remap calendari di update_stocks,
    # così Adaptio, Azioni ed ETF condividono ESATTAMENTE gli stessi giorni IN/OUT.
    print("[ADAPTIVE] allineo date alla griglia settimanale di update_stocks...")
    prices = us.align_weekly_index(prices, us.BACKTEST_START)
    dollar_vol = us.align_weekly_index(dollar_vol, us.BACKTEST_START)
    print(f"[ADAPTIVE] prezzi: {prices.shape[1]} x {prices.shape[0]} settimane")

    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': str(prices.index[-1].date()),
        'stock_names': getattr(us, 'STOCK_NAMES', {}),
        'mode_label': 'Adaptive',
        'stop_loss_pct': STOP_LOSS_PCT,
        'modes': {},
    }
    for mode in ('aggressive',):
        print(f"\n[ADAPTIVE.{mode}] backtest panieri auto-aggiornati + stop-loss {STOP_LOSS_PCT}%...")
        r = build_full_output(prices, dollar_vol, mode)
        out['modes'][mode] = r
        st = r['stats']
        n_stop = sum(1 for o in r['operations'] if o.get('exit_reason') == 'stop_loss')
        worst = min((o['perf_pct'] for o in r['operations'] if o['status'] == 'closed'), default=0)
        print(f"  total {st.get('total_return')}% . CAGR {st.get('cagr')}% . "
              f"MaxDD {st.get('max_drawdown')}% . Sharpe {st.get('sharpe')}")
        print(f"  {st.get('n_operations_total')} op . {n_stop} stop scattati . worst trade {worst}%")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'adaptive_data.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[ADAPTIVE] scritto {path}")


if __name__ == '__main__':
    main()
