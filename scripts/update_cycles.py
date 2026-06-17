#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_cycles.py — Analisi ciclica S&P 500 (metodo Sartorelli, cicli annidati)
Scarica la storia giornaliera dell'S&P 500, individua i minimi ciclici a tre scale
(annuale ~250gg, intermedio ~80gg, mensile ~22gg) e scrive data/cycles_data.json.

Pensato per girare su GitHub Actions (dove Stooq/yfinance sono raggiungibili).
Nessuna dipendenza obbligatoria oltre la stdlib; usa yfinance solo come fallback.
"""
import json, csv, io, sys, urllib.request, datetime, statistics

import os

OUT_PATH = "data/cycles_data.json"

# Durate teoriche dei cicli (giorni di borsa) — scuola ciclica classica
CYCLES = [
    {"key": "annuale",    "label": "Ciclo annuale",    "len": 250},
    {"key": "intermedio", "label": "Ciclo intermedio", "len": 80},
    {"key": "mensile",    "label": "Ciclo mensile",    "len": 22},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (cycles-bot)"}


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_twelvedata():
    """Fonte primaria se è impostato TWELVEDATA_API_KEY (secret del repo).
    Twelve Data è affidabile dai runner GitHub. Simbolo indice S&P 500: SPX."""
    key = os.environ.get("TWELVEDATA_API_KEY")
    if not key:
        return None
    for sym in ("SPX", "GSPC", "US500"):
        try:
            url = (f"https://api.twelvedata.com/time_series?symbol={sym}"
                   f"&interval=1day&outputsize=2000&order=ASC&apikey={key}")
            obj = json.loads(_http_get(url))
            vals = obj.get("values")
            if not vals:
                print(f"[twelvedata] {sym}: {obj.get('message','nessun dato')}")
                continue
            data = [(v["datetime"][:10], float(v["close"])) for v in vals
                    if v.get("close")]
            if len(data) > 300:
                print(f"[twelvedata] {len(data)} candele da {sym}")
                return data
        except Exception as e:
            print(f"[twelvedata] {sym} fallito: {e}")
    return None


def fetch_stooq():
    """Storia giornaliera S&P 500 da Stooq (CSV diretto, storico lungo).
    Provo più host perché stooq.com può essere bloccato da alcuni runner."""
    hosts = ["stooq.com", "stooq.pl"]
    syms = ["%5Espx", "^spx"]
    for host in hosts:
        for sym in syms:
            try:
                txt = _http_get(f"https://{host}/q/d/l/?s={sym}&i=d")
                if not txt or txt.strip().lower().startswith("<!doctype"):
                    continue
                rows = list(csv.DictReader(io.StringIO(txt)))
                data = [(r["Date"], float(r["Close"])) for r in rows
                        if r.get("Close") not in (None, "", "N/D")]
                if len(data) > 300:
                    print(f"[stooq] {len(data)} candele da {host}/{sym}")
                    return data
            except Exception as e:
                print(f"[stooq] {host}/{sym} fallito: {e}")
    return None


def _norm_date(x):
    """Converte l'indice yfinance (Timestamp, datetime o str) in 'YYYY-MM-DD'."""
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    return str(x)[:10]


def fetch_yfinance():
    """Fallback: yfinance ^GSPC. Gestisce indice come Timestamp o stringa."""
    try:
        import yfinance as yf
        df = yf.download("^GSPC", period="5y", interval="1d",
                         progress=False, auto_adjust=True)
        if df is not None and len(df) > 300:
            close = df["Close"]
            # con multi-index colonne (yfinance recente) prendi la prima colonna
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            close = close.dropna()
            data = [(_norm_date(idx), float(val)) for idx, val in close.items()]
            if len(data) > 300:
                print(f"[yfinance] {len(data)} candele")
                return data
    except Exception as e:
        print(f"[yfinance] fallito: {e}")
    return None


def fetch_stooq_csv_github():
    """Ulteriore fallback: file CSV statico storico ^SPX via raw GitHub mirror.
    (placeholder: usa yfinance/stooq; qui solo per estendibilità futura)"""
    return None


def fetch_btc_daily():
    """Storia giornaliera BTC/USDT da Binance (klines 1d). Multi-host perché
    alcuni endpoint Binance sono bloccati dai runner GitHub USA (errore 451)."""
    hosts = ["data-api.binance.vision", "api.binance.com", "api1.binance.com"]
    for host in hosts:
        try:
            all_rows, end = [], None
            # Binance dà max 1000 candele per richiesta: pagino all'indietro
            for _ in range(4):
                url = (f"https://{host}/api/v3/klines?symbol=BTCUSDT"
                       f"&interval=1d&limit=1000")
                if end:
                    url += f"&endTime={end}"
                arr = json.loads(_http_get(url))
                if not arr:
                    break
                all_rows = arr + all_rows
                end = arr[0][0] - 1  # openTime della prima candela meno 1ms
                if len(arr) < 1000:
                    break
            if len(all_rows) > 300:
                data = []
                seen = set()
                for k in all_rows:
                    d = datetime.datetime.utcfromtimestamp(k[0] / 1000).strftime("%Y-%m-%d")
                    if d in seen:
                        continue
                    seen.add(d)
                    data.append((d, float(k[4])))  # close
                print(f"[binance] {len(data)} candele daily da {host}")
                return data
        except Exception as e:
            print(f"[binance] {host} fallito: {e}")
    return None


def fetch_btc_kraken():
    """Fallback BTC: Kraken OHLC daily (XBTUSD)."""
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440"
        obj = json.loads(_http_get(url))
        res = obj.get("result", {})
        key = next((k for k in res if k != "last"), None)
        if key:
            rows = res[key]
            data = [(datetime.datetime.utcfromtimestamp(r[0]).strftime("%Y-%m-%d"),
                     float(r[4])) for r in rows]
            if len(data) > 300:
                print(f"[kraken] {len(data)} candele daily")
                return data
    except Exception as e:
        print(f"[kraken] fallito: {e}")
    return None


def load_prices(instrument="sp500"):
    if instrument == "btc":
        data = fetch_btc_daily() or fetch_btc_kraken()
        src = "Binance / Kraken"
    else:
        data = fetch_twelvedata() or fetch_stooq() or fetch_yfinance()
        src = "Twelve Data / Stooq / yfinance"
    if not data:
        raise SystemExit(f"Impossibile scaricare i dati ({instrument}) da nessuna fonte ({src}).")
    data.sort(key=lambda x: x[0])  # cronologico
    seen = {}
    for d, p in data:
        seen[d] = p
    return sorted(seen.items())


def find_cycle_lows(prices, cycle_len):
    """Minimi ciclici: punto minimo in una finestra ~0.4*durata, con distanza minima
    tra minimi pari a ~0.5*durata (evita doppioni)."""
    half = max(3, int(cycle_len * 0.4))
    min_gap = cycle_len * 0.5
    lows = []
    for i in range(len(prices)):
        a = max(0, i - half)
        b = min(len(prices), i + half + 1)
        window = prices[a:b]
        if prices[i] == min(window):
            if not lows or (i - lows[-1]) >= min_gap:
                lows.append(i)
    return lows


def find_cycle_highs(prices, cycle_len):
    """Massimi ciclici (ciclo inverso): punto massimo in una finestra ~0.4*durata."""
    half = max(3, int(cycle_len * 0.4))
    min_gap = cycle_len * 0.5
    highs = []
    for i in range(len(prices)):
        a = max(0, i - half)
        b = min(len(prices), i + half + 1)
        window = prices[a:b]
        if prices[i] == max(window):
            if not highs or (i - highs[-1]) >= min_gap:
                highs.append(i)
    return highs


def analyze_cycle(prices, dates, spec):
    cl = spec["len"]
    lows = find_cycle_lows(prices, cl)
    res = {
        "key": spec["key"], "label": spec["label"], "len_theoretical": cl,
        "n_lows": len(lows), "lows_idx": lows[-8:],  # ultimi minimi (indici)
        "lows_dates": [dates[i] for i in lows[-8:]],
    }
    if len(lows) >= 2:
        gaps = [lows[i+1]-lows[i] for i in range(len(lows)-1)]
        res["gap_avg"] = round(statistics.mean(gaps), 1)
        res["gap_min"] = min(gaps)
        res["gap_max"] = max(gaps)
        last = lows[-1]
        elapsed = (len(prices)-1) - last
        res["elapsed_days"] = elapsed
        res["last_low_date"] = dates[last]
        # progresso nel ciclo corrente rispetto alla durata teorica
        prog = elapsed / cl
        res["progress_pct"] = round(min(prog, 1.5) * 100, 0)
        # fase: prima meta' = ascendente (post-minimo), seconda = discendente (verso minimo)
        if prog < 0.5:
            res["phase"] = "ascendente"
            res["phase_note"] = "forze rialziste dopo il minimo"
        elif prog < 0.9:
            res["phase"] = "discendente"
            res["phase_note"] = "verso il prossimo minimo, forze in indebolimento"
        else:
            res["phase"] = "minimo atteso"
            res["phase_note"] = "ciclo maturo, minimo ciclico in prossimita'"
        # giorni stimati al prossimo minimo (durata teorica - trascorsi)
        res["days_to_low_est"] = max(0, cl - elapsed)
        # data stimata del prossimo minimo (ultimo minimo + durata, proiettata al futuro)
        try:
            _d = datetime.date.fromisoformat(dates[last])
            _last_d = datetime.date.fromisoformat(dates[-1])
            _nx = _d + datetime.timedelta(days=cl)
            while _nx <= _last_d:
                _nx += datetime.timedelta(days=cl)
            res["next_low_date_est"] = _nx.strftime("%Y-%m-%d")
            res["days_to_low_est"] = (_nx - _last_d).days
        except Exception:
            pass

    # --- ciclo inverso (massimi / top) ---
    highs = find_cycle_highs(prices, cl)
    res["n_highs"] = len(highs)
    res["highs_dates"] = [dates[i] for i in highs[-8:]]
    if len(highs) >= 2:
        hgaps = [highs[i+1]-highs[i] for i in range(len(highs)-1)]
        res["high_gap_avg"] = round(statistics.mean(hgaps), 1)
        last_h = highs[-1]
        elapsed_h = (len(prices)-1) - last_h
        res["elapsed_from_high"] = elapsed_h
        res["last_high_date"] = dates[last_h]
        prog_h = elapsed_h / cl
        res["progress_high_pct"] = round(min(prog_h, 1.5) * 100, 0)
        res["days_to_high_est"] = max(0, cl - elapsed_h)
        # data stimata del prossimo massimo (ultimo massimo + durata, proiettata al futuro)
        try:
            _dh = datetime.date.fromisoformat(dates[last_h])
            _last_date = datetime.date.fromisoformat(dates[-1])
            _nxh = _dh + datetime.timedelta(days=cl)
            while _nxh <= _last_date:
                _nxh += datetime.timedelta(days=cl)
            res["next_high_date_est"] = _nxh.strftime("%Y-%m-%d")
            res["days_to_high_est"] = (_nxh - _last_date).days
        except Exception:
            pass
        # fase inversa: prima meta' dopo il top = discesa, seconda = risalita verso nuovo top
        if prog_h < 0.5:
            res["inv_phase"] = "post-top"
            res["inv_note"] = "dopo un massimo ciclico, possibile correzione"
        elif prog_h < 0.9:
            res["inv_phase"] = "verso-top"
            res["inv_note"] = "in avvicinamento al prossimo massimo"
        else:
            res["inv_phase"] = "top atteso"
            res["inv_note"] = "massimo ciclico in prossimita'"
    return res


INSTRUMENTS = [
    {"id": "sp500", "label": "S&P 500", "out": "data/cycles_data.json",     "round": 2},
    {"id": "btc",   "label": "Bitcoin", "out": "data/cycles_btc_data.json", "round": 0},
]


def build_one(inst):
    data = load_prices(inst["id"])
    dates = [d for d, _ in data]
    prices = [p for _, p in data]
    cycles = [analyze_cycle(prices, dates, spec) for spec in CYCLES]
    out = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "instrument": inst["label"],
        "last_date": dates[-1],
        "last_close": round(prices[-1], inst["round"]),
        "n_days": len(prices),
        "cycles": cycles,
        "disclaimer": ("Analisi ciclica indicativa sui minimi storici (metodo dei cicli "
                       "annidati). Lettura probabilistica, non previsione."),
    }
    os.makedirs("data", exist_ok=True)
    with open(inst["out"], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[ok] {inst['label']} -> {inst['out']}")
    for c in cycles:
        if "progress_pct" in c:
            print(f"  {c['label']:18} {c['elapsed_days']:>3}gg / {c['len_theoretical']} "
                  f"({c['progress_pct']:.0f}%) {c['phase']}")


def main():
    errors = []
    for inst in INSTRUMENTS:
        try:
            build_one(inst)
        except SystemExit as e:
            print(f"[skip] {inst['label']}: {e}")
            errors.append(inst["label"])
    if len(errors) == len(INSTRUMENTS):
        raise SystemExit("Nessuno strumento aggiornato.")


if __name__ == "__main__":
    main()
