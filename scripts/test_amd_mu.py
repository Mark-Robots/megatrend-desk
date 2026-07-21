#!/usr/bin/env python3
"""
DIAGNOSTICA: perché l'Adaptio scelse AMD e non MU l'11/07/2025 in SOXX?
Calcola il punteggio di selezione (aggressive = ROC4×0.7 + ROC13×0.3) di TUTTI i
candidati SOXX a quella data e li ordina. Risponde: AMD aveva davvero score > MU?

NON tocca la produzione. In scripts/, lancia: python scripts/test_amd_mu.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import yfinance as yf
import update_stocks as us
import sector_baskets as sb

DATA_SCELTA = pd.Timestamp('2025-07-11')

def main():
    us.deduplicate_universes()  # applica dedup come in produzione
    basket = sb.BASKETS.get('SOXX', [])
    print(f"Candidati SOXX (dopo dedup): {basket}\n")

    tickers = sorted(set(basket) | {'MU', 'AMD'})
    raw = yf.download(tickers, start='2023-01-01', end='2025-07-14',
                      interval='1wk', auto_adjust=True, progress=False)
    prices = us.align_weekly_index(raw['Close'], '2023-01-01')

    # indice della settimana della scelta (l'ultima <= DATA_SCELTA)
    idx = prices.index[prices.index <= DATA_SCELTA]
    if len(idx) == 0:
        print("Data non trovata"); return
    w = prices.index.get_loc(idx[-1])
    print(f"Settimana di riferimento: {prices.index[w].date()}\n")

    rows = []
    for tk in tickers:
        if tk not in prices.columns: continue
        s = prices[tk].iloc[:w+1].dropna()
        if len(s) < 14: continue
        roc4 = us.compute_roc(s, 4)
        roc13 = us.compute_roc(s, 13)
        roc52 = us.compute_roc(s, 52)
        score_aggr = (roc4 or 0)*0.7 + (roc13 or 0)*0.3
        rows.append((tk, roc4, roc13, roc52, score_aggr))

    rows.sort(key=lambda x: x[4], reverse=True)
    print(f"{'TICKER':8}{'ROC4':>8}{'ROC13':>8}{'ROC52':>8}{'SCORE_aggr':>12}")
    print("-"*44)
    for tk, r4, r13, r52, sc in rows:
        star = " ←SCELTO" if tk == rows[0][0] else ""
        mark = " (AMD)" if tk=='AMD' else " (MU)" if tk=='MU' else ""
        print(f"{tk:8}{(r4 or 0):>7.1f}%{(r13 or 0):>7.1f}%{(r52 or 0):>7.1f}%{sc:>11.2f}{mark}{star}")
    print()
    # confronto diretto AMD vs MU
    d = {r[0]: r for r in rows}
    if 'AMD' in d and 'MU' in d:
        a, m = d['AMD'], d['MU']
        print(f"AMD score={a[4]:.2f}  vs  MU score={m[4]:.2f}")
        if a[4] > m[4]:
            print(f"→ AMD aveva score PIÙ ALTO di MU all'11/07/2025: la scelta fu CORRETTA")
            print(f"  (AMD correva di più nel breve; MU ha accelerato DOPO, non prevedibile)")
        else:
            print(f"→ MU aveva score più alto: il motore AVREBBE dovuto scegliere MU")

if __name__ == '__main__':
    main()
