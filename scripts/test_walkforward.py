#!/usr/bin/env python3
"""
WALK-FORWARD sullo smoothing dell'Adaptive (versione corretta).

L'engine ha bisogno di ~56 settimane di storia per il warmup (RRG, ROC), quindi
NON si puo' girare su una finestra isolata di 1 anno. Soluzione: giro sempre da
inizio storia fino a fine anno-test, ma MISURO il rendimento del SOLO anno-test
dalla equity curve (la parte out-of-sample, non vista quando ho scelto il parametro).

NON tocca la produzione. In scripts/, lancia: python scripts/test_walkforward.py
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
TOLS = [2, 3, 4]


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


def equity_curve_upto(prices, dollar_vol, tol, end_date):
    """Gira l'engine da inizio storia fino a end_date con smoothing=tol.
    Ritorna la equity curve (lista di {date, system})."""
    us.smooth_signal_binary = (lambda s, tolerance_weeks=3, _t=tol:
                               _ORIG(s, tolerance_weeks=_t))
    try:
        mask = prices.index < end_date
        pw = prices.loc[mask]
        dvw = dollar_vol.loc[mask]
        if len(pw) < 60:
            return []
        r = ae.build_full_output(pw, dvw, 'aggressive')
        return r['equity_curve']
    except Exception:
        return []
    finally:
        us.smooth_signal_binary = _ORIG


def sharpe_upto(prices, dollar_vol, tol, end_date):
    us.smooth_signal_binary = (lambda s, tolerance_weeks=3, _t=tol:
                               _ORIG(s, tolerance_weeks=_t))
    try:
        mask = prices.index < end_date
        pw = prices.loc[mask]; dvw = dollar_vol.loc[mask]
        if len(pw) < 60:
            return -99
        r = ae.build_full_output(pw, dvw, 'aggressive')
        return r['stats'].get('sharpe', -99)
    except Exception:
        return -99
    finally:
        us.smooth_signal_binary = _ORIG


def year_return(curve, year):
    """Rendimento % del solo anno indicato, dalla equity curve."""
    pts = [(pd.Timestamp(p['date']), p['system']) for p in curve
           if pd.Timestamp(p['date']).year == year]
    if len(pts) < 2:
        return None
    pts.sort()
    return (pts[-1][1] / pts[0][1] - 1) * 100


def main():
    print("=" * 74)
    print("WALK-FORWARD SMOOTHING — Adaptive (con warmup corretto)")
    print("=" * 74)
    prices, dollar_vol = scarica()
    dates = prices.index
    y0, y1 = dates[0].year, dates[-1].year
    print(f"Storia: {dates[0].date()} -> {dates[-1].date()}\n")

    results = []
    for test_year in range(y0 + 3, y1 + 1):
        train_end = pd.Timestamp(f"{test_year}-01-01")
        test_end = pd.Timestamp(f"{test_year + 1}-01-01")
        # 1) scelgo miglior tol per Sharpe sul TRAIN (dati < train_end)
        best_tol, best_sh = None, -99
        for tol in TOLS:
            sh = sharpe_upto(prices, dollar_vol, tol, train_end)
            if sh > best_sh:
                best_sh, best_tol = sh, tol
        # 2) OOS: giro fino a fine test_year, isolo il rendimento di test_year
        curve_best = equity_curve_upto(prices, dollar_vol, best_tol, test_end)
        ret_best = year_return(curve_best, test_year)
        fixed = {}
        for tol in TOLS:
            c = equity_curve_upto(prices, dollar_vol, tol, test_end)
            fixed[tol] = year_return(c, test_year)
        results.append((test_year, best_tol, ret_best, fixed))
        rb = f"{ret_best:+.1f}%" if ret_best is not None else "n/d"
        print(f"  {test_year}: train sceglie tol={best_tol} -> OOS {rb}")

    print("\n" + "=" * 74)
    print("RENDIMENTO OUT-OF-SAMPLE COMPOSTO (quello che avresti fatto DAVVERO)")
    print("-" * 74)

    def compound(rets):
        acc = 1.0
        for r in rets:
            if r is not None:
                acc *= (1 + r / 100)
        return (acc - 1) * 100

    wf = [r[2] for r in results]
    print(f"  {'Walk-forward (scegli il migliore)':42} {compound(wf):>+10.1f}%")
    for tol in TOLS:
        fr = [r[3][tol] for r in results]
        print(f"  {'Fisso tol=' + str(tol):42} {compound(fr):>+10.1f}%")
    print("=" * 74)
    print()
    print("LETTURA:")
    print("- Se un tol FISSO batte il walk-forward, inseguire l'ottimo non paga.")
    print("- Se 'train sceglie tol' e' sempre lo stesso ED e' anche il migliore")
    print("  OOS, quel valore e' robusto. Se il train sceglie 4 ma OOS 4 perde,")
    print("  allora 4 era overfitting sullo storico completo.")


if __name__ == '__main__':
    main()
