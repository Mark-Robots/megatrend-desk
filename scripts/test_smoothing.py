#!/usr/bin/env python3
"""
TEST SMOOTHING SWEEP — gira il backtest Adaptive per OGNI tolleranza di smoothing
da 0 (anticipa, nessun liscio) a 5 settimane, e stampa la tabella completa.

Serve a vedere se il sistema e' STABILE intorno al valore scelto (altopiano = buono)
o se un solo valore svetta (picco fragile = sospetto curve-fitting).

NON modifica file di produzione: intercetta lo smoothing a runtime.
Mettilo in scripts/ e lancia:  python scripts/test_smoothing.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
import update_stocks as us
import sector_baskets as sb
import adaptive_engine as ae

# la funzione di smoothing originale (per ripristino)
_ORIG_SMOOTH = us.smooth_signal_binary


def scarica_dati():
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK); tickers.add(us.EU_BENCHMARK)
    tickers.add(us.CASH_TICKER); tickers.add(us.WORLD_TICKER)
    tickers = sorted(tickers)
    print(f"Scarico {len(tickers)} ticker una volta sola...\n")
    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = raw['Close']
    dollar_vol = raw['Close'] * raw['Volume']
    prices = us.align_weekly_index(prices, us.BACKTEST_START)
    dollar_vol = us.align_weekly_index(dollar_vol, us.BACKTEST_START)
    return prices, dollar_vol


def gira_con_tolleranza(prices, dollar_vol, tol):
    # forzo lo smoothing alla tolleranza data (tol=0 => nessun liscio)
    us.smooth_signal_binary = (lambda signals, tolerance_weeks=3, _t=tol:
                               _ORIG_SMOOTH(signals, tolerance_weeks=_t))
    try:
        r = ae.build_full_output(prices, dollar_vol, 'aggressive')
    finally:
        us.smooth_signal_binary = _ORIG_SMOOTH
    return r['stats'], len(r['current_positions'])


def main():
    print("=" * 78)
    print("TEST SMOOTHING SWEEP — Adaptive, tolleranza 0..5 settimane")
    print("(0 = anticipa / nessun liscio ; 3 = attuale)")
    print("=" * 78)
    prices, dollar_vol = scarica_dati()

    rows = []
    for tol in range(0, 6):
        print(f"Giro tolleranza {tol}...")
        st, pos = gira_con_tolleranza(prices, dollar_vol, tol)
        rows.append((tol, st, pos))

    print("\n" + "=" * 78)
    print(f"  {'TOL':>4} {'Rend.tot':>10} {'CAGR':>8} {'Sharpe':>8} "
          f"{'MaxDD':>9} {'WinR':>7} {'P/L':>6} {'Op':>5} {'Pos':>5}")
    print("-" * 78)
    for tol, st, pos in rows:
        star = " *" if tol == 3 else "  "
        print(f"  {tol:>4}{star}"
              f"{st.get('total_return',0):>9.1f}%"
              f"{st.get('cagr',0):>7.1f}%"
              f"{st.get('sharpe',0):>8.2f}"
              f"{st.get('max_drawdown',0):>8.1f}%"
              f"{st.get('win_rate',0):>6.1f}%"
              f"{(st.get('profit_loss_ratio') or 0):>6.2f}"
              f"{st.get('n_operations_total',0):>5.0f}"
              f"{pos:>5}")
    print("=" * 78)
    print("* = valore attuale in produzione (3)")
    print()

    # trovo il miglior Sharpe e il miglior rendimento
    best_sharpe = max(rows, key=lambda x: x[1].get('sharpe', 0))
    best_ret = max(rows, key=lambda x: x[1].get('total_return', 0))
    print(f"Miglior Sharpe:     tolleranza {best_sharpe[0]} "
          f"(Sharpe {best_sharpe[1].get('sharpe',0):.2f})")
    print(f"Miglior rendimento: tolleranza {best_ret[0]} "
          f"(+{best_ret[1].get('total_return',0):.1f}%)")
    print()
    print("COME LEGGERE: cerca un ALTOPIANO, non un picco. Se 2-3-4 danno")
    print("valori simili, il sistema e' robusto e 3 va bene. Se un solo")
    print("valore svetta e gli altri crollano, e' fortuna, non segnale.")


if __name__ == '__main__':
    main()
