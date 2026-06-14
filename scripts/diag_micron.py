#!/usr/bin/env python3
"""
DIAGNOSI: perche' l'Adaptive non sceglie mai Micron (MU) in SOXX?
Per ogni revisione semestrale stampa:
 - se MU supera il filtro (dollar-volume top-15 + ROC13>0)
 - la sua posizione nel ranking dollar-volume
 - il confronto col titolo effettivamente scelto
"""
import sys, os
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb

def main():
    import yfinance as yf
    cands = sb.BASKETS['SOXX']
    need = set(cands) | {'SOXX', us.US_BENCHMARK}
    print(f"scarico {len(need)} ticker SOXX...")
    raw = yf.download(sorted(need), start=us.BACKTEST_START, interval='1wk',
                      auto_adjust=True, progress=False)
    prices = raw['Close']; dv = raw['Close']*raw['Volume']
    dates = prices.index

    # revisioni semestrali
    revs = []
    for y in range(2019, 2027):
        for m in (1,7):
            rd = pd.Timestamp(year=y, month=m, day=1)
            if rd <= dates[-1]:
                idx = dates.searchsorted(rd)
                if idx < len(dates): revs.append((rd, idx))

    print(f"\n{'revisione':12} {'MU nei top15?':14} {'rank_DV':>8} {'MU_ROC13':>9} {'top3 paniere':30}")
    print('-'*80)
    for rd, w in revs:
        lo = max(0, w - sb.DV_LOOKBACK_WEEKS)
        # dollar volume medio per tutti i candidati
        ranking = []
        mu_roc = None
        for tk in cands:
            if tk not in dv.columns: continue
            win = dv[tk].iloc[lo:w+1].dropna()
            if len(win) < sb.DV_LOOKBACK_WEEKS//2: continue
            adv = float(win.mean())
            if adv <= 0: continue
            # roc13
            s = prices[tk].iloc[:w+1].dropna()
            roc = (s.iloc[-1]/s.iloc[-14]-1)*100 if len(s)>=14 else None
            ranking.append((adv, tk, roc))
            if tk=='MU': mu_roc = roc
        ranking.sort(reverse=True)
        # applica filtro ROC>0 e prendi top15
        filtered = [(adv,tk,roc) for adv,tk,roc in ranking if roc is not None and roc>0][:sb.TOP_N]
        top_tickers = [tk for _,tk,_ in filtered]
        mu_in = 'MU' in top_tickers
        # rank di MU nel dollar-volume (prima del filtro)
        mu_rank = next((i+1 for i,(_,tk,_) in enumerate(ranking) if tk=='MU'), None)
        mu_roc_s = f"{mu_roc:+.1f}%" if mu_roc is not None else "n/a"
        top3 = ', '.join(top_tickers[:3])
        flag = 'SI' if mu_in else 'NO'
        # perche' escluso?
        reason=''
        if not mu_in and mu_rank:
            if mu_roc is not None and mu_roc<=0:
                reason=' [ROC<0!]'
            elif mu_rank>sb.TOP_N:
                reason=f' [rank {mu_rank}>15]'
            else:
                reason=' [fuori dopo filtro]'
        print(f"{str(rd.date()):12} {flag:14} {str(mu_rank):>8} {mu_roc_s:>9} {top3:30}{reason}")

if __name__=='__main__':
    main()
