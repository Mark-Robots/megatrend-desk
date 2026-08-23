#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST SIZING · A/B/C — confronto onesto delle regole di dimensionamento
sul sistema ETF (stessi segnali lisciati validati, stessi prezzi del backtest).

  A · CASSETTI INDIPENDENTI (il validato): ogni settore ha la sua sotto-equity;
      alle uscite il ricavato resta nel cassetto e rientra per intero.
  B · POZZO COMUNE: alle uscite il ricavato torna nel patrimonio collettivo;
      ogni nuovo ingresso investe 1/9 del totale corrente (posizioni+cash).
  C · POZZO + RIBILANCIAMENTO ANNUALE dell'investito (equal weight tra aperte).
      NB: C ignora i costi fiscali delle vendite di ribilancio -> è LUSINGATA.

Legge data/sector_data.json (nessun download): eseguibile ovunque, anche in Actions.
"""
import json, statistics, sys, os

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join('data', 'sector_data.json')
sd = json.load(open(PATH))
sim = sd['portfolio_simulation']; dates = sim['dates']
SY = [s['ticker_raw'] for s in sd['ranking']['ranking'] if s['opSignal'] != 'INFO']
N = len(SY)

PX, SG = {}, {}
for t in SY:
    sec = sim['sectors'][t]
    PX[t] = sec['prices']
    SG[t] = sec['signals_by_ts'][str(sec['default_ts'])]

def held(t, i): return i >= 1 and SG[t][i-1]
def ret(t, i):
    p0, p1 = PX[t][i-1], PX[t][i]
    return (p1/p0) if (p0 and p1 is not None) else 1.0

def metrics(eq):
    yrs = (len(eq)-1)/52
    cagr = (eq[-1]/eq[0])**(1/yrs)-1
    pk, mdd = eq[0], 0.0
    for v in eq:
        pk = max(pk, v); mdd = min(mdd, v/pk-1)
    return (eq[-1]/eq[0]-1)*100, cagr*100, mdd*100

def run_A():
    sub = {t: 100.0/N for t in SY}
    eq, conc = [], []
    for i in range(len(dates)):
        if i:
            for t in SY:
                if held(t, i): sub[t] *= ret(t, i)
        tot = sum(sub.values()); eq.append(tot)
        inv = [sub[t] for t in SY if held(t, i)]
        conc.append(max(inv)/tot*100 if inv else 0.0)
    return eq, conc, None

def run_pool(rebalance_every=None):
    cash, pos = 100.0, {}
    eq, conc, short = [], [], 0
    for i in range(len(dates)):
        if i:
            for t in list(pos):
                if held(t, i): pos[t] *= ret(t, i)
            for t in list(pos):
                if not held(t, i): cash += pos.pop(t)
            for t in SY:
                if held(t, i) and t not in pos and not held(t, i-1):
                    tot = cash + sum(pos.values())
                    stake = tot/N
                    if stake > cash: stake = cash; short += 1
                    if stake > 0: pos[t] = stake; cash -= stake
            if rebalance_every and i % rebalance_every == 0 and pos:
                inv = sum(pos.values()); n = len(pos)
                for t in pos: pos[t] = inv/n
        tot = cash + sum(pos.values()); eq.append(tot)
        conc.append(max(pos.values())/tot*100 if pos else 0.0)
    return eq, conc, short

def report():
    res = {'A cassetti': run_A(), 'B pozzo': run_pool(), 'C pozzo+ribil.': run_pool(52)}
    print(f"Periodo: {dates[0]} -> {dates[-1]}  ({(len(dates)-1)/52:.1f} anni, {N} settori)\n")
    hdr = f"{'':24}" + "".join(f"{k:>16}" for k in res)
    print(hdr)
    rows = []
    m = {k: metrics(v[0]) for k, v in res.items()}
    rows.append(("Totale", [f"{m[k][0]:+.0f}%" for k in res]))
    rows.append(("CAGR", [f"{m[k][1]:+.2f}%" for k in res]))
    rows.append(("MaxDD", [f"{m[k][2]:+.1f}%" for k in res]))
    rows.append(("Concentraz. media", [f"{statistics.mean(v[1]):.1f}%" for v in res.values()]))
    rows.append(("Concentraz. massima", [f"{max(v[1]):.1f}%" for v in res.values()]))
    rows.append(("% settimane sopra 33%", [f"{sum(1 for x in v[1] if x>33)/len(v[1])*100:.1f}%" for v in res.values()]))
    for lab, vals in rows:
        print(f"{lab:24}" + "".join(f"{v:>16}" for v in vals))
    print(f"\nIngressi con cash insufficiente in B: {res['B pozzo'][2]}")
    print(f"Sanity: equity finale A = {res['A cassetti'][0][-1]:.1f} (deve coincidere con la portfolio_equity pubblicata)")

if __name__ == '__main__':
    report()
