"""Calcul stop / objectif / taille / levier pour chaque bras (démo uniquement).

Limites absolues reprises de GUARDRAILS.md. La base de données applique les
mêmes limites par trigger : ce module ne peut pas les assouplir.
"""
from __future__ import annotations

import math

HARD = dict(risk_pct_max=0.01, leverage_max=10, max_open_per_arm=8,
            max_entries_per_day_per_arm=3, drawdown_halt=0.15)


def cfg_num(cfg, key, default):
    v = cfg.get(key, default)
    return float(v) if v is not None else default


def stop_distance(params, entry, atr_value=None):
    s = params["stop"]
    if s["type"] == "fixed_pct":
        return float(s["pct"])
    if s["type"] == "atr":
        if not atr_value:
            # historique trop court (nouveau listing) : stop le plus large autorisé, par prudence
            return float(s["max_pct"])
        d = float(s["mult"]) * atr_value / entry
        return min(max(d, float(s["min_pct"])), float(s["max_pct"]))
    raise ValueError(f"type de stop inconnu : {s['type']}")


def tp_distance(params, stop_dist):
    t = params["tp"]
    if t["type"] == "fixed_pct":
        return float(t["pct"])
    if t["type"] == "r_multiple":
        return float(t["r"]) * stop_dist
    raise ValueError(f"type d'objectif inconnu : {t['type']}")


def plan_position(params, entry, equity, cfg, atr_value=None, open_margin=0.0):
    """Renvoie le plan d'une position longue virtuelle, ou lève ValueError."""
    risk_pct = min(cfg_num(cfg, "risk_pct", 0.01), HARD["risk_pct_max"])
    lev_cap = min(cfg_num(cfg, "max_leverage", 10), HARD["leverage_max"],
                  float(params.get("max_leverage") or HARD["leverage_max"]))
    mmr = cfg_num(cfg, "maintenance_margin_rate", 0.01)
    buf = cfg_num(cfg, "liquidation_buffer_pct", 0.02)

    sd = stop_distance(params, entry, atr_value)
    td = tp_distance(params, sd)
    risk_usd = risk_pct * equity
    notional = risk_usd / sd
    # Plafond : notionnel <= levier max x capital.
    notional = min(notional, lev_cap * equity)
    # Levier choisi pour que la liquidation estimée reste SOUS le stop (avec marge).
    lev = max(1, min(lev_cap, math.floor(1 / (sd + mmr + buf))))
    margin = notional / lev
    free = equity - open_margin
    if margin > free:
        if free <= 0:
            raise ValueError("plus de marge virtuelle disponible")
        notional = free * lev
        margin = free
    stop = entry * (1 - sd)
    tp = entry * (1 + td)
    liq = entry * (1 - 1 / lev + mmr)
    be = params.get("breakeven_trigger_pct")
    tr = params.get("trailing")
    return dict(
        entry_price=entry,
        size_usd=round(notional, 2),
        leverage=lev,
        margin_usd=round(margin, 2),
        stop_price=stop,
        tp_price=tp,
        stop_dist=sd,
        tp_dist=td,
        risk_usd=round(notional * sd, 4),
        breakeven_trigger_price=entry * (1 + float(be)) if be else None,
        trailing_pct=sd if tr else None,
        trailing_activate_price=entry * (1 + float(tr["activate_pct"])) if tr else None,
        liquidation_price=liq if liq > 0 else None,
        max_hold_days=float(params.get("max_hold_days", 10)),
    )


def breakeven_winrate(params, stop_dist=None):
    """Taux de réussite d'équilibre = 1 / (1 + gain/perte), hors frais."""
    sd = stop_dist or (params["stop"].get("pct") or 0.15)
    td = tp_distance(params, sd)
    rr = td / sd
    return rr, 1 / (1 + rr)
