#!/usr/bin/env python3
"""
TEST SMOOTHING — confronta il backtest Adaptive CON smoothing (3 settimane, come
l'ETF) vs SENZA smoothing (anticipa, come le azioni "prima").

Gira l'engine due volte cambiando SOLO lo smoothing e stampa le metriche affiancate.
NON modifica nessun file di produzione: intercetta la funzione di smoothing a runtime.
Mettilo nella cartella scripts/ accanto a update_stocks.py e lancia:
    python test_smoothing.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
import update_stocks as us
import sector_baskets as sb
import adaptive_engine as ae


def scarica_dati():
    tickers = set()
    for tks in sb.BASKETS.values():
        tickers.update(tks)
    tickers.update(us.SECTORS_SYSTEM)
    tickers.add(us.US_BENCHMARK); tickers.add(us.EU_BENCHMARK)
    tickers.add(us.CASH_TICKER); tickers.add(us.WORLD_TICKER)
    tickers = sorted(tickers)
    print(f"Scarico {len(tickers)} ticker una volta sola...")
    raw = yf.download(tickers, start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = raw['Close']
    dollar_vol = raw['Close'] * raw['Volume']
    prices = us.align_weekly_index(prices, us.BACKTEST_START)
    dollar_vol = us.align_weekly_index(dollar_vol, us.BACKTEST_START)
    return prices, dollar_vol


def gira(prices, dollar_vol, smoothing_on):
    originale = us.smooth_signal_binary
    if not smoothing_on:
        us.smooth_signal_binary = lambda signals, tolerance_weeks=3: list(signals)
    try:
        r = ae.build_full_output(prices, dollar_vol, 'aggressive')
    finally:
        us.smooth_signal_binary = originale
    return r['stats'], len(r['current_positions'])


def main():
    print("=" * 66)
    print("TEST SMOOTHING — Adaptive: CON (3 sett, come ETF) vs SENZA (anticipa)")
    print("=" * 66)
    prices, dollar_vol = scarica_dati()

    print("Giro CON smoothing...")
    on, pos_on = gira(prices, dollar_vol, True)
    print("Giro SENZA smoothing (anticipa)...")
    off, pos_off = gira(prices, dollar_vol, False)

    def r(lbl, k, fmt="{:+.2f}", sfx=""):
        try:
            a = fmt.format(on.get(k, 0)) + sfx
            b = fmt.format(off.get(k, 0)) + sfx
        except Exception:
            a, b = str(on.get(k)), str(off.get(k))
        print(f"  {lbl:24} {a:>15} {b:>15}")

    print("\n" + "=" * 66)
    print(f"  {'METRICA':24} {'CON smoothing':>15} {'SENZA (antic.)':>15}")
    print("-" * 66)
    r("Rendimento totale", "total_return", "{:+.2f}", "%")
    r("CAGR", "cagr", "{:+.2f}", "%")
    r("Sharpe", "sharpe", "{:.2f}")
    r("Max Drawdown", "max_drawdown", "{:.2f}", "%")
    r("Win Rate", "win_rate", "{:.1f}", "%")
    r("Profit/Loss ratio", "profit_loss_ratio", "{:.2f}")
    r("Operazioni totali", "n_operations_total", "{:.0f}")
    print(f"  {'Posizioni aperte ora':24} {pos_on:>15} {pos_off:>15}")
    print("=" * 66)

    dr = off.get('total_return', 0) - on.get('total_return', 0)
    dd = off.get('max_drawdown', 0) - on.get('max_drawdown', 0)
    dop = off.get('n_operations_total', 0) - on.get('n_operations_total', 0)
    sh_on, sh_off = on.get('sharpe', 0), off.get('sharpe', 0)
    print("\nLETTURA (anticipare rispetto a tenere lo smoothing):")
    print(f"  rendimento: {dr:+.1f} punti")
    print(f"  max drawdown: {dd:+.1f} punti (negativo = peggiora)")
    print(f"  operazioni: {dop:+.0f} (i whipsaw brevi che rientrano)")
    print(f"  Sharpe: {sh_on:.2f} vs {sh_off:.2f} -> "
          f"{'ANTICIPARE meglio' if sh_off > sh_on + 0.03 else 'SMOOTHING meglio' if sh_on > sh_off + 0.03 else 'sostanzialmente pari'}")
    print()
    print("Ricorda il principio: se i numeri sono simili, la scelta piu robusta")
    print("e quella con meno operazioni e drawdown minore (meno whipsaw).")


if __name__ == '__main__':
    main()
