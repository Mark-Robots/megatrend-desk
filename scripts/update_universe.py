#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UNIVERSO COMPLETO · MarkRoboT.S.
--------------------------------
Calcola RRG (RS-Ratio / RS-Momentum) + fase di Weinstein per un universo ESTESO
di settori/tematici, oltre ai 13 del desk. Serve alla pagina "Universo completo":
mostra anche i settori esclusi dal desk (automotive, utilities, materiali, ecc.),
così si coglie un'eventuale rotazione futura di leadership.

NON tocca il motore del desk: è uno script separato che scrive un JSON a parte
(data/universe_data.json). Usa gli STESSI benchmark e le STESSE formule del
motore ufficiale (update_data.py), così i risultati sono confrontabili.

Benchmark: USA = SPY, Europa = EXSA.DE (identici al desk).
"""

import json, os, sys
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

US_BENCHMARK = 'SPY'
EU_BENCHMARK = 'EXSA.DE'
OUT_PATH = os.path.join('data', 'universe_data.json')

# ── UNIVERSO ESTESO (settori NON già nel desk) ──────────────────────────
# Livello 1: GICS USA mancanti · Livello 2: Europa completa · Livello 3: tematici
US_EXTRA = {
    # Livello 1 — GICS USA mancanti
    'XLY':  'Beni voluttuari USA',
    'XLU':  'Utilities USA',
    'XLB':  'Materiali USA',
    'XLRE': 'Immobiliare USA',
    'XLC':  'Comunicazioni USA',
    # Livello 3 — tematici strutturali (USA/globali)
    'DRIV': 'Automotive / EV',
    'BOTZ': 'AI / Robotica',
    'ICLN': 'Clean Energy',
    'HACK': 'Cybersecurity',
    'ITA':  'Aerospazio / Difesa',
}
EU_EXTRA = {
    # Livello 2 — Europa completa (STOXX 600 settoriali iShares)
    'EXV3.DE': 'Tecnologia EU',
    'EXV4.DE': 'Sanità EU',
    'EXH9.DE': 'Utilities EU',
    'EXH7.DE': 'Beni di base EU',
    'EXV6.DE': 'Materiali EU',
    'EXV5.DE': 'Automotive EU',
    'EXV7.DE': 'Chimica EU',
    'EXH3.DE': 'Telecom EU',
}

LEVEL = {  # per etichettare la provenienza nella pagina
    'XLY':'GICS USA','XLU':'GICS USA','XLB':'GICS USA','XLRE':'GICS USA','XLC':'GICS USA',
    'DRIV':'Tematico','BOTZ':'Tematico','ICLN':'Tematico','HACK':'Tematico','ITA':'Tematico',
    'EXV3.DE':'Settore EU','EXV4.DE':'Settore EU','EXH9.DE':'Settore EU','EXH7.DE':'Settore EU',
    'EXV6.DE':'Settore EU','EXV5.DE':'Settore EU','EXV7.DE':'Settore EU','EXH3.DE':'Settore EU',
}


# ── FORMULE (identiche a update_data.py) ────────────────────────────────
def calculate_rrg(symbol_prices, benchmark_prices, window=14):
    common = symbol_prices.dropna().index.intersection(benchmark_prices.dropna().index)
    if len(common) < window * 3:
        return None
    rs_raw = (symbol_prices.loc[common] / benchmark_prices.loc[common]) * 100
    rs_ratio = rs_raw.rolling(window=window).mean()
    rs_ratio_mean = rs_ratio.rolling(window=window*4).mean()
    rs_ratio_std = rs_ratio.rolling(window=window*4).std()
    rs_ratio_norm = 100 + (rs_ratio - rs_ratio_mean) / rs_ratio_std.replace(0, 1) * 5
    rs_mom_raw = rs_ratio_norm.pct_change(periods=window//2) * 100 + 100
    rs_mom = rs_mom_raw.rolling(window=window//2).mean()
    return pd.DataFrame({'rsRatio': rs_ratio_norm, 'rsMom': rs_mom}).dropna()


def classify_quadrant(rs, mom):
    if pd.isna(rs) or pd.isna(mom):
        return 'Debole'
    if rs >= 100 and mom >= 100: return 'Leader'
    if rs <  100 and mom >= 100: return 'Emergente'
    if rs >= 100 and mom <  100: return 'In rallentamento'
    return 'Debole'


def classify_stage(prices, ma_weeks=30):
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
    ma_5w_ago = ma.iloc[-6] if len(ma) >= 6 else last_ma
    slope_up = last_ma > ma_5w_ago
    above_ma = last_price > last_ma
    if above_ma and slope_up:         return '2'
    if above_ma and not slope_up:     return '3'
    if not above_ma and not slope_up: return '4'
    return '1'


def is_operational_in_base(state, stage):
    if state == 'Debole':
        return False
    if stage == '4':
        return False
    return True


def smooth_signal_binary(signals, tolerance_weeks=4):
    """Liscia una serie binaria ignorando transizioni che durano ≤ tolerance_weeks
    settimane consecutive. IDENTICA a update_data.py / update_stocks.py:
    un flip del segnale base diventa effettivo solo se persiste oltre la tolleranza."""
    if not signals:
        return signals
    current = signals[0]
    pending_count = 0
    smoothed = []
    for v in signals:
        if v == current:
            pending_count = 0
            smoothed.append(current)
        else:
            pending_count += 1
            if pending_count > tolerance_weeks:
                current = v
                pending_count = 0
            smoothed.append(current)
    return smoothed


def score_universe(state, rs_ratio, alpha, weeks, stage):
    """Punteggio di forza 0-200+.
    STESSA formula di score_sector in update_data.py (il desk), così gli score
    dell'universo sono confrontabili e la freccia settimanale ha lo stesso metro.
    alpha = perf settore - perf benchmark dalla data di inizio trend (%).
    weeks = settimane di trend ininterrotto (weeks_in_trend)."""
    score = 0
    if state == 'Leader': score = 100
    elif state == 'Emergente': score = 70
    elif state == 'In rallentamento': score = 40
    else: score = 10
    score += max(0, (rs_ratio or 100) - 100) * 2
    score += max(-30, min(30, (alpha or 0) * 0.6))
    if state == 'Leader':
        if (weeks or 0) > 60: score -= 20
        elif (weeks or 0) > 40: score -= 10
    if '2' in str(stage): score += 5
    elif '4' in str(stage): score -= 5
    return round(score, 1)


# ── DOWNLOAD + CALCOLO ──────────────────────────────────────────────────
def fetch_weekly(tickers):
    """Scarica prezzi settimanali (Close) per i ticker dati."""
    data = yf.download(tickers, period='3y', interval='1wk',
                       auto_adjust=True, progress=False)
    if 'Close' in data:
        close = data['Close']
    else:
        close = data
    if isinstance(close, pd.Series):
        close = close.to_frame()
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    return close


def process_region(close, bench_ticker, sector_dict, region_label):
    rows = []
    if bench_ticker not in close.columns:
        print(f"  [!] benchmark {bench_ticker} mancante, regione {region_label} saltata", file=sys.stderr)
        return rows
    bench = close[bench_ticker].dropna()
    for ticker, name in sector_dict.items():
        if ticker not in close.columns:
            print(f"  [skip] {ticker} ({name}) — nessun dato", file=sys.stderr)
            continue
        sec = close[ticker].dropna()
        if len(sec) < 40:
            print(f"  [skip] {ticker} ({name}) — storia troppo corta ({len(sec)} sett)", file=sys.stderr)
            continue
        rrg = calculate_rrg(sec, bench)
        if rrg is None or len(rrg) == 0:
            print(f"  [skip] {ticker} ({name}) — RRG non calcolabile", file=sys.stderr)
            continue
        rs = float(rrg['rsRatio'].iloc[-1])
        mom = float(rrg['rsMom'].iloc[-1])
        state = classify_quadrant(rs, mom)
        stage = classify_stage(sec)

        # Segnale operativo con SMOOTHING 4 (stessa regola del desk):
        # serie settimanale base (stato+fase) → smooth_signal_binary(4).
        # opSignal, data d'ingresso e settimane di trend derivano dalla serie
        # LISCIATA, non dall'ultima fotografia: un flip deve persistere oltre
        # 4 settimane per diventare operativo, esattamente come nel desk.
        op = False
        op_entry = None
        weeks_in_trend = 0
        try:
            rrg_hist = rrg.dropna()
            sec_al = sec.reindex(rrg_hist.index, method='ffill')
            ma30 = sec.rolling(30).mean().reindex(rrg_hist.index, method='ffill')
            base_in = []
            states_w, stages_w = [], []
            for k in range(len(rrg_hist)):
                rk = float(rrg_hist['rsRatio'].iloc[k])
                mk = float(rrg_hist['rsMom'].iloc[k])
                st_k = classify_quadrant(rk, mk)
                pk = sec_al.iloc[k]; mak = ma30.iloc[k]
                if pd.isna(mak):
                    stg_k = '—'
                else:
                    mak_prev = ma30.iloc[k - 5] if k >= 5 else mak
                    up = mak > mak_prev; above = pk > mak
                    stg_k = '2' if (above and up) else '3' if (above and not up) else '4' if (not above and not up) else '1'
                states_w.append(st_k); stages_w.append(stg_k)
                base_in.append(is_operational_in_base(st_k, stg_k))
            smoothed = smooth_signal_binary(base_in, tolerance_weeks=4)
            if smoothed:
                op = bool(smoothed[-1])
            if op:
                k = len(smoothed) - 1
                while k >= 0 and smoothed[k]:
                    op_entry = rrg_hist.index[k]
                    weeks_in_trend += 1
                    k -= 1
            op_entry_str = op_entry.strftime('%Y-%m-%d') if op_entry is not None else None
        except Exception:
            op_entry_str = None
            weeks_in_trend = 0
            op = is_operational_in_base(state, stage)  # fallback: fotografia grezza

        # Alpha vs benchmark dalla data di inizio trend (per lo score).
        # Se il settore non è in trend, alpha=0: pesa solo stato/rsRatio/fase.
        alpha = 0.0
        if op_entry is not None:
            try:
                b_al = bench.reindex(sec.index, method='ffill')
                p0, p1 = sec.loc[op_entry], sec.iloc[-1]
                b0, b1 = b_al.loc[op_entry], b_al.iloc[-1]
                if not (pd.isna(p0) or pd.isna(b0) or p0 == 0 or b0 == 0):
                    alpha = (p1 / p0 - 1) * 100 - (b1 / b0 - 1) * 100
            except Exception:
                alpha = 0.0
        score = score_universe(state, rs, alpha, weeks_in_trend, stage)

        # ── Serie 52 settimane per i grafici della pagina universo:
        #    prezzo, segnale lisciato (per le bande IN) e score storico
        #    ricalcolato a ritroso con la stessa formula (walk-forward:
        #    ogni punto usa solo informazioni note a quella settimana). ──
        price_series, in_series, score_series = [], [], []
        try:
            n_hist = len(rrg_hist)
            s0 = max(0, n_hist - 52)
            b_al2 = bench.reindex(rrg_hist.index, method='ffill')
            for k in range(s0, n_hist):
                pv = sec_al.iloc[k]
                price_series.append({'date': rrg_hist.index[k].strftime('%Y-%m-%d'),
                                     'value': round(float(pv), 2) if pv == pv else None})
                in_series.append(bool(smoothed[k]))
                # streak lisciata corrente alla settimana k
                wk_k = 0; e = k
                if smoothed[k]:
                    while e >= 0 and smoothed[e]:
                        wk_k += 1; e -= 1
                    e += 1
                a_k = 0.0
                if smoothed[k]:
                    p0, p1 = sec_al.iloc[e], sec_al.iloc[k]
                    b0, b1 = b_al2.iloc[e], b_al2.iloc[k]
                    if p0 == p0 and b0 == b0 and p0 and b0:
                        a_k = (p1 / p0 - 1) * 100 - (b1 / b0 - 1) * 100
                rk = float(rrg_hist['rsRatio'].iloc[k])
                score_series.append({'date': rrg_hist.index[k].strftime('%Y-%m-%d'),
                                     'value': score_universe(states_w[k], rk, a_k, wk_k, stages_w[k])})
        except Exception:
            price_series, in_series, score_series = [], [], []

        rows.append({
            'ticker': ticker.replace('.DE', ''),
            'ticker_raw': ticker,
            'name': name,
            'region': 'USA' if region_label == 'USA' else 'EU',
            'group': LEVEL.get(ticker, '—'),
            'rsRatio': round(rs, 2),
            'rsMom': round(mom, 2),
            'state': state,
            'stage': stage,
            'opSignal': 'IN' if op else 'OUT',
            'trend_start_date': op_entry_str,
            'weeks_in_trend': weeks_in_trend,
            'history_weeks': len(sec),
            'score': score,
            'priceSeries': price_series,
            'scoreSeries': score_series,
            'inSeries': in_series,
        })
        print(f"  [ok] {ticker:9} {name:24} {state:16} F{stage}  rs={rs:.1f} mom={mom:.1f}")
    return rows


def main():
    all_us = [US_BENCHMARK] + list(US_EXTRA.keys())
    all_eu = [EU_BENCHMARK] + list(EU_EXTRA.keys())

    print("Scarico USA...")
    close_us = fetch_weekly(all_us)
    print("Scarico Europa...")
    close_eu = fetch_weekly(all_eu)

    us_rows = process_region(close_us, US_BENCHMARK, US_EXTRA, 'USA')
    eu_rows = process_region(close_eu, EU_BENCHMARK, EU_EXTRA, 'EU')

    all_rows = us_rows + eu_rows
    # ordino per forza: prima gli operativi (IN), poi per rsRatio decrescente
    all_rows.sort(key=lambda r: (r['opSignal'] != 'IN', -r['rsRatio']))

    # ── STORICO SCORE + variazione settimanale (per la freccia della pagina) ──
    # Stessa logica di update_data.py: snapshot giornaliero in universe_history.json,
    # confronto con quello di 5-9 giorni fa (fallback 5-14 se c'è un buco nei run).
    HIST_PATH = os.path.join('data', 'universe_history.json')
    history = []
    try:
        if os.path.exists(HIST_PATH):
            with open(HIST_PATH, 'r') as f:
                history = json.load(f)
    except Exception as e:
        print(f"  Storico universo non disponibile: {e}", file=sys.stderr)
        history = []

    today = datetime.now(timezone.utc).date()
    prev_scores = {}
    prev_date = None
    fallback_snap = None
    for snap in reversed(history):
        try:
            snap_date = datetime.fromisoformat(snap['date']).date()
            days_diff = (today - snap_date).days
            if 5 <= days_diff <= 9:
                prev_scores = {r['ticker']: r.get('score') for r in snap.get('ranks', [])}
                prev_date = snap['date']
                break
            if fallback_snap is None and 5 <= days_diff <= 14:
                fallback_snap = snap
        except Exception:
            continue
    else:
        if fallback_snap is not None:
            prev_scores = {r['ticker']: r.get('score') for r in fallback_snap.get('ranks', [])}
            prev_date = fallback_snap['date']

    for r in all_rows:
        ps = prev_scores.get(r['ticker'])
        if ps is not None:
            r['score_prev'] = ps
            r['score_change'] = round(r['score'] - ps, 1)
        else:
            r['score_prev'] = None
            r['score_change'] = None

    today_snapshot = {
        'date': datetime.now(timezone.utc).isoformat(),
        'ranks': [{'ticker': r['ticker'], 'score': r['score']} for r in all_rows],
    }
    history = [h for h in history if not h.get('date', '').startswith(today.isoformat())]
    history.append(today_snapshot)
    if len(history) > 35:
        history = history[-35:]
    try:
        os.makedirs('data', exist_ok=True)
        with open(HIST_PATH, 'w') as f:
            json.dump(history, f, indent=2)
        print(f"  Snapshot universo salvato in {HIST_PATH} (prev: {prev_date})")
    except Exception as e:
        print(f"  Impossibile salvare lo storico universo: {e}", file=sys.stderr)

    last_date = None
    for c in (close_us, close_eu):
        if len(c) > 0:
            d = c.index[-1].strftime('%Y-%m-%d')
            last_date = max(last_date, d) if last_date else d

    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': last_date,
        'note': 'Universo esteso: settori extra oltre i 13 del desk. Stesse formule e benchmark del motore ufficiale.',
        'benchmarks': {'USA': US_BENCHMARK, 'EU': EU_BENCHMARK},
        'sectors': all_rows,
        'count': len(all_rows),
    }
    os.makedirs('data', exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[salvato] {OUT_PATH} — {len(all_rows)} settori extra")
    # riepilogo per stato
    from collections import Counter
    c = Counter(r['state'] for r in all_rows)
    print("Riepilogo stati:", dict(c))


if __name__ == '__main__':
    main()
