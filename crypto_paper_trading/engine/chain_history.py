"""Rejeu historique pour la routine 7 : construit des occasions d'entrée (« événements ») datées
sur l'historique public (Gate, puis OKX), SANS regard vers le futur, et leurs résultats pour toute
la grille (stop, R) avec le moteur de rejeu existant.

Substitut documenté (docs/audit_3.md) : l'historique ne contient ni annonces ni open interest
journalier ancien ; les signaux historiques reprennent donc les deux modes de la routine 1 qui
se calculent sur les seuls prix et volumes :
- « avant la hausse » : volume >= 2x la moyenne 14 j, hausse 24 h < 10 %, hausse 7 j < 20 %,
  volatilité comprimée (ATR7/ATR30 <= 0,85) ;
- « momentum » : jour de signal >= +15 %, jamais acheté ; entrée le jour suivant si le volume reste
  >= 2x, sans nouvelle bougie >= +15 %, et à moins de 15 % sous la clôture du jour de signal.
Score = mêmes poids que la routine 1 (pre_move_accumulation 2, volume_doubling 1,5,
oversold_or_breakout 1, top_gainer_24h 0,5). TOUS les signaux sont gardés, y compris ceux qui
n'ont rien donné (pas seulement les cas de pump).
"""
from __future__ import annotations

import concurrent.futures as cf
import time

from . import chains, features, indicators, market

DAY = 86400
HOUR = 3600
W = dict(pre_move_accumulation=2.0, volume_doubling=1.5, oversold_or_breakout=1.0, top_gainer_24h=0.5)
REFERENCE = ("VELVETUSDT", "PUMPUSDT", "COTIUSDT")


def universe(n=80, min_vol=2e6):
    tick, _ = market.tickers()
    contracts = market.crypto_contracts()
    rows = [t for t in tick if t["pair"] in contracts and t["quote_vol_24h"] >= min_vol]
    rows.sort(key=lambda t: -t["quote_vol_24h"])
    pairs = [t["pair"] for t in rows[:n]]
    for r in REFERENCE:
        if r not in pairs:
            pairs.append(r)
    return pairs


def day_signals(pair, daily, start_ts, end_ts):
    """Décisions journalières (à la clôture du jour j) : renvoie [(decision_ts, types, mode)]."""
    out = []
    for i in range(31, len(daily)):
        d = daily[i]
        ts = d["t"] + DAY                                  # bougie fermée -> décision à sa clôture
        if ts < start_ts or ts > end_ts:
            continue
        hist = daily[i - 14:i]
        avg = sum(c["vq"] for c in hist) / len(hist) if hist else 0
        vr = d["vq"] / avg if avg else 0
        ch1 = d["c"] / daily[i - 1]["c"] - 1
        ch7 = d["c"] / daily[i - 7]["c"] - 1
        a7 = indicators.atr(daily[i - 7:i + 1], 7)
        a30 = indicators.atr(daily[i - 30:i + 1], 30)
        comp = (a7 / a30) if a7 and a30 else None
        hi20 = max(c["h"] for c in daily[i - 20:i])
        types = []
        if vr >= 2:
            types.append("volume_doubling")
        if d["c"] > hi20:
            types.append("oversold_or_breakout")
        if vr >= 2 and abs(ch1) < 0.10 and ch7 < 0.20 and comp is not None and comp <= 0.85:
            types.append("pre_move_accumulation")
            out.append((ts, types, "pre_move"))
            continue
        # momentum : le jour i est-il le lendemain d'un jour de signal (>= +15 %) ?
        prev = daily[i - 1]
        prev_ch = prev["c"] / daily[i - 2]["c"] - 1
        if prev_ch >= 0.15 and ch1 < 0.15 and vr >= 2 and d["c"] >= prev["c"] * 0.85:
            types.append("top_gainer_24h")
            out.append((ts, types, "momentum"))
    return out


def build_pair(pair, start_ts, end_ts, btc_daily, fee=0.00055, fund=0.0001, slip=0.001):
    try:
        daily, src = market.candles(pair, "1d", start_ts - 45 * DAY, end_ts)
        hourly, _ = market.candles(pair, "1h", start_ts - 2 * DAY, end_ts + 11 * DAY)
    except Exception as e:
        return [], f"{pair}: {str(e)[:80]}"
    evs = []
    for ts, types, mode in day_signals(pair, daily, start_ts, end_ts):
        rows = [r for r in hourly if r["t"] >= ts]
        if len(rows) < 24:
            continue
        entry = rows[0]["o"] * (1 + slip)
        f = features.compute_features(ts, daily, hourly, btc_daily)
        f["detection_mode"] = [mode]
        crit = {k: v for k, v in features.eval_criteria(f).items() if v is not None}
        outs = chains.event_outcomes(entry, rows, ts, 3600, fee, fund, slip)
        horizon = [r for r in rows if r["t"] < ts + 10 * DAY]
        mfe = max(r["h"] for r in horizon) / entry - 1 if horizon else None
        dvol = next((c["vq"] for c in reversed(daily) if c["t"] + DAY <= ts), None)
        score = sum(W.get(t, 0) for t in types)
        evs.append(dict(id=f"{pair}:{int(ts)}", ts=ts, pair=pair, mode=mode, types=types, base_score=score,
                        score=score, crit=crit, outcomes=outs, vol24h=dvol, mfe10=mfe,
                        regime=chains.btc_regime(btc_daily, ts), source="replay_history",
                        reference=pair in REFERENCE, data_source=src))
    return evs, None


def build(days=120, n_pairs=80, threads=8, end_ts=None):
    end_ts = end_ts or (time.time() // DAY) * DAY - 11 * DAY      # 10 j d'horizon complet
    start_ts = end_ts - days * DAY
    btc, _ = market.candles("BTCUSDT", "1d", start_ts - 60 * DAY, end_ts + 11 * DAY)
    pairs = universe(n_pairs)
    evs, errors = [], []
    with cf.ThreadPoolExecutor(threads) as ex:
        for res, err in ex.map(lambda p: build_pair(p, start_ts, end_ts, btc), pairs):
            evs.extend(res)
            if err:
                errors.append(err)
    evs.sort(key=lambda e: e["ts"])
    for c in features.cluster_events([dict(pair=e["pair"], ts=e["ts"], id=e["id"]) for e in evs]):
        for m in c["members"]:
            m_id = m["id"]
            for e in evs:
                if e["id"] == m_id:
                    e["cluster"] = c["id"]
    return dict(events=evs, errors=errors, pairs=pairs, start_ts=start_ts, end_ts=end_ts, built_at=time.time())


def target_calibration(events):
    """Hausse maximale médiane sur 10 jours depuis l'entrée, par mode, sur TOUS les signaux
    (y compris ceux qui n'ont rien donné) ; comparée aux cas de référence (pumps déjà connus)."""
    out = {}
    for key in sorted({e.get("mode", "inconnu") for e in events}) + ["tous"]:
        xs = sorted(e["mfe10"] for e in events if e.get("mfe10") is not None and (key == "tous" or e.get("mode", "inconnu") == key))
        if xs:
            out[key] = dict(n=len(xs), median=xs[len(xs) // 2], p25=xs[len(xs) // 4], p75=xs[3 * len(xs) // 4],
                            suggested_target=max(t for t in (0.15, 0.30, 0.45) if t <= max(0.15, xs[len(xs) // 2]))
                            if xs[len(xs) // 2] >= 0.15 else 0.15)
    ref = sorted(e["mfe10"] for e in events if e.get("reference") and e.get("mfe10") is not None)
    if ref:
        out["cas_de_pump"] = dict(n=len(ref), median=ref[len(ref) // 2])
    return out
