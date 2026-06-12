"""
PREVIEW SIGNALS — sistema AZIONI Megatrend.

Gira nel workflow (GitHub Actions), una volta al giorno dopo la chiusura USA.
Riusa ESATTAMENTE la logica di update_stocks.py (select_best_at_week, compute_roc,
composite_score, assign_tag) per calcolare, alle quotazioni correnti, quali settori
sarebbero IN/OUT, confronta con le posizioni APERTE dell'ultimo run ufficiale
(data/stocks_data.json) e scrive data/preview_signals.json per la dashboard.

NB: e' un'ANTEPRIMA. Il segnale ufficiale si forma solo alla chiusura di venerdi'.
"""
import json, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_stocks as us

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS_JSON = os.path.join(ROOT, 'data', 'stocks_data.json')
OUT_JSON = os.path.join(ROOT, 'data', 'preview_signals.json')

NAMES = getattr(us, 'SECTOR_NAMES', {})


def uni_for(sec):
    return us.US_UNIVERSE if sec in us.US_SECTORS_ETF else us.IT_UNIVERSE


def sector_is_in(sec, prices):
    """
    Stato OPERATIVO REALE del settore, identico al backtest delle 16:00.
    Replica la pipeline NO_BAD: RRG (rsRatio/rsMom) dell'ETF di settore vs benchmark
    -> state (quadrante) + stage (1-4 vs MA30) -> is_operational_in_base().
    Ritorna (in_now: bool, state: str|None, stage: str|None).

    NB: questo e' cio' che mancava al preview. Prima diceva 'in' se esisteva un buon
    TITOLO nel settore; ma l'ingresso reale dipende dallo STATO DEL SETTORE, non dai titoli.
    """
    if sec not in prices.columns:
        return False, None, None
    region = 'US' if sec in us.US_SECTORS_ETF else 'IT'
    bench_tk = us.US_BENCHMARK if region == 'US' else us.EU_BENCHMARK
    if bench_tk not in prices.columns:
        return False, None, None
    sec_prices = prices[sec].dropna()
    bench_prices = prices[bench_tk].dropna()
    rrg = us.calculate_rrg(sec_prices, bench_prices, window=14)
    if rrg is None or len(rrg) == 0:
        return False, None, None
    history = us.extract_signal_history_full(rrg, sec_prices, ma_weeks=30)
    if not history:
        return False, None, None
    # l'ultimo periodo della storia = stato corrente del settore
    last = history[-1]
    in_now = (last.get('signal') == 'IN')
    return bool(in_now), last.get('end_state'), last.get('end_stage')


def best_candidate(sec, prices, w, mode):
    """Miglior titolo del settore ORA; se il settore e' OUT, il 'capolista' comunque."""
    best = us.select_best_at_week(sec, prices, w, uni_for(sec), mode)
    if best:
        return best, True
    # settore OUT: calcolo comunque il capolista per mostrare i numeri
    scored = []
    for tk in uni_for(sec).get(sec, []):
        if tk not in prices.columns:
            continue
        s = prices[tk].iloc[:w + 1].dropna()
        if len(s) < 14:
            continue
        roc4 = us.compute_roc(s, 4)
        roc13 = us.compute_roc(s, 13)
        roc52 = us.compute_roc(s, 52)
        scored.append({'ticker': tk, 'roc4': roc4, 'roc13': roc13, 'roc52': roc52,
                       'tag': us.assign_tag(roc13, roc52),
                       'score': us.composite_score(roc4, roc13, roc52, mode)})
    if not scored:
        return None, False
    key = 'roc4' if mode == 'aggressive' else 'score'
    ref = max(scored, key=lambda x: (x[key] if x[key] is not None else -1e9))
    return ref, False


def main():
    print("[PREVIEW] Scarico prezzi correnti...")
    prices = us.fetch_all_prices()
    w = len(prices) - 1
    last_bar = str(prices.index[-1].date())

    # posizioni aperte dall'ultimo run ufficiale (settori + titolo detenuto)
    open_secs = {'balanced': set(), 'aggressive': set()}
    held = {'balanced': {}, 'aggressive': {}}
    try:
        with open(STOCKS_JSON, encoding='utf-8') as f:
            d = json.load(f)
        for m in open_secs:
            for p in d['modes'][m]['current_positions']:
                open_secs[m].add(p['sector_etf'])
                held[m][p['sector_etf']] = p['ticker']
    except Exception as e:
        print(f"[PREVIEW] WARN: non leggo {STOCKS_JSON}: {e}")

    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_bar': last_bar,
        'note': "Anteprima alle quotazioni correnti: il segnale ufficiale si forma alla chiusura di venerdi'.",
        'modes': {},
    }

    for mode in ('balanced', 'aggressive'):
        sectors = []
        ingressi, uscite = [], []
        for sec in us.SECTORS_SYSTEM:
            # STATO REALE DEL SETTORE (regola NO_BAD, identica alle 16:00)
            in_now, state, stage = sector_is_in(sec, prices)
            # candidato = miglior titolo del settore ORA (solo informativo: se entrasse, compreresti questo)
            ref, _cand_in = best_candidate(sec, prices, w, mode)
            was_in = sec in open_secs[mode]
            move = None
            if in_now and not was_in:
                move = 'ingresso'
                ingressi.append(sec)
            elif was_in and not in_now:
                move = 'uscita'
                uscite.append(sec)
            r = ref or {}
            roc4 = r.get('roc4')
            # borderline: settore IN ma vicino all'uscita (stage 3 = sopra MA ma in rallentamento)
            borderline = bool(in_now and was_in and stage == '3')
            held_tk = held[mode].get(sec)
            names = getattr(us, 'STOCK_NAMES', {})
            sectors.append({
                'sector': sec,
                'name': NAMES.get(sec, sec),
                'in_now': bool(in_now),
                'was_in': bool(was_in),
                'move': move,
                'borderline': borderline,
                'state': state,
                'stage': stage,
                'ticker': r.get('ticker'),
                'ticker_name': getattr(us, 'STOCK_NAMES', {}).get(r.get('ticker'), r.get('ticker')),
                'held_ticker': held_tk,
                'held_name': names.get(held_tk, held_tk) if held_tk else None,
                'roc4': round(float(roc4), 2) if roc4 is not None else None,
                'roc13': round(float(r['roc13']), 2) if r.get('roc13') is not None else None,
                'score': round(float(r['score']), 1) if r.get('score') is not None else None,
                'tag': r.get('tag'),
            })
        out['modes'][mode] = {
            'open_sectors': sorted(open_secs[mode]),
            'sectors': sectors,
            'ingressi': ingressi,
            'uscite': uscite,
        }
        print(f"[PREVIEW·{mode.upper()}] ingressi={ingressi} uscite={uscite}")

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1,
                  default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print(f"[PREVIEW] Scritto {OUT_JSON}")


if __name__ == '__main__':
    main()
