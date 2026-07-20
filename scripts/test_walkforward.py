#!/usr/bin/env python3
"""
WALK-FORWARD sullo smoothing dell'Adaptive.

Domanda: se ogni anno scegliessi il miglior smoothing sui dati PASSATI e lo usassi
l'anno DOPO, quanto renderei davvero? Questo separa il segnale (un valore che regge
fuori campione) dalla fortuna (un picco che vince solo sullo storico completo).

METODO:
- Divide la storia in finestre. Su ogni finestra IN-SAMPLE (train) trova lo smoothing
  col miglior Sharpe; poi misura QUEL valore sulla finestra OUT-OF-SAMPLE (test) dopo.
- Confronta la strategia "scegli il migliore ogni volta" con i valori FISSI 2,3,4.

NON tocca la produzione. Mettilo in scripts/ e lancia: python scripts/test_walkforward.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf
import update_stocks as us
import sector_baskets as sb
import adaptive_engine as ae

_ORIG = us.smooth_signal_binary
TOLS = [2, 3, 4]  # candidati da valutare (i 3 con Sharpe alto)


def scarica():
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK); tickers.add(us.EU_BENCHMARK)
    tickers.add(us.CASH_TICKER); tickers.add(us.WORLD_TICKER)
    tickers = sorted(tickers)
    print(f"Scarico {len(tickers)} ticker...\n")
    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    p = us.align_weekly_index(raw['Close'], us.BACKTEST_START)
    dv = us.align_weekly_index(raw['Close'] * raw['Volume'], us.BACKTEST_START)
    return p, dv


def run_window(prices, dollar_vol, tol, d0, d1):
    """Backtest su [d0,d1) con smoothing=tol. Ritorna (total_return, sharpe)."""
    us.smooth_signal_binary = (lambda s, tolerance_weeks=3, _t=tol:
                               _ORIG(s, tolerance_weeks=_t))
    try:
        mask = (prices.index >= d0) & (prices.index < d1)
        pw = prices.loc[mask]
        dvw = dollar_vol.loc[mask]
        if len(pw) < 60:  # troppo corta
            return None, None
        r = ae.build_full_output(pw, dvw, 'aggressive')
        st = r['stats']
        return st.get('total_return', 0), st.get('sharpe', 0)
    except Exception as e:
        return None, None
    finally:
        us.smooth_signal_binary = _ORIG


def main():
    print("=" * 74)
    print("WALK-FORWARD SMOOTHING — Adaptive")
    print("=" * 74)
    prices, dollar_vol = scarica()
    dates = prices.index
    y0, y1 = dates[0].year, dates[-1].year
    print(f"Storia: {dates[0].date()} -> {dates[-1].date()} ({y0}-{y1})\n")

    # finestre annuali: train = tutto fino a fine anno N, test = anno N+1
    # (walk-forward "ancorato": il train cresce, il test e' sempre l'anno dopo)
    results = []  # (anno_test, best_tol_in_sample, ret_oos_best, ret_oos per tol fissi)
    for test_year in range(y0 + 3, y1 + 1):  # servono almeno 3 anni di train iniziale
        train_end = pd.Timestamp(f"{test_year}-01-01")
        test_end = pd.Timestamp(f"{test_year + 1}-01-01")
        # scelgo il miglior tol sul TRAIN (per Sharpe)
        best_tol, best_sharpe = None, -99
        for tol in TOLS:
            _, sh = run_window(prices, dollar_vol, tol, dates[0], train_end)
            if sh is not None and sh > best_sharpe:
                best_sharpe, best_tol = sh, tol
        # misuro OOS: il best_tol e i tol fissi sull'anno di test
        ret_best, _ = run_window(prices, dollar_vol, best_tol, train_end, test_end)
        fixed = {}
        for tol in TOLS:
            rr, _ = run_window(prices, dollar_vol, tol, train_end, test_end)
            fixed[tol] = rr
        results.append((test_year, best_tol, ret_best, fixed))
        print(f"  {test_year}: train sceglie tol={best_tol} -> "
              f"OOS best={ret_best if ret_best is not None else 'n/d'}")

    # riepilogo: rendimento OOS composto per strategia
    print("\n" + "=" * 74)
    print("RENDIMENTO OUT-OF-SAMPLE COMPOSTO (quello che avresti fatto DAVVERO)")
    print("-" * 74)

    def compound(rets):
        acc = 1.0
        for r in rets:
            if r is not None:
                acc *= (1 + r / 100)
        return (acc - 1) * 100

    wf_rets = [r[2] for r in results]
    print(f"  {'Walk-forward (scegli il migliore)':42} {compound(wf_rets):>+10.1f}%")
    for tol in TOLS:
        fr = [r[3][tol] for r in results]
        print(f"  {'Fisso tol=' + str(tol):42} {compound(fr):>+10.1f}%")
    print("=" * 74)
    print()
    print("LETTURA:")
    print("- Se un tol FISSO batte il walk-forward, inseguire l'ottimo NON paga:")
    print("  il valore migliore cambia troppo, meglio fissarne uno robusto.")
    print("- Guarda anche la colonna 'train sceglie tol': se salta ogni anno")
    print("  (2,4,3,2,4...) e' instabile -> conferma che 4 era fortuna.")
    print("- Se invece il train sceglie SEMPRE lo stesso ed e' anche il migliore")
    print("  OOS, allora quel valore e' davvero robusto.")


if __name__ == '__main__':
    main()
