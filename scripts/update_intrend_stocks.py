#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPDATE INTREND STOCKS · le migliori 3 azioni di ogni settore in trend.

Per ciascun settore attualmente IN (sistema + universo) applica ESATTAMENTE
il metodo di selezione del portafoglio Azioni — compute_roc, assign_tag e
composite_score importati da update_stocks, filtro aggressive "chi corre
adesso" (ROC4>0, tag non squalificante), ordinamento per punteggio — e
pubblica le prime tre in data/intrend_stocks.json per la pagina intrend.html.
Solo classifica informativa: il portafoglio vero ne compra una per settore.
"""
import json, os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yfinance as yf
import pandas as pd
import update_stocks as us

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# titoli dei settori tematici dell'universo (stesse liste di universo.html)
EXTRA_UNIVERSE = {
    'HACK': ['PANW', 'CRWD', 'ZS', 'FTNT', 'NET'],
    'ICLN': ['FSLR', 'ENPH', 'IBE.MC', 'VWS.CO', 'ORSTED.CO'],
    'DRIV': ['TSLA', 'RIVN', 'BYDDY', 'GM', 'F'],
}
EXTRA_NAMES = {'PANW':'Palo Alto','CRWD':'CrowdStrike','ZS':'Zscaler','FTNT':'Fortinet','NET':'Cloudflare',
    'FSLR':'First Solar','ENPH':'Enphase','IBE.MC':'Iberdrola','VWS.CO':'Vestas','ORSTED.CO':'Orsted',
    'TSLA':'Tesla','RIVN':'Rivian','BYDDY':'BYD','GM':'General Motors','F':'Ford'}

def load(fn):
    try:
        with open(os.path.join(DATA_DIR, fn), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def candidates_for(key):
    """Universo titoli per la chiave settore (sistema o universo)."""
    for k in (key, key + '.DE'):
        if k in us.US_UNIVERSE: return us.US_UNIVERSE[k]
        if k in us.IT_UNIVERSE: return us.IT_UNIVERSE[k]
    return EXTRA_UNIVERSE.get(key, [])

def main():
    sd = load('sector_data.json')
    un = load('universe_data.json')

    sectors = []   # (key, nome)
    for s in ((sd.get('ranking') or {}).get('ranking') or []):
        if s.get('opSignal') == 'IN':
            sectors.append((s.get('ticker_raw') or s.get('ticker'), s.get('name')))
    for s in (un.get('sectors') or []):
        if s.get('opSignal') == 'IN':
            sectors.append((s.get('ticker'), s.get('name')))

    # ticker complessivi da scaricare
    all_tk = sorted({tk for key, _ in sectors for tk in candidates_for(key)})
    if not all_tk:
        print('nessun settore in trend'); return
    print(f'{len(sectors)} settori in trend, {len(all_tk)} titoli da valutare')

    px = yf.download(all_tk, period='420d', interval='1wk',
                     auto_adjust=True, progress=False)['Close']
    if isinstance(px, pd.Series):
        px = px.to_frame(all_tk[0])

    names = dict(getattr(us, 'STOCK_NAMES', {}) or {})
    names.update((load('stocks_data.json').get('stock_names') or {}))
    names.update(EXTRA_NAMES)

    out = {'updated_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
           'note': 'top 3 per settore in trend · stesso metodo di selezione del sistema Azioni (aggressive)',
           'sectors': {}}

    for key, nome in sectors:
        scored = []
        for tk in candidates_for(key):
            if tk not in px.columns: continue
            s = px[tk].dropna()
            if len(s) < 14: continue
            roc4 = us.compute_roc(s, 4)
            roc13 = us.compute_roc(s, 13)
            roc52 = us.compute_roc(s, 52)
            tag = us.assign_tag(roc13, roc52)
            sc = us.composite_score(roc4, roc13, roc52, 'aggressive')
            scored.append({'ticker': tk, 'name': names.get(tk, tk), 'tag': tag,
                           'roc4': roc4,
                           'roc13': round(roc13, 1) if roc13 is not None else None,
                           'score': round(sc, 2) if sc is not None else None})
        if not scored:
            continue
        # stesso ordine di preferenza del selettore aggressive
        rising = [x for x in scored if x['score'] is not None
                  and (x.get('roc4') or 0) > 0
                  and x['tag'] not in us.DISQUALIFYING_TAGS]
        pool = rising if rising else scored
        pool.sort(key=lambda x: (x['score'] if x['score'] is not None else -1e9), reverse=True)
        top = [{k: v for k, v in x.items() if k != 'roc4'} for x in pool[:3]]
        out['sectors'][key] = {'name': nome, 'stocks': top}
        print(f"  {key:8} -> " + ", ".join(f"{x['ticker']}({x['tag']})" for x in pool[:3]))

    dst = os.path.join(DATA_DIR, 'intrend_stocks.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'scritto {dst}: {len(out["sectors"])} settori')

if __name__ == '__main__':
    main()
