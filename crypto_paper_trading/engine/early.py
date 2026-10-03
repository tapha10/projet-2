"""Détection précoce : trouver les candidats AVANT la hausse de prix, et par annonce.

Trois modes de détection coexistent et sont comparés (tag `mode_*` dans signal_types) :
  - mode_momentum     : plus fortes hausses 24 h (logique d'origine, inchangée) ;
  - mode_pre_move     : volume et/ou open interest qui montent alors que le prix bouge peu
                        (« accumulation avant départ ») ;
  - mode_announcement : annonce officielle d'un exchange (listing, perp, levée de surveillance).

Lecture seule, données publiques. Aucun ordre.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from . import indicators, market

DAY = 86400
DEFAULTS = {
    "enabled": True,
    "pre_move": {"min_quote_volume_24h": 1_000_000, "max_abs_change_24h": 0.10, "max_change_7d": 0.20,
                 "min_vol_ratio": 2.0, "min_oi_change_3d": 0.15, "max_compression": 0.85,
                 "max_candidates": 8, "max_scan": 250, "threads": 8},
    "announcements": {"hours": 48, "fresh_hours": 24, "max_candidates": 10},
}


def settings(cfg_value):
    s = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in (cfg_value or {}).items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


def classify_pre_move(complete_daily, ticker, oi_change_3d, rules):
    """Règle pure (testable) : volume en hausse, prix encore calme, et OI qui monte ou
    volatilité comprimée. Utilise uniquement des journées fermées + le ticker courant."""
    if len(complete_daily) < 15:
        return False, {"raison": "historique < 15 jours"}
    ch24 = ticker["change_24h"]
    c7 = complete_daily[-1]["c"] / complete_daily[-8]["c"] - 1 if len(complete_daily) >= 8 else None
    hist = complete_daily[-14:]
    avg14 = sum(d["vq"] for d in hist) / len(hist)
    vr = ticker["quote_vol_24h"] / avg14 if avg14 > 0 else None
    a7 = indicators.atr(complete_daily[-8:], 7)
    a30 = indicators.atr(complete_daily[-31:], 30) if len(complete_daily) >= 20 else None
    comp = (a7 / a30) if a7 and a30 else None
    det = dict(vol_ratio=vr, change_24h=ch24, change_7d=c7, oi_change_3d=oi_change_3d, compression=comp)
    ok = (vr is not None and vr >= rules["min_vol_ratio"]
          and abs(ch24) < rules["max_abs_change_24h"]
          and (c7 is None or c7 < rules["max_change_7d"])
          and ((oi_change_3d is not None and oi_change_3d >= rules["min_oi_change_3d"])
               or (comp is not None and comp <= rules["max_compression"])))
    return ok, det


def pre_move_scan(tickers, exclude, rules, sources, now=None):
    """Balaye les perps liquides au prix encore calme. Renvoie [(pair, détail)] trié par volume relatif."""
    now = now or time.time()
    pool = [t for t in tickers if t["quote_vol_24h"] >= rules["min_quote_volume_24h"]
            and abs(t["change_24h"]) < rules["max_abs_change_24h"] and t["pair"] not in exclude]
    pool.sort(key=lambda t: -t["quote_vol_24h"])
    pool = pool[: rules["max_scan"]]

    def one(t):
        try:
            daily, _ = market.candles(t["pair"], "1d", now - 40 * DAY, now, sources)
        except Exception:
            return None
        complete = [d for d in daily if d["t"] + DAY <= now]
        if len(complete) < 15:
            return None
        hist = complete[-14:]
        avg14 = sum(d["vq"] for d in hist) / len(hist)
        if not avg14 or t["quote_vol_24h"] / avg14 < rules["min_vol_ratio"]:
            return None                                # filtre bon marché avant l'appel OI
        oi = None
        try:
            series, _ = market.open_interest_usd(t["pair"], days=5)
            if len(series) >= 4 and series[-4][1] > 0:
                oi = series[-1][1] / series[-4][1] - 1
        except Exception:
            pass
        ok, det = classify_pre_move(complete, t, oi, rules)
        return (t["pair"], det) if ok else None

    with ThreadPoolExecutor(max_workers=int(rules.get("threads", 8))) as ex:
        found = [r for r in ex.map(one, pool) if r]
    found.sort(key=lambda r: -(r[1]["vol_ratio"] or 0))
    return found[: rules["max_candidates"]], len(pool)
