#!/usr/bin/env python3
"""
TEST rotazione intra-settore (config Adaptive: PIT + ROC>0 + stop -20%).

Confronta due regole, a parita' di rotation dei settori e selezione paniere:
 ATTUALE  : 1 titolo per tutta la durata del periodo IN del settore.
 ROTAZIONE: se il titolo detenuto scende a ROC13<=0, ESCE e entra subito il
            miglior altro titolo del settore (ROC13>0). Il settore resta investito
            finche' e' IN. Stop -20% e uscita per settore OUT restano validi.

Misura total/MaxDD/Sharpe/worst, n. trade, n. rotazioni, e se taglia i mega-trend.
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

def roc13_at(prices, tk, w):
    if tk not in prices.columns: return None
    s = prices[tk].iloc[:w+1].dropna()
    if len(s) < 14: return None
    return (s.iloc[-1]/s.iloc[-14]-1)*100

def best_in_basket(sec, prices, w, basket, mode):
    """miglior titolo del basket con ROC>0 a w, via select_best_at_week."""
    avail = [t for t in basket if (roc13_at(prices,t,w) or -1) > 0 and t in prices.columns]
    if not avail: return None
    return us.select_best_at_week(sec, prices, w, {sec: avail}, mode=mode)

def run(prices, dv, mode, rotate):
    dates=prices.index; n=len(dates); last=dates[-1]
    sectors={}
    for sec in us.SECTORS_SYSTEM:
        if sec not in prices.columns: continue
        region='US' if sec in us.US_SECTORS_ETF else 'IT'
        bench=us.US_BENCHMARK if region=='US' else us.EU_BENCHMARK
        if bench not in prices.columns: continue
        rrg=us.calculate_rrg(prices[sec].dropna(),prices[bench].dropna(),14)
        if rrg is None or rrg.empty: continue
        h=us.extract_signal_history_full(rrg,prices[sec].dropna(),30)
        sectors[sec]=[p for p in h if p['signal']=='IN']
    cache={}; trades=[]; n_rot=0; cut_winners=[]
    for sec,periods in sectors.items():
        for p in periods:
            try: si=dates.get_loc(p['start_date'])
            except KeyError:
                si=dates.searchsorted(p['start_date'])
                if si>=n: continue
            try: ei=dates.get_loc(p['end_date'])
            except KeyError:
                ei=dates.searchsorted(p['end_date'])
                if ei>=n: ei=n-1
            is_open=(p['end_date']==last) or (ei==n-1)
            nat=ei if is_open else min(ei+1,n-1)
            rv=rev_idx(dates[si],dates); key=(sec,rv)
            if key not in cache: cache[key]=basket_at(sec,dv,prices,rv)
            bsk=cache[key]
            if not bsk: continue

            # gestione del periodo: uno o piu' trade (se rotate)
            cur_w = si
            while cur_w < nat:
                best = best_in_basket(sec, prices, cur_w, bsk, mode)
                if best is None: break
                tk=best['ticker']
                entry=float(prices[tk].iloc[cur_w])
                if pd.isna(entry) or entry<=0: break
                th=entry*(1-STOP_PCT/100)
                # scorre fino a: stop, ROC<0 (se rotate), o fine periodo
                exit_w=nat; reason='settore_out'
                for w in range(cur_w+1, nat+1):
                    c=prices[tk].iloc[w]
                    if not pd.isna(c) and c<=th:
                        exit_w=w; reason='stop'; break
                    if rotate:
                        r=roc13_at(prices,tk,w)
                        if r is not None and r<=0:
                            exit_w=w; reason='roc_out'; break
                xp=float(prices[tk].iloc[exit_w])
                if pd.isna(xp) or xp<=0: break
                perf=(xp/entry-1)*100
                trades.append({'tk':tk,'sec':sec,'perf':perf,'si':cur_w,'ei':exit_w,'reason':reason})
                if reason=='roc_out':
                    n_rot+=1
                    # il titolo sarebbe risalito? (taglio winner?)
                    fut=prices[tk].iloc[exit_w:nat+1].dropna()
                    if len(fut)>1 and fut.iloc[-1]>entry:
                        cut_winners.append((tk,round((fut.iloc[-1]/entry-1)*100,0)))
                if reason!='roc_out' or not rotate:
                    break  # stop o fine settore: chiudi il periodo
                cur_w = exit_w  # rotazione: riparte dal punto di uscita
    # equity
    cash=prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    N=len(us.SECTORS_SYSTEM)
    port=100.0; sw=max(56,min((t['si'] for t in trades),default=56)); eq=[]
    for w in range(sw,n):
        if w>sw:
            act=[t for t in trades if t['si']<=w-1 and t['ei']>=w-1]
            cr=0.0
            if cash is not None and w<len(cash):
                pc=cash.iloc[w-1];cc=cash.iloc[w]
                if not pd.isna(pc) and not pd.isna(cc) and pc>0: cr=cc/pc-1
            ps=0.0;nv=0
            for t in act:
                pp=prices[t['tk']].iloc[w-1];cp=prices[t['tk']].iloc[w]
                if pd.isna(pp) or pd.isna(cp) or pp==0: continue
                ps+=cp/pp-1;nv+=1
            port*=(1+(ps/N)+cr*(N-nv)/N)
        eq.append(port)
    total=port-100; peak=100;mdd=0
    for e in eq:
        peak=max(peak,e);mdd=min(mdd,(e/peak-1)*100)
    rets=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    sharpe=(np.mean(rets)/(np.std(rets) or 1e-9)*np.sqrt(52)) if rets else 0
    perfs=[t['perf'] for t in trades]
    return {'total':round(total,0),'mdd':round(mdd,1),'sharpe':round(sharpe,2),
            'worst':round(min(perfs),1) if perfs else 0,'n':len(trades),
            'n_rot':n_rot,'cut_winners':cut_winners[:8],'n_cut':len(cut_winners)}

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
    print(f"{'regola':28} {'total':>7} {'MaxDD':>7} {'Sharpe':>7} {'worst':>7} {'trade':>6} {'rotazioni':>9} {'winner tagliati':>15}")
    print('-'*100)
    for label,rot in [('ATTUALE (1 titolo/settore)',False),('ROTAZIONE intra-settore',True)]:
        r=run(prices,dv,'aggressive',rot)
        print(f"{label:28} {r['total']:>6.0f}% {r['mdd']:>6}% {r['sharpe']:>7} {r['worst']:>6}% {r['n']:>6} {r['n_rot']:>9} {r['n_cut']:>15}")
        if r['cut_winners']:
            print(f"     winner tagliati (sarebbero risaliti): {r['cut_winners']}")

if __name__=='__main__':
    main()
