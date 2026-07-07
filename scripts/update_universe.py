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
        op = is_operational_in_base(state, stage)
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
            'history_weeks': len(sec),
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
