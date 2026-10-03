"""Addendum 2ter — instantané des critères d'un signal (`signal_features`).

Règle absolue : aucun regard vers le futur. Chaque critère de marché n'utilise que
des bougies FERMÉES avant l'instant de décision (`t + durée <= decision_ts`).
Les critères d'information (catalyseur, unlock, transferts) viennent de la
recherche de la routine 1 et sont datés.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import indicators

DAY, HOUR = 86400, 3600
PARIS = ZoneInfo("Europe/Paris")
RELIABILITY = {"officiel": 1.0, "exchange": 1.0, "media_majeur": 0.7, "agregateur": 0.4, "social": 0.2}


def closed(candles, decision_ts, seconds):
    return [c for c in candles if c["t"] + seconds <= decision_ts]


def bb_width(closes, n=20):
    if len(closes) < n:
        return None
    w = closes[-n:]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return 4 * sd / m if m else None


def compute_features(decision_ts, daily, hourly=None, btc_daily=None, oi=None, funding_rate=None,
                     info=None, stop_struct_pct=None):
    """daily/hourly : bougies dict(t,o,h,l,c,vq) ; oi : [(t, oi_usd)] journalier ;
    info : dict(catalyst_type, catalyst_reliability, info_published_at_ts, n_sources,
    unlock_next_days, unlock_last_days, team_transfer, market_cap)."""
    d = closed(daily, decision_ts, DAY)
    h = closed(hourly or [], decision_ts, HOUR)
    b = closed(btc_daily or [], decision_ts, DAY)
    info = info or {}
    f = {}
    a7 = indicators.atr(d[-8:], 7) if len(d) >= 8 else None
    a30 = indicators.atr(d[-31:], 30) if len(d) >= 31 else None
    f["compression_atr7_30"] = (a7 / a30) if a7 and a30 else None
    f["bb_width_20"] = bb_width([c["c"] for c in d])
    hist = d[:-1][-14:]
    avg14 = sum(c["vq"] for c in hist) / len(hist) if hist else None
    f["vol_rel_14"] = (d[-1]["vq"] / avg14) if d and avg14 else None
    oi_c = [x for x in (oi or []) if x[0] + DAY <= decision_ts]
    f["oi_change_3d"] = (oi_c[-1][1] / oi_c[-4][1] - 1) if len(oi_c) >= 4 and oi_c[-4][1] else None
    f["funding_rate"] = funding_rate
    f["catalyst_type"] = info.get("catalyst_type")
    f["catalyst_reliability"] = info.get("catalyst_reliability")
    pub = info.get("info_published_at_ts")
    f["info_age_h"] = round((decision_ts - pub) / HOUR, 2) if pub and pub <= decision_ts else None
    f["n_sources"] = info.get("n_sources")
    f["unlock_next_days"] = info.get("unlock_next_days")
    f["unlock_last_days"] = info.get("unlock_last_days")
    f["team_transfer"] = info.get("team_transfer")
    f["market_cap"] = info.get("market_cap")
    f["liquidity_7d"] = (sum(c["vq"] for c in d[-7:]) / 7) if len(d) >= 7 else None
    dt = datetime.fromtimestamp(decision_ts, tz=timezone.utc).astimezone(PARIS)
    f["hour_paris"], f["weekday"] = dt.hour, dt.weekday()
    if len(b) >= 20:
        sma = sum(c["c"] for c in b[-20:]) / 20
        f["btc_trend_up"] = b[-1]["c"] > sma
    else:
        f["btc_trend_up"] = None
    if len(h) >= 25:
        f["gain_24h"] = h[-1]["c"] / h[-25]["c"] - 1
    elif len(d) >= 2:
        f["gain_24h"] = d[-1]["c"] / d[-2]["c"] - 1
    else:
        f["gain_24h"] = None
    f["gain_7d"] = (d[-1]["c"] / d[-8]["c"] - 1) if len(d) >= 8 else None
    f["stop_struct_pct"] = stop_struct_pct
    f["last_closed_daily_ts"] = d[-1]["t"] if d else None
    f["last_closed_hourly_ts"] = h[-1]["t"] if h else None
    return f


# Critères binaires testés (nom -> fonction des features). Une valeur manquante = None.
def _lt(k, x):
    return lambda f: None if f.get(k) is None else f[k] < x


def _ge(k, x):
    return lambda f: None if f.get(k) is None else f[k] >= x


CRITERIA = {
    "compression_forte": _lt("compression_atr7_30", 0.7),
    "bollinger_serre": _lt("bb_width_20", 0.25),
    "volume_x2": _ge("vol_rel_14", 2.0),
    "volume_x5": _ge("vol_rel_14", 5.0),
    "oi_hausse_20": _ge("oi_change_3d", 0.20),
    "funding_negatif": _lt("funding_rate", 0.0),
    "catalyseur_fiable": _ge("catalyst_reliability", 0.7),
    "info_fraiche_24h": _lt("info_age_h", 24),
    "sources_2plus": _ge("n_sources", 2),
    "pas_unlock_30j": _ge("unlock_next_days", 30),
    "pas_transfert_equipe": lambda f: None if f.get("team_transfer") is None else not f["team_transfer"],
    "btc_haussier": lambda f: f.get("btc_trend_up"),
    "pas_deja_monte_24h": _lt("gain_24h", 0.15),
    "pas_deja_monte_7j": _lt("gain_7d", 0.30),
    "stop_serre_8": _lt("stop_struct_pct", 0.08),
    "liquide_5M": _ge("liquidity_7d", 5e6),
    "heure_europe": lambda f: None if f.get("hour_paris") is None else 8 <= f["hour_paris"] < 18,
    # modes de détection (comparés entre eux par la routine 6)
    "mode_momentum": lambda f: None if f.get("detection_mode") is None else "momentum" in f["detection_mode"],
    "mode_avant_hausse": lambda f: None if f.get("detection_mode") is None else "pre_move" in f["detection_mode"],
    "mode_annonce": lambda f: None if f.get("detection_mode") is None else "announcement" in f["detection_mode"],
}


def eval_criteria(features):
    return {name: fn(features) for name, fn in CRITERIA.items()}


def cluster_events(rows, key_pair="pair", key_ts="ts", window_days=10):
    """Regroupe en événements indépendants : même pair à moins de 10 jours du premier
    signal de l'événement = même événement. Renvoie la liste des événements (le premier
    signal de chaque groupe, avec 'members')."""
    rows = sorted(rows, key=lambda r: (r[key_pair], r[key_ts]))
    events, cur = [], None
    for r in rows:
        if cur and cur[key_pair] == r[key_pair] and r[key_ts] - cur[key_ts] < window_days * DAY:
            cur["members"].append(r)
            continue
        cur = dict(r)
        cur["members"] = [r]
        events.append(cur)
    return sorted(events, key=lambda e: e[key_ts])
