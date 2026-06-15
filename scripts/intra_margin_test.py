#!/usr/bin/env python3
"""
TEST rotazione intra-settore con DOPPIA condizione (config Adaptive PIT+roc+stop -20%).

Ruota il titolo SOLO se:
  (1) il titolo detenuto e' debole: il suo score di selezione e' <= 0
      (ha perso il momentum che lo aveva fatto entrare), E
  (2) il miglior altro titolo del settore ha uno score che SUPERA quello del
      detenuto di almeno MARGINE% (in valore assoluto di score).

Confronta: nessuna rotazione (base) vs margine +20%, +30%, +50%.
Stop -20% e uscita per settore OUT restano sempre validi.
Misura total/MaxDD/Sharpe/worst, rotazioni, e winner tagliati.
"""
import sys, os
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us
import sector_baskets as sb

STOP_PCT = 20.0

def basket_at(sec, dv, prices, w):
    cands = sb.BASKETS.get(sec, [])
    lo = max(0, w - sb.DV_LOOKBACK_WEEKS); sc=[]
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

def score_of(sec, prices, w, tk, mode):
    """score di un singolo titolo via la logica composite di produzione."""
    if tk not in prices.columns: return None
    s = prices[tk].iloc[:w+1].dropna()
    if len(s) < 14: return None
    r4=us.compute_roc(s,4); r13=us.compute_roc(s,13); r52=us.compute_roc(s,52)
    return us.composite_score(r4, r13, r52, mode)

def best_of(sec, prices, w, basket, mode):
    avail={'__':[t for t in basket if t in prices.columns]}
    return us.select_best_at_week(sec, prices, w, {sec:[t for t in basket if t in prices.columns]}, mode=mode)

def run(prices, dv, mode, margin):
    """margin=None -> nessuna rotazione. Altrimenti soglia % di score."""
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
    cache={}; trades=[]; n_rot=0; cut=[]
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
            cur=si
            while cur < nat:
                best=best_of(sec,prices,cur,bsk,mode)
                if best is None: break
                tk=best['ticker']; entry=float(prices[tk].iloc[cur])
                if pd.isna(entry) or entry<=0: break
                th=entry*(1-STOP_PCT/100); exit_w=nat; reason='settore_out'
                for w in range(cur+1,nat+1):
                    c=prices[tk].iloc[w]
                    if not pd.isna(c) and c<=th: exit_w=w; reason='stop'; break
                    if margin is not None:
                        # doppia condizione
                        held_sc=score_of(sec,prices,w,tk,mode)
                        if held_sc is not None and held_sc<=0:
                            alt=best_of(sec,prices,w,[t for t in bsk if t!=tk],mode)
                            if alt is not None:
                                alt_sc=alt['score']
                                # alternativa supera il detenuto di almeno margin%
                                if held_sc<=0 and alt_sc>0 and (alt_sc-held_sc)>=abs(held_sc)*margin/100 + 1e-9:
                                    exit_w=w; reason='rotate'; break
                xp=float(prices[tk].iloc[exit_w])
                if pd.isna(xp) or xp<=0: break
                trades.append({'tk':tk,'sec':sec,'perf':(xp/entry-1)*100,'si':cur,'ei':exit_w})
                if reason=='rotate':
                    n_rot+=1
                    fut=prices[tk].iloc[exit_w:nat+1].dropna()
                    if len(fut)>1 and fut.iloc[-1]>entry: cut.append((tk,round((fut.iloc[-1]/entry-1)*100,0)))
                    cur=exit_w
                else:
                    break
    cash=prices[us.CASH_TICKER] if us.CASH_TICKER in prices.columns else None
    N=len(us.SECTORS_SYSTEM); port=100.0
    sw=max(56,min((t['si'] for t in trades),default=56)); eq=[]
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
            'n_rot':n_rot,'n_cut':len(cut),'cut':cut[:6]}

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
    print(f"{'regola':24} {'total':>7} {'MaxDD':>7} {'Sharpe':>7} {'worst':>7} {'trade':>6} {'rotaz':>6} {'winner tagl':>11}")
    print('-'*82)
    for label,mg in [('base (no rotazione)',None),('margine +20%',20),('margine +30%',30),('margine +50%',50)]:
        r=run(prices,dv,'aggressive',mg)
        print(f"{label:24} {r['total']:>6.0f}% {r['mdd']:>6}% {r['sharpe']:>7} {r['worst']:>6}% {r['n']:>6} {r['n_rot']:>6} {r['n_cut']:>11}")
        if r['cut']: print(f"     tagliati: {r['cut']}")

if __name__=='__main__':
    main()
