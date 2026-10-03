"""Simulation bougie par bougie d'une position longue virtuelle.

Règles (STRATEGY.md) :
- on utilise les plus hauts / plus bas de chaque bougie, pas seulement le dernier prix ;
- si stop et objectif sont touchés dans la même bougie, le stop compte d'abord ;
- passage à l'équilibre et stop suiveur s'appliquent à partir de la bougie suivante
  (on ne connaît pas l'ordre des prix à l'intérieur d'une bougie) ;
- liquidation estimée si le prix touche le prix de liquidation avant le stop ;
- sortie par le temps à la première bougie qui atteint max_hold_until.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CANDLE_SECONDS = 900  # 15 minutes


@dataclass
class PosState:
    entry: float
    size_usd: float
    leverage: float
    stop: float
    initial_stop: float
    tp: float
    opened_ts: float
    max_hold_ts: float
    be_trigger: float | None = None
    trailing_pct: float | None = None
    trailing_activate: float | None = None
    liquidation: float | None = None
    highest: float | None = None
    lowest: float | None = None
    stop_kind: str = "sl"            # sl | breakeven | trailing
    events: list = field(default_factory=list)

    def __post_init__(self):
        self.highest = self.highest or self.entry
        self.lowest = self.lowest or self.entry


def step(ps: PosState, candles, slippage=0.0, candle_seconds=CANDLE_SECONDS):
    """Fait avancer la position. Renvoie None si toujours ouverte, sinon
    dict(exit_price, exit_reason, exit_ts)."""
    for k in candles:
        if k["t"] < ps.opened_ts - 1:
            continue  # bougie antérieure à l'entrée
        o, h, l, c = k["o"], k["h"], k["l"], k["c"]
        end_ts = k["t"] + candle_seconds

        # 1) côté baisse d'abord (hypothèse prudente)
        liq = ps.liquidation
        if liq and liq >= ps.stop and l <= liq:
            ps.lowest = min(ps.lowest, l)
            return dict(exit_price=liq, exit_reason="liquidation", exit_ts=k["t"])
        if l <= ps.stop:
            ps.lowest = min(ps.lowest, l)
            fill = min(ps.stop, o) * (1 - slippage)  # gap sous le stop : exécution à l'ouverture
            return dict(exit_price=fill, exit_reason=ps.stop_kind, exit_ts=k["t"])
        # 2) objectif
        if h >= ps.tp:
            ps.highest = max(ps.highest, h)
            ps.lowest = min(ps.lowest, l)
            return dict(exit_price=ps.tp, exit_reason="tp", exit_ts=k["t"])

        ps.highest = max(ps.highest, h)
        ps.lowest = min(ps.lowest, l)
        # 3) passage à l'équilibre
        if ps.be_trigger and ps.highest >= ps.be_trigger and ps.stop < ps.entry:
            ps.stop = ps.entry
            ps.stop_kind = "breakeven"
            ps.events.append(("breakeven", k["t"]))
        # 4) stop suiveur
        if ps.trailing_pct and ps.trailing_activate and ps.highest >= ps.trailing_activate:
            new_stop = ps.highest * (1 - ps.trailing_pct)
            if new_stop > ps.stop:
                ps.stop = new_stop
                ps.stop_kind = "trailing"
                ps.events.append(("trailing", k["t"], new_stop))
        # 5) durée maximale
        if end_ts >= ps.max_hold_ts:
            return dict(exit_price=c * (1 - slippage), exit_reason="time", exit_ts=end_ts)
    return None


def pnl(ps: PosState, exit_price, exit_ts, exit_reason, fee_rate, funding_8h):
    qty = ps.size_usd / ps.entry
    gross = qty * (exit_price - ps.entry)
    fees = fee_rate * (ps.size_usd + qty * exit_price)
    hours = max(0.0, (exit_ts - ps.opened_ts) / 3600)
    funding = ps.size_usd * funding_8h * hours / 8
    margin = ps.size_usd / ps.leverage
    if exit_reason == "liquidation":
        net = -margin - fees  # toute la marge isolée est perdue
    else:
        net = gross - fees - funding
    risk = ps.size_usd * (ps.entry - ps.initial_stop) / ps.entry
    return dict(
        pnl_usd=round(net, 4),
        pnl_pct=round(exit_price / ps.entry - 1, 6),
        r_multiple=round(net / risk, 4) if risk > 0 else None,
        fees_usd=round(fees, 4),
        funding_usd=round(funding, 4),
        mfe_pct=round(ps.highest / ps.entry - 1, 6),
        mae_pct=round(ps.lowest / ps.entry - 1, 6),
    )


def replay(plan, candles, opened_ts, fee_rate=0.0005, funding_8h=0.0001, slippage=0.0,
           candle_seconds=3600):
    """Rejoue un plan (risk.plan_position) sur des bougies : utilisé pour le
    walk-forward et les résultats contrefactuels. Renvoie dict de résultat."""
    ps = PosState(entry=plan["entry_price"], size_usd=plan["size_usd"], leverage=plan["leverage"],
                  stop=plan["stop_price"], initial_stop=plan["stop_price"], tp=plan["tp_price"],
                  opened_ts=opened_ts, max_hold_ts=opened_ts + plan["max_hold_days"] * 86400,
                  be_trigger=plan.get("breakeven_trigger_price"),
                  trailing_pct=plan.get("trailing_pct"),
                  trailing_activate=plan.get("trailing_activate_price"),
                  liquidation=plan.get("liquidation_price"))
    res = step(ps, candles, slippage, candle_seconds)
    if res is None:
        if not candles:
            return None
        last = candles[-1]
        res = dict(exit_price=last["c"], exit_reason="open", exit_ts=last["t"] + candle_seconds)
    out = pnl(ps, res["exit_price"], res["exit_ts"], res["exit_reason"], fee_rate, funding_8h)
    out.update(exit_reason=res["exit_reason"], exit_price=res["exit_price"],
               hold_hours=round((res["exit_ts"] - opened_ts) / 3600, 2))
    return out
