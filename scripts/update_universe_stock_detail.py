#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UNIVERSO · TITOLI: GRAFICO 1 ANNO + FONDAMENTALI · MarkRoboT.S.
-----------------------------------------------------------------
Per ogni titolo rappresentativo dei settori dell'universo, genera:
  - serie prezzi normalizzata a 1 anno (per il grafico)
  - dati fondamentali (capitalizzazione, P/E, dividend yield, settore, range 52w)

La pagina universo.html usa data/universe_stock_detail.json: cliccando un titolo
nel pannello del settore si apre una scheda con grafico a 1 anno e i fondamentali.

Nota: i fondamentali richiedono una chiamata .info per titolo → lo script impiega
qualche minuto. Gira sul runner GitHub (settimanale), non serve realtime.
"""
import json, os, sys, time
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

OUT_PATH = os.path.join('data', 'universe_stock_detail.json')

# ── mappa NOME → TICKER (stessa della pagina) ───────────────────────────
TICKER = {
    'NVIDIA':'NVDA','AMD':'AMD','Broadcom':'AVGO','Micron':'MU','TSMC':'TSM',
    'Apple':'AAPL','Microsoft':'MSFT','Alphabet':'GOOGL','Oracle':'ORCL','Salesforce':'CRM',
    'ExxonMobil':'XOM','Chevron':'CVX','ConocoPhillips':'COP','Valero':'VLO',
    'Allianz':'ALV.DE','AXA':'CS.PA','Generali':'G.MI','Zurich':'ZURN.SW',
    'LVMH':'MC.PA','Herm\u00e8s':'RMS.PA','L\u2019Or\u00e9al':'OR.PA','Kering':'KER.PA',
    'Shell':'SHEL.L','TotalEnergies':'TTE.PA','BP':'BP.L','Eni':'ENI.MI',
    'UniCredit':'UCG.MI','Intesa Sanpaolo':'ISP.MI','Santander':'SAN.MC','BNP Paribas':'BNP.PA',
    'Caterpillar':'CAT','Honeywell':'HON','GE':'GE','Boeing':'BA',
    'Amgen':'AMGN','Gilead':'GILD','Vertex':'VRTX','Regeneron':'REGN',
    'UnitedHealth':'UNH','Johnson & Johnson':'JNJ','Eli Lilly':'LLY','Pfizer':'PFE',
    'P&G':'PG','Coca-Cola':'KO','PepsiCo':'PEP','Walmart':'WMT',
    'Siemens':'SIE.DE','Schneider Electric':'SU.PA','ABB':'ABBN.SW','Airbus':'AIR.PA',
    'JPMorgan':'JPM','Bank of America':'BAC','Goldman Sachs':'GS','Visa':'V',
    'Amazon':'AMZN','Tesla':'TSLA','Home Depot':'HD','McDonald\u2019s':'MCD','Nike':'NKE',
    'NextEra':'NEE','Southern Co':'SO','Duke Energy':'DUK','Constellation':'CEG',
    'Linde':'LIN','Sherwin-Williams':'SHW','Freeport':'FCX','Ecolab':'ECL',
    'Prologis':'PLD','American Tower':'AMT','Equinix':'EQIX','Welltower':'WELL',
    'Meta':'META','Netflix':'NFLX','Disney':'DIS','T-Mobile':'TMUS',
    'Rivian':'RIVN','BYD':'BYDDY','General Motors':'GM','Ford':'F',
    'Intuitive Surgical':'ISRG','Keyence':'6861.T','Fanuc':'6954.T',
    'First Solar':'FSLR','Enphase':'ENPH','Iberdrola':'IBE.MC','Vestas':'VWS.CO','Orsted':'ORSTED.CO',
    'Palo Alto':'PANW','CrowdStrike':'CRWD','Zscaler':'ZS','Fortinet':'FTNT','Cloudflare':'NET',
    'RTX':'RTX','Lockheed Martin':'LMT','GE Aerospace':'GE','Northrop':'NOC',
    'SAP':'SAP.DE','ASML':'ASML.AS','Infineon':'IFX.DE','Capgemini':'CAP.PA',
    'Novo Nordisk':'NOVO-B.CO','AstraZeneca':'AZN.L','Roche':'ROG.SW','Novartis':'NOVN.SW',
    'Enel':'ENEL.MI','E.ON':'EOAN.DE','National Grid':'NG.L',
    'Nestl\u00e9':'NESN.SW','Unilever':'ULVR.L','Diageo':'DGE.L','Danone':'BN.PA',
    'Air Liquide':'AI.PA','BASF':'BAS.DE','Rio Tinto':'RIO.L','Glencore':'GLEN.L',
    'Mercedes-Benz':'MBG.DE','BMW':'BMW.DE','Volkswagen':'VOW3.DE','Stellantis':'STLAM.MI',
    'Solvay':'SOLB.BR',
    'Deutsche Telekom':'DTE.DE','Vodafone':'VOD.L','Orange':'ORA.PA','Telef\u00f3nica':'TEF.MC',
}

# valuta di riferimento per ogni suffisso (per etichettare la capitalizzazione)
CCY = {'.DE':'EUR','.PA':'EUR','.MI':'EUR','.AS':'EUR','.MC':'EUR','.BR':'EUR',
       '.L':'GBP','.SW':'CHF','.CO':'DKK','.T':'JPY'}


def fmt_cap(v, ccy='USD'):
    """Capitalizzazione leggibile: 3.2 T, 845 Mld, 12 Mld..."""
    if not v or v <= 0: return None
    if v >= 1e12: return f"{v/1e12:.2f} T {ccy}"
    if v >= 1e9:  return f"{v/1e9:.0f} Mld {ccy}"
    if v >= 1e6:  return f"{v/1e6:.0f} Mln {ccy}"
    return f"{v:.0f} {ccy}"


def currency_of(sym):
    for suf, c in CCY.items():
        if sym.endswith(suf): return c
    return 'USD'


def main():
    names = sorted(TICKER)
    syms = sorted(set(TICKER.values()))
    print(f"{len(names)} titoli, {len(syms)} simboli unici")

    # 1) prezzi a 1 anno (una sola chiamata bulk, veloce)
    print("Scarico prezzi 1 anno (settimanale)...")
    data = yf.download(syms, period='1y', interval='1wk',
                       auto_adjust=True, progress=False)
    close = data['Close'] if 'Close' in data else data
    if isinstance(close, pd.Series): close = close.to_frame()
    if close.index.tz is not None: close.index = close.index.tz_localize(None)

    # 2) fondamentali (una chiamata per titolo → lento ma settimanale)
    print("Scarico fondamentali (una chiamata per titolo, pazienza)...")
    out = {}
    for i, nm in enumerate(names, 1):
        sym = TICKER[nm]
        rec = {'name': nm, 'ticker': sym}
        # serie prezzi normalizzata (% dal primo punto disponibile)
        if sym in close.columns:
            s = close[sym].dropna()
            if len(s) >= 2:
                perc = ((s / s.iloc[0]) - 1) * 100
                rec['series'] = [round(float(v), 2) for v in perc.values]
                rec['perf_1y'] = round(float(perc.iloc[-1]), 1)
                rec['last'] = round(float(s.iloc[-1]), 2)
        # fondamentali
        try:
            info = yf.Ticker(sym).info or {}
            ccy = info.get('currency') or currency_of(sym)
            rec['currency'] = ccy
            rec['cap'] = fmt_cap(info.get('marketCap'), ccy)
            pe = info.get('trailingPE') or info.get('forwardPE')
            rec['pe'] = round(float(pe), 1) if pe and pe > 0 else None
            dy = info.get('dividendYield')
            if dy:
                dy = dy * 100 if dy < 1 else dy   # yfinance a volte 0.023, a volte 2.3
                rec['div_yield'] = round(float(dy), 2)
            rec['sector'] = info.get('sector')
            rec['industry'] = info.get('industry')
            lo, hi = info.get('fiftyTwoWeekLow'), info.get('fiftyTwoWeekHigh')
            if lo and hi:
                rec['range52'] = [round(float(lo), 2), round(float(hi), 2)]
        except Exception as e:
            print(f"  [!] {nm} ({sym}) fondamentali non recuperati: {e}", file=sys.stderr)
        out[nm] = rec
        if i % 20 == 0:
            print(f"  ...{i}/{len(names)}")
        time.sleep(0.15)   # gentile con l'endpoint

    payload = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'note': 'Grafico 1 anno (serie % settimanale) e fondamentali per titolo.',
        'stocks': out,
    }
    os.makedirs('data', exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    ok = sum(1 for v in out.values() if v.get('series'))
    print(f"\n[salvato] {OUT_PATH} — {len(out)} titoli ({ok} con serie prezzi)")


if __name__ == '__main__':
    main()
