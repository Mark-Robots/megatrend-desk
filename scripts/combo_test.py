#!/usr/bin/env python3
"""
CONFRONTO 4 combinazioni: filtro ROC {on/off} x stop-loss {on/off}.
Misura total, MaxDD, Sharpe, worst trade, e il contributo Consumi (XLP)
+ traccia DLTR/DG e MU per vedere il trade-off concreto.
"""
import sys, os
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb


def basket_at(sec, dollar_vol, prices, w_idx, use_roc):
    cands = sb.BASKETS.get(sec, [])
    lo = max(0, w_idx - sb.DV_LOOKBACK_WEEKS)
    scores = []
    for tk in cands:
        if tk not in dollar_vol.columns: continue
        win = dollar_vol[tk].iloc[lo:w_idx+1].dropna()
        if len(win) < sb.DV_LOOKBACK_WEEKS//2: continue
        adv = float(win.mean())
        if adv <= 0: continue
        if use_roc and tk in prices.columns:
            s = prices[tk].iloc[:w_idx+1].dropna()
            if len(s) < 14: continue
            roc13 = (s.iloc[-1]/s.iloc[-14]-1)*100
            if roc13 <= 0: continue
        scores.append((adv, tk))
    scores.sort(reverse=True)
    return [tk for _, tk in scores[:sb.TOP_N]]


def review_index_for(date, dates):
    y = date.year; cands = []
    for ry in (y-1, y):
        for m in sb.REVIEW_MONTHS:
            rd = pd.Timestamp(year=ry, month=m, day=1)
            if rd <= date: cands.append(rd)
    return min(dates.searchsorted(max(cands)), len(dates)-1) if cands else 0


def run(prices, dollar_vol, mode, use_roc, stop_pct):
    dates = prices.index; n = len(dates); last = dates[-1]
    sector_data = {}
    for sec in us.SECTORS_SYSTEM:
        if sec not in prices.columns: continue
        region = 'US' if sec in us.US_SECTORS_ETF else 'IT'
        bench = us.US_BENCHMARK if region=='US' else us.EU_BENCHMARK
        if bench not in prices.columns: continue
        rrg = us.calculate_rrg(prices[sec].dropna(), prices[bench].dropna(), 14)
        if rrg is None or rrg.empty: continue
        h = us.extract_signal_history_full(rrg, prices[sec].dropna(), 30)
        sector_data[sec] = [p for p in h if p['signal']=='IN']
    cache = {}; ops = []
    for sec, periods in sector_data.items():
        for p in periods:
            sd, ed = p['start_date'], p['end_date']
            try: si = dates.get_loc(sd)
            except KeyError:
                si = dates.searchsorted(sd)
                if si>=n: continue
            try: ei = dates.get_loc(ed)
            except KeyError:
                ei = dates.searchsorted(ed)
                if ei>=n: ei=n-1
            rev = review_index_for(dates[si], dates)
            key=(sec,rev,use_roc)
            if key not in cache: cache[key]=basket_at(sec,dollar_vol,prices,rev,use_roc)
            bsk=cache[key]
            if not bsk: continue
            best=us.select_best_at_week(sec,prices,si,{sec:bsk},mode=mode)
            if best is None: continue
            tk=best['ticker']
            if tk not in prices.columns: continue
            entry=float(prices[tk].iloc[si])
            if pd.isna(entry) or entry<=0: continue
            is_open=(ed==last) or (ei==n-1)
            nat=ei if is_open else min(ei+1,n-1)
            stop_idx=None
            if stop_pct is not None:
                th=entry*(1-stop_pct/100)
                for w in range(si+1,nat+1):
                    c=prices[tk].iloc[w]
                    if not pd.isna(c) and c<=th: stop_idx=w; break
            exit_idx=stop_idx if stop_idx is not None else nat
            xp=float(prices[tk].iloc[exit_idx])
            if pd.isna(xp) or xp<=0: continue
            ops.append({'tk':tk,'sec':sec,'perf':(xp/entry-1)*100,
                        'si':si,'ei':exit_idx,'entry_date':str(dates[si].date())})
    # equity
    cash=prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    world=prices[us.WORLD_TICKER] if us.WORLD_TICKER in prices.columns else None
    port=100.0; N=len(us.SECTORS_SYSTEM)
    sw=max(56,min((o['si'] for o in ops),default=56))
    eq=[]
    for w in range(sw,n):
        if w>sw:
            act=[o for o in ops if o['si']<=w-1 and o['ei']>=w-1]
            cr=0.0
            if cash is not None and w<len(cash):
                pc=cash.iloc[w-1]; cc=cash.iloc[w]
                if not pd.isna(pc) and not pd.isna(cc) and pc>0: cr=cc/pc-1
            ps=0.0; nv=0
            for o in act:
                pp=prices[o['tk']].iloc[w-1]; cp=prices[o['tk']].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp==0: continue
                ps+=cp/pp-1; nv+=1
            port*=(1+(ps/N)+cr*(N-nv)/N)
        eq.append(port)
    total=port-100
    peak=100; mdd=0
    for e in eq:
        peak=max(peak,e); mdd=min(mdd,(e/peak-1)*100)
    rets=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    sharpe=(np.mean(rets)/(np.std(rets) or 1e-9)*np.sqrt(52)) if rets else 0
    perfs=[o['perf'] for o in ops]
    xlp=sum(o['perf'] for o in ops if o['sec']=='SOXX')  # placeholder, sotto vero XLP
    xlp=sum(o['perf'] for o in ops if o['sec']=='XLP')
    mu=[round(o['perf'],0) for o in ops if o['tk']=='MU']
    dltrdg=[(o['tk'],round(o['perf'],0)) for o in ops if o['tk'] in ('DLTR','DG')]
    return {'total':round(total,0),'mdd':round(mdd,1),'sharpe':round(sharpe,2),
            'worst':round(min(perfs),1) if perfs else 0,'xlp':round(xlp,0),
            'n':len(ops),'mu':mu,'dltrdg':dltrdg}


def main():
    import yfinance as yf
    tks=set()
    for v in sb.BASKETS.values(): tks.update(v)
    tks.update(us.SECTORS_SYSTEM); tks.add(us.US_BENCHMARK); tks.add(us.EU_BENCHMARK)
    tks.add(us.CASH_TICKER); tks.add(us.WORLD_TICKER)
    print(f"scarico {len(tks)} ticker...")
    raw=yf.download(sorted(tks),start=us.BACKTEST_START,interval='1wk',auto_adjust=True,progress=False)
    prices=raw['Close']; dv=raw['Close']*raw['Volume']
    print(f"prezzi {prices.shape[1]}x{prices.shape[0]}\n")
    COMBOS=[('niente','off',None),('solo filtro','on',None),
            ('solo stop','off',20),('filtro+stop','on',20)]
    print(f"{'combo':14} {'total':>7} {'MaxDD':>7} {'Sharpe':>7} {'worst':>7} {'Consumi':>8} {'MU?':>6} {'DLTR/DG':>18}")
    print('-'*90)
    for label,roc,stop in COMBOS:
        r=run(prices,dv,"aggressive",roc=="on",stop)
        mu_s='SI' if r['mu'] else 'no'
        dd=','.join(f"{t}{p:+.0f}" for t,p in r['dltrdg']) or '-'
        print(f"{label:14} {r['total']:>6.0f}% {r['mdd']:>6}% {r['sharpe']:>7} {r['worst']:>6}% {r['xlp']:>7.0f}% {mu_s:>6} {dd:>18}")

if __name__=='__main__':
    main()
