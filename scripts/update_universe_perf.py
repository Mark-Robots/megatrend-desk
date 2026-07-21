#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UNIVERSO · PERFORMANCE SETTORE · MarkRoboT.S.
----------------------------------------------
Per ogni settore dell'universo che è OPERATIVO in stato "In rafforzamento" o
"Leader", genera la serie di performance dell'ETF settoriale DA QUANDO è entrato
in trend FINO A OGGI.

La pagina universo.html usa data/universe_perf.json per mostrare, al click su un
settore (solo Emergente/Leader), il grafico + la performance dalla data d'ingresso.
I titoli restano solo come elenco informativo (nella pagina, statici).

Da lanciare dove yfinance è raggiungibile (runner GitHub).
"""
import json, os, sys
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

UNIVERSE_DATA = os.path.join('data','universe_data.json')
SECTOR_DATA   = os.path.join('data','sector_data.json')
OUT_PATH      = os.path.join('data','universe_perf.json')

# ticker Yahoo dell'ETF di ogni settore (desk + extra)
SECTOR_ETF = {
    'SOXX':'SOXX','XLK':'XLK','XLE':'XLE','XLI':'XLI','IBB':'IBB','XLV':'XLV',
    'XLP':'XLP','XLF':'XLF',
    'EXH5':'EXH5.DE','EXH6':'EXH6.DE','EXH1':'EXH1.DE','EXV1':'EXV1.DE','EXH4':'EXH4.DE',
    'XLY':'XLY','XLU':'XLU','XLB':'XLB','XLRE':'XLRE','XLC':'XLC',
    'DRIV':'DRIV','BOTZ':'BOTZ','ICLN':'ICLN','HACK':'HACK','ITA':'ITA',
    'EXV3':'EXV3.DE','EXV4':'EXV4.DE','EXH9':'EXH9.DE','EXH7':'EXH7.DE','EXV6':'EXV6.DE',
    'EXV5':'EXV5.DE','EXV7':'EXV7.DE','EXH3':'EXH3.DE',
}

# Grafico/perf per TUTTI i settori operativamente IN (segnale lisciato 4 settimane),
# non solo Emergente/Leader: anche un settore in rallentamento ma ancora in trend
# confermato mostra il suo percorso dalla data d'ingresso.


def load_states_and_dates():
    """Per ogni settore: stato attuale + data d'ingresso in trend."""
    info = {}
    # universo esteso
    try:
        u=json.load(open(UNIVERSE_DATA,encoding='utf-8'))
        for s in u.get('sectors',[]):
            info[s['ticker']]={'state':s.get('state'),'sig':s.get('opSignal'),
                               'entry':s.get('trend_start_date')}
    except Exception as e:
        print(f"[!] universe_data non letto: {e}",file=sys.stderr)
    # desk: la data d'ingresso vale SOLO se il segnale operativo e' IN
    # (opCurrent.start_date esiste anche per i periodi OUT e non va graficato)
    try:
        sd=json.load(open(SECTOR_DATA,encoding='utf-8'))
        for r in sd.get('ranking',{}).get('ranking',[]):
            oc=r.get('opCurrent') or {}
            info.setdefault(r['ticker'],{})
            info[r['ticker']]['state']=r.get('state')
            info[r['ticker']]['sig']=r.get('opSignal')
            if r.get('opSignal')=='IN' and oc.get('start_date'):
                info[r['ticker']]['entry']=oc['start_date']
    except Exception:
        pass
    return info


def main():
    info = load_states_and_dates()
    # settori da elaborare: tutti quelli operativamente IN con data d'ingresso
    todo = {sec:d for sec,d in info.items()
            if d.get('sig')=='IN' and d.get('entry')}
    print(f"Settori operativamente IN con data d'ingresso: {len(todo)}")
    if not todo:
        json.dump({'updated_at':datetime.now(timezone.utc).isoformat(),'sectors':{}},
                  open(OUT_PATH,'w',encoding='utf-8'))
        print("Nessun settore da elaborare."); return

    etfs=list(set(SECTOR_ETF[s] for s in todo if s in SECTOR_ETF))
    print(f"Scarico {len(etfs)} ETF...")
    data=yf.download(etfs,period='3y',interval='1wk',auto_adjust=True,progress=False)
    close=data['Close'] if 'Close' in data else data
    if isinstance(close,pd.Series): close=close.to_frame()
    if close.index.tz is not None: close.index=close.index.tz_localize(None)

    out={}
    for sec,d in todo.items():
        etf=SECTOR_ETF.get(sec)
        if not etf or etf not in close.columns: continue
        serie=close[etf].dropna()
        serie=serie[serie.index>=pd.Timestamp(d['entry'])]
        if len(serie)<2: continue
        perc=((serie/serie.iloc[0])-1)*100
        out[sec]={
            'entry_date':d['entry'],
            'perf':round(float(perc.iloc[-1]),1),
            'series':[round(float(v),2) for v in perc.values],
        }
        print(f"  {sec:8} da {d['entry']}: {out[sec]['perf']:+.1f}%")

    json.dump({'updated_at':datetime.now(timezone.utc).isoformat(),
               'note':'Performance ETF settore da ingresso trend (segnale lisciato 4 settimane). Tutti i settori IN.',
               'sectors':out},
              open(OUT_PATH,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
    print(f"\n[salvato] {OUT_PATH} — {len(out)} settori")


if __name__=='__main__':
    main()
