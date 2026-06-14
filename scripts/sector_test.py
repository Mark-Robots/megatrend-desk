#!/usr/bin/env python3
"""
TEST: effetto di rimuovere settori dai 9 operativi (config filtro ROC + stop -20%).
Confronta: tutti i 9 settori vs senza Consumi (XLP) vs senza altri candidati deboli.
Misura total, MaxDD, Sharpe, e contributo per settore.
"""
import sys, os
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb

STOP_PCT = 20.0

def basket_at(sec, dv, prices, w):
    cands = sb.BASKETS.get(sec, [])
    lo = max(0, w - sb.DV_LOOKBACK_WEEKS)
    sc = []
    for tk in cands:
        if tk not in dv.columns: continue
        win = dv[tk].iloc[lo:w+1].dropna()
        if len(win) < sb.DV_LOOKBACK_WEEKS//2: continue
        adv = float(win.mean())
        if adv <= 0: continue
        s = prices[tk].iloc[:w+1].dropna()
        if len(s) < 14: continue
        if (s.iloc[-1]/s.iloc[-14]-1)*100 <= 0: continue
        sc.append((adv, tk))
    sc.sort(reverse=True)
    return [t for _, t in sc[:sb.TOP_N]]

def rev_idx(date, dates):
    y=date.year; c=[]
    for ry in (y-1,y):
        for m in sb.REVIEW_MONTHS:
            rd=pd.Timestamp(year=ry,month=m,day=1)
            if rd<=date: c.append(rd)
    return min(dates.searchsorted(max(c)),len(dates)-1) if c else 0

def run(prices, dv, sectors, mode='aggressive'):
    dates=prices.index; n=len(dates); last=dates[-1]
    N=len(sectors)
    sd_data={}
    for sec in sectors:
        if sec not in prices.columns: continue
        region='US' if sec in us.US_SECTORS_ETF else 'IT'
        bench=us.US_BENCHMARK if region=='US' else us.EU_BENCHMARK
        if bench not in prices.columns: continue
        rrg=us.calculate_rrg(prices[sec].dropna(),prices[bench].dropna(),14)
        if rrg is None or rrg.empty: continue
        h=us.extract_signal_history_full(rrg,prices[sec].dropna(),30)
        sd_data[sec]=[p for p in h if p['signal']=='IN']
    cache={}; ops=[]
    for sec,periods in sd_data.items():
        for p in periods:
            try: si=dates.get_loc(p['start_date'])
            except KeyError:
                si=dates.searchsorted(p['start_date'])
                if si>=n: continue
            try: ei=dates.get_loc(p['end_date'])
            except KeyError:
                ei=dates.searchsorted(p['end_date'])
                if ei>=n: ei=n-1
            rv=rev_idx(dates[si],dates); key=(sec,rv)
            if key not in cache: cache[key]=basket_at(sec,dv,prices,rv)
            bsk=cache[key]
            if not bsk: continue
            best=us.select_best_at_week(sec,prices,si,{sec:bsk},mode=mode)
            if best is None: continue
            tk=best['ticker']
            if tk not in prices.columns: continue
            entry=float(prices[tk].iloc[si])
            if pd.isna(entry) or entry<=0: continue
            is_open=(p['end_date']==last) or (ei==n-1)
            nat=ei if is_open else min(ei+1,n-1)
            stop=None
            if STOP_PCT:
                th=entry*(1-STOP_PCT/100)
                for w in range(si+1,nat+1):
                    c=prices[tk].iloc[w]
                    if not pd.isna(c) and c<=th: stop=w; break
            xi=stop if stop is not None else nat
            xp=float(prices[tk].iloc[xi])
            if pd.isna(xp) or xp<=0: continue
            ops.append({'tk':tk,'sec':sec,'perf':(xp/entry-1)*100,'si':si,'ei':xi})
    cash=prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    world=prices[us.WORLD_TICKER] if us.WORLD_TICKER in prices.columns else None
    port=100.0; sw=max(56,min((o['si'] for o in ops),default=56)); eq=[]
    for w in range(sw,n):
        if w>sw:
            act=[o for o in ops if o['si']<=w-1 and o['ei']>=w-1]
            cr=0.0
            if cash is not None and w<len(cash):
                pc=cash.iloc[w-1];cc=cash.iloc[w]
                if not pd.isna(pc) and not pd.isna(cc) and pc>0: cr=cc/pc-1
            ps=0.0;nv=0
            for o in act:
                pp=prices[o['tk']].iloc[w-1];cp=prices[o['tk']].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp==0: continue
                ps+=cp/pp-1;nv+=1
            port*=(1+(ps/N)+cr*(N-nv)/N)
        eq.append(port)
    total=port-100; peak=100;mdd=0
    for e in eq:
        peak=max(peak,e);mdd=min(mdd,(e/peak-1)*100)
    rets=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    sharpe=(np.mean(rets)/(np.std(rets) or 1e-9)*np.sqrt(52)) if rets else 0
    return {'total':round(total,0),'mdd':round(mdd,1),'sharpe':round(sharpe,2),'n':len(ops)}

def main():
    import yfinance as yf
    tks=set()
    for v in sb.BASKETS.values(): tks.update(v)
    tks.update(us.SECTORS_SYSTEM);tks.add(us.US_BENCHMARK);tks.add(us.EU_BENCHMARK)
    tks.add(us.CASH_TICKER);tks.add(us.WORLD_TICKER)
    print(f"scarico {len(tks)} ticker...")
    raw=yf.download(sorted(tks),start=us.BACKTEST_START,interval='1wk',auto_adjust=True,progress=False)
    prices=raw['Close'];dv=raw['Close']*raw['Volume']
    print(f"prezzi {prices.shape[1]}x{prices.shape[0]}\n")
    full=list(us.SECTORS_SYSTEM)
    no_xlp=[s for s in full if s!='XLP']
    no_xlp_xlf=[s for s in full if s not in ('XLP','XLF')]  # togli anche Finanziari (era debole)
    SCEN=[('9 settori (tutti)',full),('8 (senza Consumi)',no_xlp),('7 (no Consumi+Finanz)',no_xlp_xlf)]
    print(f"{'scenario':24} {'total':>7} {'MaxDD':>7} {'Sharpe':>7} {'n_op':>5}")
    print('-'*56)
    for label,secs in SCEN:
        r=run(prices,dv,secs)
        print(f"{label:24} {r['total']:>6.0f}% {r['mdd']:>6}% {r['sharpe']:>7} {r['n']:>5}")

if __name__=='__main__':
    main()
