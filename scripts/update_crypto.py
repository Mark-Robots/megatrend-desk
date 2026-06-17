#!/usr/bin/env python3
"""
DMI Sentinel Crypto - replica Python della logica di Earnings_3_0.html
Modalita': long-only puro (DMI crossover su d1/d2 mensili, NO ema/volume/short).
Calcola l'equity per BTC/ETH/SOL e la media equipesata, con perf settimana/mese/YTD.
Salva data/crypto_data.json nel repo megatrend-desk.
"""
import json, os, sys, time, datetime
import urllib.request

# ── PARAMETRI MENSILI (estratti da Earnings_3_0.html) ──────────────────
PARAMS = json.load(open(os.path.join(os.path.dirname(__file__), 'crypto_params.json')))
SYMBOLS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT'}
DMI_PERIOD = 14
BINANCE = 'https://api.binance.com/api/v3/klines'


def get_params(asset, year, month):
    """replica getParams(a,y,m): mappa anno/mese -> soglie d1/d2/d3/d4."""
    p = PARAMS[asset]
    sy, sm = p['start']
    idx = (year - sy) * 12 + (month - sm)
    if idx < 0 or idx >= len(p['d1']):
        return {'d1': p['def'][0], 'd2': p['def'][1], 'd3': p['def'][2], 'd4': p['def'][3]}
    if p['d1'][idx] == 0 and p['d2'][idx] == 0 and p['d3'][idx] == 0 and p['d4'][idx] == 0:
        for i in range(idx - 1, -1, -1):
            if not (p['d1'][i] == 0 and p['d2'][i] == 0 and p['d3'][i] == 0 and p['d4'][i] == 0):
                return {'d1': p['d1'][i], 'd2': p['d2'][i], 'd3': p['d3'][i], 'd4': p['d4'][i]}
        return {'d1': p['def'][0], 'd2': p['def'][1], 'd3': p['def'][2], 'd4': p['def'][3]}
    return {'d1': p['d1'][idx], 'd2': p['d2'][idx], 'd3': p['d3'][idx], 'd4': p['d4'][idx]}


def fetch_klines(symbol, start_ms, interval='1h'):
    """scarica candele orarie da Binance, paginando (max 1000/req)."""
    out = []
    cur = start_ms
    while True:
        url = f"{BINANCE}?symbol={symbol}&interval={interval}&startTime={cur}&limit=1000"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = json.loads(r.read())
                break
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(2)
        if not data:
            break
        for k in data:
            out.append({'time': k[0] // 1000, 'open': float(k[1]), 'high': float(k[2]),
                        'low': float(k[3]), 'close': float(k[4]), 'volume': float(k[5])})
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.25)
    return out


def _day_key(ts_sec):
    return (ts_sec // 86400) * 86400


def compute_rolling_dmi(klines, period=14):
    """replica computeRollingDMI: DMI rolling intraday su candele orarie."""
    if not klines:
        return {}
    # bucket per giorno
    day_buckets = {}
    for i, k in enumerate(klines):
        dk = _day_key(k['time'])
        if dk not in day_buckets:
            day_buckets[dk] = [i, i]
        else:
            day_buckets[dk][1] = i
    days = sorted(day_buckets.keys())
    if len(days) < period + 2:
        return {}
    # candele giornaliere chiuse
    daily = []
    for dk in days:
        s, e = day_buckets[dk]
        o = klines[s]['open']; c = klines[e]['close']
        hi = max(klines[j]['high'] for j in range(s, e + 1))
        lo = min(klines[j]['low'] for j in range(s, e + 1))
        daily.append({'time': dk, 'open': o, 'high': hi, 'low': lo, 'close': c})
    n = len(daily)
    tr = [0.0] * n; pdm = [0.0] * n; mdm = [0.0] * n
    for i in range(1, n):
        h, l = daily[i]['high'], daily[i]['low']
        ph, pl, pc = daily[i-1]['high'], daily[i-1]['low'], daily[i-1]['close']
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up, dn = h - ph, pl - l
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
    # Wilder running sums fino a "ieri"
    state = [None] * n
    sTR = sPDM = sMDM = 0.0
    for i in range(1, min(period + 1, n)):
        sTR += tr[i]; sPDM += pdm[i]; sMDM += mdm[i]
    if n > period:
        state[period] = (sTR, sPDM, sMDM)
    for i in range(period + 1, n):
        sTR = sTR - sTR / period + tr[i]
        sPDM = sPDM - sPDM / period + pdm[i]
        sMDM = sMDM - sMDM / period + mdm[i]
        state[i] = (sTR, sPDM, sMDM)
    # DMI intraday per ogni ora
    decay = 1 - 1 / period
    dmi_by_time = {}
    for dIdx in range(period + 1, n):
        dk = days[dIdx]
        hStart, hEnd = day_buckets[dk]
        prev = state[dIdx - 1]
        if not prev:
            continue
        pHigh = daily[dIdx-1]['high']; pLow = daily[dIdx-1]['low']; pClose = daily[dIdx-1]['close']
        runHigh = klines[hStart]['high']; runLow = klines[hStart]['low']
        sTRd, sPDMd, sMDMd = prev[0]*decay, prev[1]*decay, prev[2]*decay
        for h in range(hStart, hEnd + 1):
            hi, lo = klines[h]['high'], klines[h]['low']
            if hi > runHigh: runHigh = hi
            if lo < runLow: runLow = lo
            trP = max(runHigh - runLow, abs(runHigh - pClose), abs(runLow - pClose))
            upP = runHigh - pHigh; dnP = pLow - runLow
            pdmP = upP if (upP > dnP and upP > 0) else 0.0
            mdmP = dnP if (dnP > upP and dnP > 0) else 0.0
            newSTR = sTRd + trP; newSPDM = sPDMd + pdmP; newSMDM = sMDMd + mdmP
            if newSTR <= 0:
                continue
            dmi_by_time[klines[h]['time']] = 100 * (newSPDM - newSMDM) / newSTR
    return dmi_by_time


def compute_signals_long_only(klines, asset, dmi_by_time):
    """replica sentinel mode SENZA ema/volume: solo DMI crossover su d1/d2."""
    signals = []
    pos = 'FLAT'; ep = 0.0
    # array DMI allineato alle candele
    dmi = [dmi_by_time.get(k['time']) for k in klines]
    for i in range(1, len(klines)):
        di, dip = dmi[i], dmi[i-1]
        if di is None or dip is None:
            continue
        d = datetime.datetime.utcfromtimestamp(klines[i]['time'])
        p = get_params(asset, d.year, d.month)
        cl = klines[i]['close']
        lE = (dip < p['d1'] and di >= p['d1']) or (dip < p['d2'] and di >= p['d2'])
        lX = (dip >= p['d1'] and di < p['d1']) or (dip >= p['d2'] and di < p['d2'])
        sE = (dip > p['d3'] and di <= p['d3']) or (dip > p['d4'] and di <= p['d4'])
        # long-only puro: entry su lE, exit su lX o segnale short
        if lE and pos != 'LONG':
            pos = 'LONG'; ep = cl
            signals.append({'i': i, 'type': 'ENTRY_LONG', 'price': cl})
        elif lX and pos == 'LONG':
            signals.append({'i': i, 'type': 'EXIT_LONG', 'price': cl})
            pos = 'FLAT'
        elif sE and pos == 'LONG':
            signals.append({'i': i, 'type': 'EXIT_LONG', 'price': cl})
            pos = 'FLAT'
    return signals


def compute_equity(klines, signals):
    """replica computeEquity: equity mark-to-market da 100."""
    n = len(klines)
    sig_map = {s['i']: s for s in signals}
    equity = 100.0; pos = 'FLAT'; ep = 0.0
    eq_series = []  # (time, equity_mark_to_market)
    for i in range(n):
        c = klines[i]
        sig = sig_map.get(i)
        if sig:
            if sig['type'] == 'ENTRY_LONG':
                pos = 'LONG'; ep = sig['price']
            elif ep > 0:
                ret = (sig['price'] / ep - 1)
                equity *= (1 + ret)
                pos = 'FLAT'; ep = 0.0
        mEq = equity
        if pos == 'LONG' and ep > 0:
            mEq = equity * (c['close'] / ep)
        eq_series.append((c['time'], mEq))
    return eq_series


def perf_from(eq_series, start_ts):
    """rendimento % dall'inizio finestra (ricostruito ripartendo dal valore a start_ts)."""
    if not eq_series:
        return 0.0
    # trova il valore base al primo punto >= start_ts
    base = None
    last = eq_series[-1][1]
    for t, v in eq_series:
        if t >= start_ts:
            base = v
            break
    if base is None or base == 0:
        return 0.0
    return (last / base - 1) * 100


def main():
    now = datetime.datetime.utcnow()
    # finestre: settimana (7g), mese (30g), YTD (1 gen anno corrente)
    week_ts = int((now - datetime.timedelta(days=7)).timestamp())
    month_ts = int((now - datetime.timedelta(days=30)).timestamp())
    ytd_ts = int(datetime.datetime(now.year, 1, 1).timestamp())
    # scarico da ~400 giorni fa (basta per DMI + finestre); start dipende da asset
    fetch_start = int((now - datetime.timedelta(days=420)).timestamp() * 1000)

    per_asset = {}
    eq_all = {}
    for asset, sym in SYMBOLS.items():
        print(f"[{asset}] scarico klines 1h...")
        kl = fetch_klines(sym, fetch_start)
        print(f"[{asset}] {len(kl)} candele orarie")
        if len(kl) < 400:
            print(f"[{asset}] dati insufficienti, skip")
            continue
        dmi = compute_rolling_dmi(kl, DMI_PERIOD)
        sigs = compute_signals_long_only(kl, asset, dmi)
        eq = compute_equity(kl, sigs)
        eq_all[asset] = eq
        per_asset[asset] = {
            'perf_week': round(perf_from(eq, week_ts), 2),
            'perf_month': round(perf_from(eq, month_ts), 2),
            'perf_ytd': round(perf_from(eq, ytd_ts), 2),
            'in_position': sigs[-1]['type'] == 'ENTRY_LONG' if sigs else False,
            'n_signals': len(sigs),
        }
        print(f"[{asset}] sett {per_asset[asset]['perf_week']}% mese {per_asset[asset]['perf_month']}% YTD {per_asset[asset]['perf_ytd']}%")

    # media equipesata delle perf (semplice media dei rendimenti %)
    def avg(key):
        vals = [per_asset[a][key] for a in per_asset]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    out = {
        'updated_at': now.isoformat(timespec='seconds') + 'Z',
        'mode': 'long_only_dmi_d1d2',
        'assets': per_asset,
        'portfolio': {
            'perf_week': avg('perf_week'),
            'perf_month': avg('perf_month'),
            'perf_ytd': avg('perf_ytd'),
            'n_assets': len(per_asset),
        },
    }
    os.makedirs('data', exist_ok=True)
    with open('data/crypto_data.json', 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n✓ portfolio: sett {out['portfolio']['perf_week']}% · mese {out['portfolio']['perf_month']}% · YTD {out['portfolio']['perf_ytd']}%")
    print("✓ data/crypto_data.json salvato")


if __name__ == '__main__':
    main()
