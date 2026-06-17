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


def load_prices():
    data = fetch_twelvedata() or fetch_stooq() or fetch_yfinance()
    if not data:
        raise SystemExit("Impossibile scaricare i dati S&P 500 da nessuna fonte "
                         "(Twelve Data / Stooq / yfinance).")
    data.sort(key=lambda x: x[0])  # cronologico
    # dedup per data (tieni l'ultimo)
    seen = {}
    for d, p in data:
        seen[d] = p
    out = sorted(seen.items())
    return out


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
    return res


def main():
    data = load_prices()
    dates = [d for d, _ in data]
    prices = [p for _, p in data]

    cycles = [analyze_cycle(prices, dates, spec) for spec in CYCLES]

    out = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "instrument": "S&P 500",
        "last_date": dates[-1],
        "last_close": round(prices[-1], 2),
        "n_days": len(prices),
        "cycles": cycles,
        "disclaimer": ("Analisi ciclica indicativa sui minimi storici (metodo dei cicli "
                       "annidati). Lettura probabilistica, non previsione."),
    }

    import os
    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[ok] scritto {OUT_PATH}")
    for c in cycles:
        if "progress_pct" in c:
            print(f"  {c['label']:18} {c['elapsed_days']:>3}gg / {c['len_theoretical']} "
                  f"({c['progress_pct']:.0f}%) {c['phase']}")


if __name__ == "__main__":
    main()
