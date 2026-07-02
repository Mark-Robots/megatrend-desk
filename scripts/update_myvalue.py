#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MyValue · MarkRoboT.S.
----------------------
Indice unico che parte da 100 e cresce/cala ogni settimana come MEDIA dei
rendimenti settimanali dei sistemi Megatrend. Per ora combina due sistemi
(ETF + Azioni); il DMI crypto verrà aggiunto in seguito.

Logica:
  - Ogni settimana leggo l'ultimo rendimento settimanale di ciascun sistema
    dalla sua equity curve ufficiale (gli stessi numeri mostrati sul desk).
  - Rendimento MyValue della settimana = media dei rendimenti disponibili.
  - Valore composto: value_new = value_old * (1 + media/100).
  - Salvo la storia in data/myvalue.json. Se un certo venerdì è già presente,
    non lo duplico (idempotente: si può lanciare più volte senza danni).

Fonti (raw GitHub, stessi file del desk):
  - Azioni: data/stocks_data.json  → modes.aggressive.equity_curve[].system
  - ETF:    data/sector_data.json  → portfolio_equity.dates / equity_system
"""

import json, os, sys, urllib.request
from datetime import datetime

REPO = "https://raw.githubusercontent.com/Mark-Robots/megatrend-desk/main"
STOCKS_URL = f"{REPO}/data/stocks_data.json"
SECTOR_URL = f"{REPO}/data/sector_data.json"
OUT_PATH   = os.path.join("data", "myvalue.json")

BASE_VALUE = 100.0   # il valore di partenza


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "myvalue/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _local_or_remote(local_name, url):
    """Preferisce il file locale (se lo script gira nel repo), altrimenti scarica."""
    p = os.path.join("data", local_name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return _get_json(url)


def weekly_return_stocks(d):
    """Ultimo rendimento settimanale del sistema Azioni + data del venerdì."""
    eq = d["modes"]["aggressive"]["equity_curve"]
    if len(eq) < 2:
        return None, None
    last, prev = eq[-1], eq[-2]
    if not prev.get("system"):
        return None, None
    r = (last["system"] / prev["system"] - 1) * 100.0
    return r, last["date"]


def weekly_return_etf(d):
    """Ultimo rendimento settimanale del sistema ETF + data del venerdì."""
    pe = d.get("portfolio_equity", {})
    es = pe.get("equity_system", [])
    dates = pe.get("dates", [])
    if len(es) < 2 or len(dates) < 2:
        return None, None
    r = (es[-1] / es[-2] - 1) * 100.0
    return r, dates[-1]


def load_history():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "name": "MyValue",
        "base": BASE_VALUE,
        "systems": ["ETF", "Azioni"],
        "note": "Indice equipesato: media dei rendimenti settimanali dei sistemi Megatrend. Parte da 100.",
        "history": []   # [{date, value, weekly_pct, parts:{etf, azioni}}]
    }


def main():
    stocks = _local_or_remote("stocks_data.json", STOCKS_URL)
    sector = _local_or_remote("sector_data.json", SECTOR_URL)

    r_az, d_az = weekly_return_stocks(stocks)
    r_etf, d_etf = weekly_return_etf(sector)

    parts = {}
    rets = []
    if r_az is not None:
        parts["azioni"] = round(r_az, 4)
        rets.append(r_az)
    if r_etf is not None:
        parts["etf"] = round(r_etf, 4)
        rets.append(r_etf)

    if not rets:
        print("[errore] nessun rendimento disponibile dai sistemi, esco")
        sys.exit(1)

    weekly = sum(rets) / len(rets)   # media equipesata

    # la data di riferimento è il venerdì più recente tra i due
    ref_date = max([d for d in [d_az, d_etf] if d])

    hist = load_history()
    H = hist["history"]

    # idempotenza: se l'ultima settimana registrata è già ref_date, aggiorno; non duplico
    if H and H[-1]["date"] == ref_date:
        print(f"[info] settimana {ref_date} già presente: nessun nuovo punto aggiunto")
        # aggiorno comunque i valori nel caso i dati fonte siano cambiati
        prev_value = H[-2]["value"] if len(H) > 1 else BASE_VALUE
        H[-1]["value"] = round(prev_value * (1 + weekly / 100.0), 4)
        H[-1]["weekly_pct"] = round(weekly, 4)
        H[-1]["parts"] = parts
    else:
        prev_value = H[-1]["value"] if H else BASE_VALUE
        # il primo punto in assoluto è il seme = 100 (nessuna variazione applicata)
        if not H:
            H.append({
                "date": ref_date,
                "value": BASE_VALUE,
                "weekly_pct": 0.0,
                "parts": parts,
                "seed": True
            })
            print(f"[seed] MyValue inizializzato a {BASE_VALUE} il {ref_date}")
        else:
            new_value = prev_value * (1 + weekly / 100.0)
            H.append({
                "date": ref_date,
                "value": round(new_value, 4),
                "weekly_pct": round(weekly, 4),
                "parts": parts
            })
            print(f"[ok] {ref_date}: media {weekly:+.2f}%  →  MyValue {new_value:.2f}")

    hist["updated_at"] = datetime.now().astimezone().isoformat()
    hist["last_value"] = H[-1]["value"]
    hist["last_date"] = H[-1]["date"]

    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    print(f"[salvato] {OUT_PATH} — {len(H)} settimane, valore attuale {H[-1]['value']}")


if __name__ == "__main__":
    main()
