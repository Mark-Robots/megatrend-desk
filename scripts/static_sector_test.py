#!/usr/bin/env python3
"""
TEST sul sistema STATICO (lista curata): effetto di togliere i Consumi (XLP).
Usa il VERO run_backtest di produzione con l'universo curato, due volte:
9 settori vs 8 (senza XLP). Confronta total/MaxDD/Sharpe.
"""
import sys, os
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us

def main():
    prices = us.fetch_all_prices()
    print(f"prezzi: {prices.shape[1]} x {prices.shape[0]}\n")

    full = us.SECTORS_SYSTEM
    no_xlp = tuple(s for s in full if s != 'XLP')

    print(f"{'scenario':22} {'total':>7} {'MaxDD':>7} {'Sharpe':>7} {'n_op':>5}")
    print('-'*54)
    for label, secs in [('9 settori (tutti)', full), ('8 (senza Consumi)', no_xlp)]:
        # patcho temporaneamente SECTORS_SYSTEM per il backtest
        orig = us.SECTORS_SYSTEM
        us.SECTORS_SYSTEM = secs
        try:
            r = us.build_mode_output(prices, secs, 'aggressive')
        finally:
            us.SECTORS_SYSTEM = orig
        st = r['stats']
        print(f"{label:22} {st.get('total_return'):>6.0f}% {st.get('max_drawdown'):>6.1f}% "
              f"{st.get('sharpe'):>7.2f} {st.get('n_operations_total'):>5}")

if __name__ == '__main__':
    main()
