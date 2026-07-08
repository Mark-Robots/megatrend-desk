#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UNIVERSO · SERIE PREZZI TITOLI · MarkRoboT.S.
----------------------------------------------
Per ogni settore dell'universo, genera la serie di performance dei suoi titoli
rappresentativi DA QUANDO il settore è entrato in trend FINO A OGGI.

La pagina universo.html usa questo file (data/universe_stocks.json) per mostrare,
al passaggio del mouse su un titolo, un grafico SVG + la performance % dalla data
d'ingresso del settore.

Fatto in casa (yfinance + calcolo %), stesso stile del sistema Azioni del desk.
Da lanciare dove yfinance è raggiungibile (runner GitHub).
"""

import json, os, sys
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

UNIVERSE_DATA = os.path.join('data', 'universe_data.json')   # per le date d'ingresso
OUT_PATH      = os.path.join('data', 'universe_stocks.json')

# ── mappa NOME → TICKER di borsa (Yahoo) ────────────────────────────────
# suffissi: .DE Xetra, .MI Milano, .PA Parigi, .AS Amsterdam, .L Londra,
#           .SW Svizzera, .MC Madrid, .CO Copenhagen, .HK Hong Kong
TICKER = {
    # Semi / Tech USA
    'NVIDIA':'NVDA','AMD':'AMD','Broadcom':'AVGO','Micron':'MU','TSMC':'TSM',
    'Apple':'AAPL','Microsoft':'MSFT','Alphabet':'GOOGL','Oracle':'ORCL','Salesforce':'CRM',
    # Energy USA
    'ExxonMobil':'XOM','Chevron':'CVX','ConocoPhillips':'COP','Valero':'VLO',
    # Insurance / Luxury / Energy EU
    'Allianz':'ALV.DE','AXA':'CS.PA','Generali':'G.MI','Zurich':'ZURN.SW',
    'LVMH':'MC.PA','Herm\u00e8s':'RMS.PA','L\u2019Or\u00e9al':'OR.PA','Kering':'KER.PA',
    'Shell':'SHEL.L','TotalEnergies':'TTE.PA','BP':'BP.L','Eni':'ENI.MI',
    # Banks EU
    'UniCredit':'UCG.MI','Intesa Sanpaolo':'ISP.MI','Santander':'SAN.MC','BNP Paribas':'BNP.PA',
    # Indu / Health / Staples / Fin USA
    'Caterpillar':'CAT','Honeywell':'HON','GE':'GE','Boeing':'BA',
    'Amgen':'AMGN','Gilead':'GILD','Vertex':'VRTX','Regeneron':'REGN',
    'UnitedHealth':'UNH','Johnson & Johnson':'JNJ','Eli Lilly':'LLY','Pfizer':'PFE',
    'P&G':'PG','Coca-Cola':'KO','PepsiCo':'PEP','Walmart':'WMT',
    'Siemens':'SIE.DE','Schneider Electric':'SU.PA','ABB':'ABBN.SW','Airbus':'AIR.PA',
    'JPMorgan':'JPM','Bank of America':'BAC','Goldman Sachs':'GS','Visa':'V',
    # Discretionary / Utilities / Materials / RealEstate / Comm USA
    'Amazon':'AMZN','Tesla':'TSLA','Home Depot':'HD','McDonald\u2019s':'MCD','Nike':'NKE',
    'NextEra':'NEE','Southern Co':'SO','Duke Energy':'DUK','Constellation':'CEG',
    'Linde':'LIN','Sherwin-Williams':'SHW','Freeport':'FCX','Ecolab':'ECL',
    'Prologis':'PLD','American Tower':'AMT','Equinix':'EQIX','Welltower':'WELL',
    'Meta':'META','Netflix':'NFLX','Disney':'DIS','T-Mobile':'TMUS',
    # Tematici
    'Rivian':'RIVN','BYD':'BYDDY','General Motors':'GM','Ford':'F',
    'Intuitive Surgical':'ISRG','Keyence':'6861.T','Fanuc':'6954.T',
    'First Solar':'FSLR','Enphase':'ENPH','Iberdrola':'IBE.MC','Vestas':'VWS.CO','Orsted':'ORSTED.CO',
    'Palo Alto':'PANW','CrowdStrike':'CRWD','Zscaler':'ZS','Fortinet':'FTNT','Cloudflare':'NET',
    'RTX':'RTX','Lockheed Martin':'LMT','GE Aerospace':'GE','Northrop':'NOC',
    # Europa extra
    'SAP':'SAP.DE','ASML':'ASML.AS','Infineon':'IFX.DE','Capgemini':'CAP.PA',
    'Novo Nordisk':'NOVO-B.CO','AstraZeneca':'AZN.L','Roche':'ROG.SW','Novartis':'NOVN.SW',
    'Enel':'ENEL.MI','E.ON':'EOAN.DE','National Grid':'NG.L',
    'Nestl\u00e9':'NESN.SW','Unilever':'ULVR.L','Diageo':'DGE.L','Danone':'BN.PA',
    'Air Liquide':'AI.PA','BASF':'BAS.DE','Rio Tinto':'RIO.L','Glencore':'GLEN.L',
    'Mercedes-Benz':'MBG.DE','BMW':'BMW.DE','Volkswagen':'VOW3.DE','Stellantis':'STLAM.MI',
    'Solvay':'SOLB.BR',
    'Deutsche Telekom':'DTE.DE','Vodafone':'VOD.L','Orange':'ORA.PA','Telef\u00f3nica':'TEF.MC',
}


def load_sector_stocks():
    """Mappa settore→titoli, letta dal JS della pagina (incorporata qui per autonomia)."""
    return {
        'SOXX':['NVIDIA','AMD','Broadcom','Micron','TSMC'],
        'XLK':['Apple','Microsoft','Alphabet','Oracle','Salesforce'],
        'XLE':['ExxonMobil','Chevron','ConocoPhillips','Valero'],
        'EXH5':['Allianz','AXA','Generali','Zurich'],
        'EXH6':['LVMH','Herm\u00e8s','L\u2019Or\u00e9al','Kering'],
        'EXH1':['Shell','TotalEnergies','BP','Eni'],
        'EXV1':['UniCredit','Intesa Sanpaolo','Santander','BNP Paribas'],
        'XLI':['Caterpillar','Honeywell','GE','Boeing'],
        'IBB':['Amgen','Gilead','Vertex','Regeneron'],
        'XLV':['UnitedHealth','Johnson & Johnson','Eli Lilly','Pfizer'],
        'XLP':['P&G','Coca-Cola','PepsiCo','Walmart'],
        'EXH4':['Siemens','Schneider Electric','ABB','Airbus'],
        'XLF':['JPMorgan','Bank of America','Goldman Sachs','Visa'],
        'XLY':['Amazon','Tesla','Home Depot','McDonald\u2019s','Nike'],
        'XLU':['NextEra','Southern Co','Duke Energy','Constellation'],
        'XLB':['Linde','Sherwin-Williams','Freeport','Ecolab'],
        'XLRE':['Prologis','American Tower','Equinix','Welltower'],
        'XLC':['Meta','Alphabet','Netflix','Disney','T-Mobile'],
        'DRIV':['Tesla','Rivian','BYD','General Motors','Ford'],
        'BOTZ':['NVIDIA','Intuitive Surgical','ABB','Keyence','Fanuc'],
        'ICLN':['First Solar','Enphase','Iberdrola','Vestas','Orsted'],
        'HACK':['Palo Alto','CrowdStrike','Zscaler','Fortinet','Cloudflare'],
        'ITA':['RTX','Boeing','Lockheed Martin','GE Aerospace','Northrop'],
        'EXV3':['SAP','ASML','Infineon','Capgemini'],
        'EXV4':['Novo Nordisk','AstraZeneca','Roche','Novartis'],
        'EXH9':['Iberdrola','Enel','E.ON','National Grid'],
        'EXH7':['Nestl\u00e9','Unilever','Diageo','Danone'],
        'EXV6':['Air Liquide','BASF','Rio Tinto','Glencore'],
        'EXV5':['Mercedes-Benz','BMW','Volkswagen','Stellantis'],
        'EXV7':['Air Liquide','BASF','Linde','Solvay'],
        'EXH3':['Deutsche Telekom','Vodafone','Orange','Telef\u00f3nica'],
    }


def load_entry_dates():
    """Legge da universe_data.json (+ eventualmente sector_data) la data d'ingresso
    in trend di ogni settore, per sapere da dove far partire la serie."""
    dates = {}
    # universo esteso
    try:
        u = json.load(open(UNIVERSE_DATA, encoding='utf-8'))
        for s in u.get('sectors', []):
            d = s.get('trend_start_date')
            if d:
                dates[s['ticker']] = d
    except Exception as e:
        print(f"[!] universe_data.json non letto: {e}", file=sys.stderr)
    # desk (per i 13): opCurrent.start_date
    try:
        sd = json.load(open(os.path.join('data','sector_data.json'), encoding='utf-8'))
        for r in sd.get('ranking',{}).get('ranking',[]):
            oc = r.get('opCurrent') or {}
            if oc.get('start_date'):
                dates.setdefault(r['ticker'], oc['start_date'])
    except Exception:
        pass
    return dates


def main():
    sector_stocks = load_sector_stocks()
    entry_dates = load_entry_dates()

    # raccolgo tutti i ticker unici da scaricare
    all_names = set()
    for lst in sector_stocks.values():
        all_names.update(lst)
    symbols = {}
    missing = []
    for nm in all_names:
        tk = TICKER.get(nm)
        if tk: symbols[nm] = tk
        else: missing.append(nm)
    if missing:
        print(f"[!] senza ticker (saltati): {missing}", file=sys.stderr)

    print(f"Scarico {len(symbols)} titoli (settimanale, max)...")
    yahoo_syms = list(set(symbols.values()))
    data = yf.download(yahoo_syms, period='3y', interval='1wk',
                       auto_adjust=True, progress=False)
    close = data['Close'] if 'Close' in data else data
    if isinstance(close, pd.Series):
        close = close.to_frame()
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)

    # data di default se un settore non ha entry date: 1 gennaio anno corrente
    default_start = f"{datetime.now().year}-01-01"

    out_sectors = {}
    for sec, names in sector_stocks.items():
        start = entry_dates.get(sec, default_start)
        start_ts = pd.Timestamp(start)
        titoli = []
        for nm in names:
            tk = symbols.get(nm)
            if not tk or tk not in close.columns:
                continue
            serie = close[tk].dropna()
            serie = serie[serie.index >= start_ts]
            if len(serie) < 2:
                continue
            base = serie.iloc[0]
            perc = ((serie / base) - 1) * 100
            pts = [round(float(v), 2) for v in perc.values]
            titoli.append({
                'name': nm,
                'ticker': tk,
                'from': start,
                'perf': round(float(perc.iloc[-1]), 1),
                'series': pts,   # % rispetto alla data d'ingresso settore
            })
        if titoli:
            out_sectors[sec] = {'entry_date': start, 'stocks': titoli}
        print(f"  {sec:8} da {start}: {len(titoli)} titoli")

    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'note': 'Serie % dei titoli da quando il settore è entrato in trend. Fonte yfinance, settimanale.',
        'sectors': out_sectors,
    }
    os.makedirs('data', exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\n[salvato] {OUT_PATH} — {len(out_sectors)} settori con titoli")


if __name__ == '__main__':
    main()
