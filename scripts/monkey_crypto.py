#!/usr/bin/env python3
"""
MONKEY TEST · CRYPTO — random-entry test sul timing del DMI Sentinel.

DOMANDA: il DMI Sentinel e' long-only su BTC/ETH/SOL. In un decennio
prevalentemente rialzista, quanto del rendimento viene dal SAPERE QUANDO stare
dentro, e quanto dal semplice essere long una certa frazione del tempo?

COME (random-entry test, alla Timothy Masters): si ricostruisce il segnale DMI
sulla storia COMPLETA (dal 2018, candele orarie, parametri mensili walk-forward,
stessa logica di update_crypto.run_backtest). La sequenza di posizioni diventa
una lista di blocchi alternati FLAT/LONG con le loro durate. Ogni scimmia
RIMESCOLA le durate (i long tra loro, i flat tra loro), mantenendo il pattern di
alternanza: stessa esposizione totale, stesso numero di trade, stesse durate —
cambia solo DOVE cadono nel tempo. Il percentile del CAGR reale nella
distribuzione casuale misura il valore del timing.

Qui il drawdown conta quanto il CAGR: evitare il bear 2022 richiedeva timing,
non fortuna di piazzamento. Percentuale di scimmie con MaxDD peggiore inclusa.

LETTURA ONESTA: < 80° caso · 80-94° debole · >= 95° segnale (p <= 0.05).
Nota: i parametri mensili sono walk-forward ma scelti su questa storia; una
quota di ottimismo in-sample resta fisiologica (vale per sistema E scimmie
in egual misura per l'esposizione, ma il timing fine e' del solo sistema).

Output: data/monkey_crypto.json (stesso schema; modes = BTC/ETH/SOL/composito).
USO: workflow_dispatch. Config env: MT_N (10000), MT_SEED (42), MT_START (2018-01-01).
"""
import json
import os
import sys
import datetime
from datetime import timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_crypto as uc

N_MONKEYS = int(os.environ.get('MT_N', '10000'))
SEED = int(os.environ.get('MT_SEED', '42'))
START = os.environ.get('MT_START', '2018-01-01')


# ---------------------------------------------------------------------------
# 1) BACKTEST FULL-HISTORY — stessa logica di update_crypto.run_backtest ma
#    senza il cutoff LOOKBACK_DAYS: parte dalla prima candela con DMI valido.
# ---------------------------------------------------------------------------
def run_full_backtest(klines, asset, dmi_by_time):
    use_ema = uc.EMA_FILTER.get(asset, False)
    closes = [k['close'] for k in klines]
    htf_ema = uc._ema(closes, uc.HTF_EMA_LEN) if use_ema else None
    dmis = [dmi_by_time.get(k['time']) for k in klines]
    times = [k['time'] for k in klines]

    start_idx = next((i for i, d in enumerate(dmis) if d is not None), None)
    if start_idx is None or start_idx >= len(klines) - 10:
        return None

    pos_arr = np.zeros(len(klines), dtype=np.int8)   # 1 = LONG sulla candela i
    pos = 'FLAT'
    ep = 0.0
    n_trades = 0
    for i in range(start_idx + 1, len(klines)):
        di, dip = dmis[i], dmis[i - 1]
        cl = closes[i]
        pos_arr[i] = 1 if pos == 'LONG' else 0       # posizione con cui si vive il ret i-1 -> i
        if di is None or dip is None:
            continue
        d = datetime.datetime.utcfromtimestamp(times[i])
        p = uc.get_params(asset, d.year, d.month)
        lE = (dip < p['d1'] and di >= p['d1']) or (dip < p['d2'] and di >= p['d2'])
        lX = (dip >= p['d1'] and di < p['d1']) or (dip >= p['d2'] and di < p['d2'])
        sE = (dip > p['d3'] and di <= p['d3']) or (dip > p['d4'] and di <= p['d4'])
        htf_ok = True
        if use_ema and htf_ema:
            e = htf_ema[i]
            htf_ok = True if (e != e) else (cl > e)
        if lE and htf_ok and pos != 'LONG':
            pos = 'LONG'; ep = cl
        elif (lX or sE) and pos == 'LONG':
            pos = 'FLAT'; n_trades += 1

    # rendimenti orari NaN-safe, allineati: ret[i] = close[i]/close[i-1]-1
    c = np.array(closes, dtype=float)
    rets = np.zeros(len(c))
    with np.errstate(invalid='ignore', divide='ignore'):
        rr = c[1:] / c[:-1] - 1.0
    ok = np.isfinite(rr) & (c[:-1] > 0)
    rets[1:][ok] = rr[ok]

    return {
        'start_idx': start_idx,
        'pos': pos_arr,
        'rets': rets,
        'times': times,
        'n_trades': n_trades,
    }


# ---------------------------------------------------------------------------
# 2) BLOCCHI E PERMUTAZIONE — run-length encoding della posizione; le scimmie
#    rimescolano le durate LONG tra loro e FLAT tra loro, pattern invariato.
# ---------------------------------------------------------------------------
def to_blocks(pos_arr, start_idx):
    seg = pos_arr[start_idx:]
    states, durs = [], []
    cur = seg[0]; run = 1
    for v in seg[1:]:
        if v == cur:
            run += 1
        else:
            states.append(int(cur)); durs.append(run)
            cur = v; run = 1
    states.append(int(cur)); durs.append(run)
    return np.array(states, dtype=np.int8), np.array(durs, dtype=np.int64)


def monkey_position(states, durs, rng, total_len):
    d = durs.copy()
    idx_long = np.where(states == 1)[0]
    idx_flat = np.where(states == 0)[0]
    d[idx_long] = rng.permutation(d[idx_long])
    d[idx_flat] = rng.permutation(d[idx_flat])
    pos = np.repeat(states, d)
    return pos[:total_len]


def equity_stats(pos_seg, rets_seg, years):
    strat = rets_seg * pos_seg
    eq = np.cumprod(1.0 + strat)
    final = float(eq[-1])
    cagr = (final ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1.0)) * 100.0
    return round(cagr, 2), round(mdd, 2), eq


def day_sample_indices(times, start_idx):
    """indici (relativi a start_idx) dell'ultima candela di ogni giorno UTC,
    per campionare l'equity oraria su griglia giornaliera (composito)."""
    idxs, days = [], []
    last_day = None
    for j, t in enumerate(times[start_idx:]):
        dk = t // 86400
        if last_day is None:
            last_day = dk
        elif dk != last_day:
            idxs.append(j - 1); days.append(last_day)
            last_day = dk
    idxs.append(len(times) - start_idx - 1); days.append(last_day)
    return np.array(idxs), np.array(days)


# ---------------------------------------------------------------------------
# 3) TEST
# ---------------------------------------------------------------------------
def main():
    now = datetime.datetime.now(timezone.utc)
    start_dt = datetime.datetime.strptime(START, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    fetch_start = int(start_dt.timestamp() * 1000)
    rng = np.random.default_rng(SEED)

    prepared = {}
    for asset, sym in uc.SYMBOLS.items():
        print(f"[{asset}] scarico klines 1h da {START}...")
        kl = uc.fetch_klines(sym, fetch_start)
        print(f"[{asset}] {len(kl)} candele orarie")
        if len(kl) < 5000:
            print(f"[{asset}] dati insufficienti, skip")
            continue
        dmi = uc.compute_rolling_dmi(kl, uc.DMI_PERIOD)
        r = run_full_backtest(kl, asset, dmi)
        if r is None:
            continue
        prepared[asset] = r

    out = {
        'generated_at': now.isoformat(),
        'config': {'n_monkeys': N_MONKEYS, 'seed': SEED, 'start': START,
                   'test': 'random-entry (permutazione blocchi di esposizione)',
                   'question': 'il timing DMI batte la stessa esposizione piazzata a caso?'},
        'modes': {},
    }

    daily_curves_sys = {}     # asset -> (days, eq_daily) per il composito
    daily_curves_monk = {}    # asset -> matrice [N_MONKEYS x n_days]

    for asset, r in prepared.items():
        si = r['start_idx']
        pos_seg = r['pos'][si:].astype(float)
        rets_seg = r['rets'][si:]
        years = (r['times'][-1] - r['times'][si]) / (365.25 * 86400)
        states, durs = to_blocks(r['pos'], si)
        exposure = round(100.0 * float(np.mean(pos_seg)), 1)
        n_long_blocks = int(np.sum(states == 1))

        s_cagr, s_mdd, s_eq = equity_stats(pos_seg, rets_seg, years)
        bh_cagr = round(((float(np.prod(1.0 + rets_seg)) ** (1.0 / years)) - 1.0) * 100.0, 2)

        d_idx, d_days = day_sample_indices(r['times'], si)
        daily_curves_sys[asset] = (d_days, s_eq[d_idx])

        mc = np.empty(N_MONKEYS)
        md = np.empty(N_MONKEYS)
        monk_daily = np.empty((N_MONKEYS, len(d_idx)))
        total_len = len(pos_seg)
        for m in range(N_MONKEYS):
            mpos = monkey_position(states, durs, rng, total_len).astype(float)
            c_, dd_, eq_ = equity_stats(mpos, rets_seg, years)
            mc[m] = c_; md[m] = dd_
            monk_daily[m] = eq_[d_idx]
            if (m + 1) % 2000 == 0:
                print(f"  [{asset}] {m+1}/{N_MONKEYS} scimmie...")
        daily_curves_monk[asset] = (d_days, monk_daily)

        below = int(np.sum(mc < s_cagr))
        pctl = 100.0 * below / N_MONKEYS
        pval = (N_MONKEYS - below) / N_MONKEYS
        q = lambda p: float(np.quantile(mc, p))
        verdict = 'SEGNALE' if pctl >= 95 else ('DEBOLE' if pctl >= 80 else 'CASO')

        out['modes'][asset] = {
            'strategy': {'cagr': s_cagr, 'max_drawdown': s_mdd,
                         'n_operations': r['n_trades'],
                         'exposure_pct': exposure, 'n_long_blocks': n_long_blocks,
                         'buy_hold_cagr': bh_cagr, 'years': round(years, 2)},
            'monkeys': {'n': N_MONKEYS, 'seed': SEED,
                        'cagr_median': round(q(0.5), 2),
                        'cagr_p05': round(q(0.05), 2),
                        'cagr_p95': round(q(0.95), 2),
                        'mdd_median': round(float(np.quantile(md, 0.5)), 2),
                        'mdd_worse_than_system_pct': round(
                            100.0 * float(np.mean(md < s_mdd)), 1)},
            'percentile': round(pctl, 1),
            'p_value': round(pval, 4),
            'verdict': verdict,
            'monkey_cagrs': [round(float(x), 3) for x in mc],
        }
        m_ = out['modes'][asset]
        print(f"  [{asset}] sistema {s_cagr}% (B&H {bh_cagr}%, exp {exposure}%, "
              f"{r['n_trades']} trade) · scimmie mediana {m_['monkeys']['cagr_median']}% · "
              f"percentile {m_['percentile']}° · {m_['verdict']}")

    # ---- COMPOSITO: media equipesata delle curve giornaliere (come il desk) ----
    if len(daily_curves_sys) >= 2:
        all_days = sorted(set().union(*[set(d) for d, _ in daily_curves_sys.values()]))
        all_days = np.array(all_days)
        n_days = len(all_days)
        years_c = (all_days[-1] - all_days[0]) / 365.25

        def align(days, curve):
            """equity su griglia comune: 1.0 prima dello start, ffill dopo."""
            v = np.ones(n_days)
            j = np.searchsorted(all_days, days)
            v[j] = curve
            first = j[0]
            mask = np.zeros(n_days, dtype=bool); mask[j] = True
            idx = np.where(mask, np.arange(n_days), 0)
            np.maximum.accumulate(idx, out=idx)
            v = v[idx]
            v[:first] = 1.0
            return v

        sys_comp = np.mean([align(d, c) for d, c in daily_curves_sys.values()], axis=0)

        def comp_stats(curve):
            cagr = ((float(curve[-1]) / float(curve[0])) ** (1.0 / years_c) - 1.0) * 100.0
            peak = np.maximum.accumulate(curve)
            mdd = float(np.min(curve / peak - 1.0)) * 100.0
            return round(cagr, 2), round(mdd, 2)

        sc_cagr, sc_mdd = comp_stats(sys_comp)
        mcc = np.empty(N_MONKEYS)
        mcd = np.empty(N_MONKEYS)
        aligned_monk = {a: None for a in daily_curves_monk}
        for a, (d, mat) in daily_curves_monk.items():
            j = np.searchsorted(all_days, d)
            full = np.ones((N_MONKEYS, n_days))
            full[:, j] = mat
            mask = np.zeros(n_days, dtype=bool); mask[j] = True
            idx = np.where(mask, np.arange(n_days), 0)
            np.maximum.accumulate(idx, out=idx)
            full = full[:, idx]
            full[:, :j[0]] = 1.0
            aligned_monk[a] = full
        comp_all = np.mean(list(aligned_monk.values()), axis=0)
        for m in range(N_MONKEYS):
            mcc[m], mcd[m] = comp_stats(comp_all[m])

        below = int(np.sum(mcc < sc_cagr))
        pctl = 100.0 * below / N_MONKEYS
        pval = (N_MONKEYS - below) / N_MONKEYS
        qc = lambda p: float(np.quantile(mcc, p))
        verdict = 'SEGNALE' if pctl >= 95 else ('DEBOLE' if pctl >= 80 else 'CASO')
        out['modes']['composito'] = {
            'strategy': {'cagr': sc_cagr, 'max_drawdown': sc_mdd,
                         'n_operations': sum(r['n_trades'] for r in prepared.values()),
                         'years': round(years_c, 2)},
            'monkeys': {'n': N_MONKEYS, 'seed': SEED,
                        'cagr_median': round(qc(0.5), 2),
                        'cagr_p05': round(qc(0.05), 2),
                        'cagr_p95': round(qc(0.95), 2),
                        'mdd_median': round(float(np.quantile(mcd, 0.5)), 2),
                        'mdd_worse_than_system_pct': round(
                            100.0 * float(np.mean(mcd < sc_mdd)), 1)},
            'percentile': round(pctl, 1),
            'p_value': round(pval, 4),
            'verdict': verdict,
            'monkey_cagrs': [round(float(x), 3) for x in mcc],
        }
        m_ = out['modes']['composito']
        print(f"  [composito] sistema {sc_cagr}% · scimmie mediana "
              f"{m_['monkeys']['cagr_median']}% · percentile {m_['percentile']}° · {m_['verdict']}")

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'monkey_crypto.json')
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    print(f"\n[MONKEY·CRYPTO] scritto {path}")


if __name__ == '__main__':
    main()
