#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MyValue · MarkRoboT.S.  (v2 — tre sistemi, ricostruzione completa)
------------------------------------------------------------------
Indice dimostrativo equipesato che parte da 100 il venerdì 2026-05-01 e
compone ogni settimana la MEDIA dei rendimenti settimanali dei tre sistemi
del Megatrend Desk:

  - ETF     data/sector_data.json → portfolio_equity.dates / equity_system
  - Azioni  data/stocks_data.json → modes.aggressive.equity_curve[].system
  - Crypto  data/crypto_data.json → weekly[] (serie venerdì→venerdì
            generata da update_crypto.py, equipesata BTC/ETH/SOL)

Logica (v2): a ogni esecuzione la storia viene RICOSTRUITA da zero a
partire dal seed. Niente stato incrementale: idempotente per costruzione,
e se un feed sorgente viene corretto MyValue si riallinea da solo.

Il calendario settimanale è quello dei venerdì del sistema ETF (il più
lungo). Se per un venerdì manca il dato di un sistema, la media usa i
sistemi disponibili e la cosa resta tracciata in "parts".
"""

import json, os, sys, urllib.request
from datetime import datetime

REPO = "https://raw.githubusercontent.com/Mark-Robots/megatrend-desk/main"
STOCKS_URL = f"{REPO}/data/stocks_data.json"
SECTOR_URL = f"{REPO}/data/sector_data.json"
CRYPTO_URL = f"{REPO}/data/crypto_data.json"
OUT_PATH   = os.path.join("data", "myvalue.json")

BASE_VALUE = 100.0
SEED_DATE  = "2026-05-01"   # venerdì di partenza (MyValue = 100)


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "myvalue/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _local_or_remote(local_name, url):
    """Preferisce il file locale (se lo script gira nel repo), altrimenti scarica."""
    p = os.path.join("data", local_name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return _get_json(url)


def series_etf(d):
    """dict {venerdì -> equity} del sistema ETF."""
    pe = d.get("portfolio_equity", {})
    dates = pe.get("dates", [])
    es = pe.get("equity_system", [])
    return {dt: v for dt, v in zip(dates, es) if v}


def series_azioni(d):
    """dict {venerdì -> equity} del sistema Azioni."""
    eq = d["modes"]["aggressive"]["equity_curve"]
    return {row["date"]: row["system"] for row in eq if row.get("system")}


def weekly_crypto(d):
    """dict {venerdì -> rendimento settimanale %} del sistema Crypto."""
    return {row["date"]: row["pct"] for row in d.get("weekly", [])}


def main():
    stocks = _local_or_remote("stocks_data.json", STOCKS_URL)
    sector = _local_or_remote("sector_data.json", SECTOR_URL)
    crypto = _local_or_remote("crypto_data.json", CRYPTO_URL)

    etf_eq = series_etf(sector)
    az_eq  = series_azioni(stocks)
    cr_wk  = weekly_crypto(crypto)

    if SEED_DATE not in etf_eq or SEED_DATE not in az_eq:
        print(f"[errore] seed {SEED_DATE} assente dalle equity ETF/Azioni, esco")
        sys.exit(1)
    if not cr_wk:
        print("[avviso] serie settimanale crypto assente: MyValue userà solo ETF+Azioni "
              "finché update_crypto.py non pubblica 'weekly' in crypto_data.json")

    # calendario: i venerdì ETF dal seed in poi
    fridays = sorted(dt for dt in etf_eq if dt >= SEED_DATE)

    history = [{
        "date": SEED_DATE,
        "value": BASE_VALUE,
        "weekly_pct": 0.0,
        "parts": {},
        "seed": True
    }]
    value = BASE_VALUE

    for prev, cur in zip(fridays, fridays[1:]):
        parts, rets = {}, []
        if etf_eq.get(prev) and etf_eq.get(cur):
            r = (etf_eq[cur] / etf_eq[prev] - 1) * 100.0
            parts["etf"] = round(r, 4); rets.append(r)
        if az_eq.get(prev) and az_eq.get(cur):
            r = (az_eq[cur] / az_eq[prev] - 1) * 100.0
            parts["azioni"] = round(r, 4); rets.append(r)
        if cur in cr_wk:
            parts["crypto"] = round(cr_wk[cur], 4); rets.append(cr_wk[cur])
        if not rets:
            print(f"[salto] {cur}: nessun rendimento disponibile")
            continue
        weekly = sum(rets) / len(rets)
        value *= (1 + weekly / 100.0)
        history.append({
            "date": cur,
            "value": round(value, 4),
            "weekly_pct": round(weekly, 4),
            "parts": parts
        })
        print(f"[ok] {cur}: media {weekly:+.2f}% su {len(rets)} sistemi → MyValue {value:.2f}")

    out = {
        "name": "MyValue",
        "base": BASE_VALUE,
        "seed_date": SEED_DATE,
        "systems": ["ETF", "Azioni", "Crypto"],
        "note": ("Indice dimostrativo equipesato: media dei rendimenti settimanali dei tre "
                 "sistemi Megatrend (ETF, Azioni, Crypto DMI), composta da 100 dal "
                 f"{SEED_DATE}. Ricostruito integralmente a ogni aggiornamento."),
        "history": history,
        "updated_at": datetime.now().astimezone().isoformat(),
        "last_value": history[-1]["value"],
        "last_date": history[-1]["date"],
    }

    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[salvato] {OUT_PATH} — {len(history)} punti, valore attuale {history[-1]['value']}")


if __name__ == "__main__":
    main()
