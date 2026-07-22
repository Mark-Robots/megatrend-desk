#!/usr/bin/env python3
"""
update_fondi.py — feed NAV per fondi.html (Megatrend Desk)
Recupera i NAV dei comparti SICAV via Yahoo Finance (yfinance risolve
gli ISIN LU quando il fondo è censito) e scrive data/fondi_nav.json.
Stesso pattern del feed NAV di Prospect. Pensato per GitHub Actions (daily).
"""

import json
import datetime as dt
from pathlib import Path

import yfinance as yf

# ISIN dei comparti (stessa lista di FUND_MAP + riserva in fondi.html)
ISINS = [
    "LU0115773425",  # Fidelity FF Global Technology E-Acc-EUR
    "LU2298322558",  # BGF World Healthscience E2 EUR Hedged
    "LU0114722738",  # Fidelity FF Global Financial Services E-Acc-EUR
    "LU0331289248",  # BGF World Energy C2 EUR
    "LU0208853944",  # JPM Global Natural Resources D (acc) EUR
    "LU0115139569",  # Invesco Global Consumer Trends E Acc EUR
    "LU0366534773",  # Pictet Nutrition R EUR
    "LU0340555134",  # Pictet Digital R EUR
    "LU0503631987",  # Pictet Global Environmental Opportunities R EUR
    "LU0512092577",  # MS INVF Global Infrastructure BH EUR
    "LU0705259769",  # Nordea 1 Global Real Estate BP EUR
]

# Se Yahoo non risolve un ISIN, mappare qui il simbolo a mano
# (es. "LU0331289248": "0P0000WI3O.F") e rilanciare.
SYMBOL_OVERRIDES: dict[str, str] = {}

OUT = Path(__file__).parent / "data" / "fondi_nav.json"


def fetch_one(isin: str) -> dict | None:
    symbol = SYMBOL_OVERRIDES.get(isin, isin)
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="1y", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        closes = hist["Close"].dropna()
        if closes.empty:
            return None
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        last_date = closes.index[-1].date()

        # YTD: primo NAV dell'anno corrente disponibile in serie
        year_mask = closes.index.year == last_date.year
        ytd_base = float(closes[year_mask].iloc[0]) if year_mask.any() else None

        info_cur = None
        try:
            info_cur = (t.fast_info or {}).get("currency")
        except Exception:
            pass

        return {
            "nav": round(last, 4),
            "date": last_date.isoformat(),
            "chg_1d": round((last / prev - 1) * 100, 2) if prev else None,
            "chg_ytd": round((last / ytd_base - 1) * 100, 2) if ytd_base else None,
            "currency": info_cur or "EUR",
            "source": f"yahoo:{symbol}",
        }
    except Exception as e:
        print(f"  [warn] {isin}: {e}")
        return None


def main() -> None:
    quotes: dict[str, dict] = {}
    missing: list[str] = []

    for isin in ISINS:
        print(f"fetch {isin} ...")
        q = fetch_one(isin)
        if q:
            quotes[isin] = q
            print(f"  ok: {q['nav']} {q['currency']} @ {q['date']}")
        else:
            missing.append(isin)
            print("  MISSING (aggiungere override simbolo)")

    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "quotes": quotes,
        "missing": missing,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)

    # onestà sopra feed vuoti: se il fetch fallisce in blocco (es. Yahoo giù),
    # non sovrascrivere un file buono con uno vuoto
    if not quotes and OUT.exists():
        print("Nessuna quota recuperata: mantengo il file precedente.")
        return

    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"scritto {OUT} — {len(quotes)} ok, {len(missing)} mancanti")


if __name__ == "__main__":
    main()
