"""Simulation bougie par bougie d'une position longue virtuelle.

Règles (STRATEGY.md) :
- on utilise les plus hauts / plus bas de chaque bougie, pas seulement le dernier prix ;
- seules les bougies **fermées** sont traitées, et chacune **une seule fois** : `ps.through`
  (fin de la dernière bougie traitée) est enregistré et la vérification suivante repart de là ;
- toute bougie 15 min où il se passe quelque chose (stop, objectif, passage à l'équilibre,
  stop suiveur, liquidation) est **rejouée minute par minute** quand une fonction `refine`
  est fournie, pour connaître l'ordre réel stop / objectif ; la bougie d'entrée est rejouée
  à partir de la minute qui suit l'entrée ;
- si l'ordre reste inconnu (stop et objectif dans la même minute, ou pas de bougies 1 min),
  le stop compte d'abord (hypothèse prudente) ;
- passage à l'équilibre et stop suiveur s'appliquent à partir de la bougie suivante
  (1 min après affinage) ;
- liquidation estimée si le prix touche le prix de liquidation avant le stop ;
- sortie par le temps à la première bougie qui atteint max_hold_until.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CANDLE_SECONDS = 900  # 15 minutes
FINE_SECONDS = 60     # bougies d'affinage


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
    through: float | None = None     # fin de la dernière bougie traitée
    audit: list = field(default_factory=list)   # comment chaque bougie à événement a été tranchée

    def __post_init__(self):
        self.highest = self.highest or self.entry
        self.lowest = self.lowest or self.entry


def walk(candles, cs, now, refine, opened_ts, through, eventful, advance, audit):
    """Parcours commun (positions simples et tranches).

    - ignore les bougies déjà traitées (fin <= through) et celles antérieures à l'entrée ;
    - s'arrête à la première bougie non fermée (fin > now) ;
    - bougie d'entrée (commence avant l'entrée) : rejouée en 1 min à partir de l'entrée si
      possible, sinon ignorée (on ne sait pas quels prix sont postérieurs à l'entrée) ;
    - bougie à événement : rejouée en 1 min si possible, sinon traitée prudemment.
    Renvoie (résultat de advance ou None, nouveau through)."""
    for k in candles:
        end = k["t"] + cs
        if through is not None and end <= through + 1:
            continue
        if end <= opened_ts:
            continue
        if now is not None and end > now:
            break
        partial = k["t"] < opened_ts - 1
        if refine and (partial or eventful(k)):
            sub = None
            try:
                sub = refine(k["t"], end)
            except Exception:
                sub = None
            sub = [s for s in (sub or []) if k["t"] <= s["t"] < end and s["t"] >= opened_ts - 1]
            if sub:
                audit.append(("1m", k["t"], len(sub)))
                for s in sub:
                    res = advance(s, FINE_SECONDS, True)
                    if res:
                        return res, s["t"] + FINE_SECONDS
                through = end
                continue
            audit.append(("prudent", k["t"], 0))
        if partial:
            through = end
            continue
        res = advance(k, cs, False)
        through = end
        if res:
            return res, through
    return None, through


def _would_trigger(ps, h, l):
    """La bougie touche-t-elle un niveau (stop, objectif, liquidation, équilibre, suiveur) ?"""
    if l <= ps.stop or h >= ps.tp or (ps.liquidation and l <= ps.liquidation):
        return True
    if ps.be_trigger and ps.stop < ps.entry and h >= ps.be_trigger:
        return True
    if ps.trailing_pct and ps.trailing_activate and max(ps.highest, h) >= ps.trailing_activate:
        return max(ps.highest, h) * (1 - ps.trailing_pct) > ps.stop
    return False


def _advance(ps, k, cs, slippage, fine):
    o, h, l, c = k["o"], k["h"], k["l"], k["c"]
    end_ts = k["t"] + cs
    # 1) côté baisse d'abord (hypothèse prudente si l'ordre reste inconnu)
    liq = ps.liquidation
    if liq and liq >= ps.stop and l <= liq:
        ps.lowest = min(ps.lowest, l)
        return dict(exit_price=liq, exit_reason="liquidation", exit_ts=k["t"])
    if l <= ps.stop:
        ps.lowest = min(ps.lowest, l)
        fill = min(ps.stop, o) * (1 - slippage)  # gap sous le stop : exécution à l'ouverture
        if h >= ps.tp:
            ps.audit.append(("stop_et_objectif_meme_bougie", k["t"], cs))
        return dict(exit_price=fill, exit_reason=ps.stop_kind, exit_ts=k["t"])
    # 2) objectif
    if h >= ps.tp:
        ps.highest = max(ps.highest, h)
        ps.lowest = min(ps.lowest, l)
        # TP/SL Bybit = ordre au marché déclenché : même glissement que le stop
        return dict(exit_price=ps.tp * (1 - slippage), exit_reason="tp", exit_ts=k["t"])

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


def step(ps: PosState, candles, slippage=0.0, candle_seconds=CANDLE_SECONDS, refine=None, now=None):
    """Fait avancer la position. Renvoie None si toujours ouverte, sinon
    dict(exit_price, exit_reason, exit_ts). `refine(t0, t1)` renvoie les bougies 1 min
    de [t0, t1) ; `now` limite aux bougies fermées. Met à jour ps.through et ps.audit."""
    res, ps.through = walk(
        candles, candle_seconds, now, refine, ps.opened_ts, ps.through,
        lambda k: _would_trigger(ps, k["h"], k["l"]),
        lambda k, cs, fine: _advance(ps, k, cs, slippage, fine), ps.audit)
    return res


def funding_cost(size_usd, opened_ts, exit_ts, rates=None, funding_8h=0.0001):
    """Funding payé par un long. `rates` : [(t, taux)] réels (règlements entre l'entrée et la
    sortie) ; sinon estimation forfaitaire au prorata du temps."""
    if rates is not None:
        return sum(size_usd * r for t, r in rates if opened_ts < t <= exit_ts)
    hours = max(0.0, (exit_ts - opened_ts) / 3600)
    return size_usd * funding_8h * hours / 8


def pnl(ps: PosState, exit_price, exit_ts, exit_reason, fee_rate, funding_8h, funding_rates=None):
    qty = ps.size_usd / ps.entry
    gross = qty * (exit_price - ps.entry)
    fees = fee_rate * (ps.size_usd + qty * exit_price)
    funding = funding_cost(ps.size_usd, ps.opened_ts, exit_ts, funding_rates, funding_8h)
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
