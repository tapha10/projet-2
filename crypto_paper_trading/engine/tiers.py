"""Addendum 2ter — paliers P1 à P4 et sorties en tranches (DÉMO UNIQUEMENT).

Les paliers sont des versions de stratégie (`strategy_versions.tier`) du portefeuille
virtuel « T » (1 000 USDT, séparé des bras A/B/C qui restent inchangés).

- Position vivante (capital papier) : une seule entrée par signal, stop structurel P1
  (1,5 x ATR(14) borné 8-12 %), découpée en tranches :
    A = part de P1, sortie à 2,5 R ;  B = part de P2, sortie à 6 R ;
    C = part du coureur (P3/P4), stop suiveur chandelier, vise 10 R, 50 R et plus.
  Après la sortie de la tranche A, le stop du solde passe à l'entrée.
- Une tranche dont le palier n'est pas débloqué ne reçoit pas de capital : sa part
  est rattachée à la tranche A (sortie à l'objectif P1) et elle est suivie en ombre.
  Un palier débloqué au risque r (0,25 %, puis 0,5 %, puis 1 %) ne reçoit que
  r / 1 % de sa part ; le reste revient aussi à la tranche A. Le risque total de la
  position reste donc toujours <= 1 % du capital.
- Paliers « autonomes » P2/P3/P4 (stop serré 3-6 %, objectif unique) : simulés en
  ombre sur chaque signal pour mesurer leur taux de réussite (déblocage).
"""
from __future__ import annotations

import math
import random

from . import risk, simulate

TIERS = ("P1", "P2", "P3", "P4")
BREAKEVEN = {"P1": 1 / (1 + 2.5), "P2": 1 / (1 + 6), "P3": 1 / (1 + 10), "P4": 1 / (1 + 50)}
TARGET_R = {"P1": 2.5, "P2": 6.0, "P3": 10.0, "P4": 50.0}
MIN_EVENTS_UNLOCK = {"P2": 40, "P3": 30, "P4": 30}
RISK_STEPS = (0.0025, 0.005, 0.01)
RISK_CAP = {"P1": 0.01, "P2": 0.01, "P3": 0.01, "P4": 0.005}   # P4 : moitié du risque au plus

# Garde-fous 2ter, propres au portefeuille T (plus stricts que GUARDRAILS.md section 3).
T_LIMITS = dict(risk_pct_max=0.01, leverage_max=3, position_max_pct=0.25, total_notional_max_pct=1.50,
                liq_vs_stop_min=3.0, max_open=8, max_entries_per_day=3, drawdown_halt=0.15)

DEFAULT_SPLIT = (0.5, 0.3, 0.2)
SPLITS = {"50/30/20": (0.5, 0.3, 0.2), "30/30/40": (0.3, 0.3, 0.4),
          "70/20/10": (0.7, 0.2, 0.1), "100/0/0": (1.0, 0.0, 0.0)}
TRANCHE_TIER = {"A": "P1", "B": "P2", "C": "P3"}

P1_STOP = dict(mult=1.5, min_pct=0.08, max_pct=0.12)
PREC_STOP = dict(mult=0.6, min_pct=0.03, max_pct=0.06)   # substitut d'E5 (absente) : stop serré structurel
CHANDELIER_ATR_MULT = 3.0
HOLD_DAYS = {"A": 10, "B": 10, "C": 30}


# ---------------------------------------------------------------- calculs de base
def r_multiple(pnl, risk_usd):
    return pnl / risk_usd if risk_usd else None


def stop_pct(entry, atr_value, spec):
    if not atr_value:
        return spec["max_pct"]
    return min(max(spec["mult"] * atr_value / entry, spec["min_pct"]), spec["max_pct"])


def leverage_for(stop_dist, mmr=0.01):
    """Plus grand levier entier <= 3 tel que la liquidation soit >= 3x plus loin que le stop."""
    lev = math.floor(1 / (T_LIMITS["liq_vs_stop_min"] * stop_dist + mmr))
    return max(1, min(T_LIMITS["leverage_max"], lev))


def liquidation_price(entry, lev, mmr=0.01):
    return entry * (1 - 1 / lev + mmr)


def check_t_guardrails(plan, equity, open_positions, entries_today, drawdown, mmr=0.01):
    """Liste des violations des garde-fous du portefeuille T (vide = accepté)."""
    v = []
    lim = T_LIMITS
    sd = (plan["entry_price"] - plan["stop_price"]) / plan["entry_price"]
    if plan["risk_usd"] > lim["risk_pct_max"] * equity * 1.0001:
        v.append("risque > 1 % du capital")
    if plan["leverage"] > lim["leverage_max"]:
        v.append("levier > 3x")
    if plan["size_usd"] > lim["position_max_pct"] * equity * 1.0001:
        v.append("position > 25 % du capital")
    total = sum(float(p["size_usd"]) for p in open_positions) + plan["size_usd"]
    if total > lim["total_notional_max_pct"] * equity * 1.0001:
        v.append("notionnel total > 150 % du capital")
    liq_dist = 1 - liquidation_price(plan["entry_price"], plan["leverage"], mmr) / plan["entry_price"]
    if liq_dist < lim["liq_vs_stop_min"] * sd * 0.9999:
        v.append("liquidation < 3x la distance du stop")
    if len(open_positions) >= lim["max_open"]:
        v.append("déjà 8 positions ouvertes")
    if entries_today >= lim["max_entries_per_day"]:
        v.append("déjà 3 entrées aujourd'hui")
    if any(p["pair"] == plan.get("pair") for p in open_positions):
        v.append("pair déjà ouvert (pas de moyenne à la baisse)")
    if drawdown > lim["drawdown_halt"]:
        v.append("drawdown > 15 % : entrées suspendues")
    return v


# ---------------------------------------------------------------- plan de position
def live_allocation(tier_state, split=DEFAULT_SPLIT):
    """Parts réellement engagées par tranche selon l'état des paliers.
    tier_state : {P2: {"status": "unlocked"|"shadow"|..., "risk_pct": 0.0025}, P3: {...}}"""
    a, b, c = split
    alloc = {"A": a, "B": 0.0, "C": 0.0}
    for tr, share in (("B", b), ("C", c)):
        tier = TRANCHE_TIER[tr]
        st = tier_state.get(tier) or {}
        if st.get("status") == "unlocked":
            frac = min(1.0, float(st.get("risk_pct", RISK_STEPS[0])) / 0.01)
            alloc[tr] = share * frac
            alloc["A"] += share * (1 - frac)
        else:
            alloc["A"] += share
    s = sum(alloc.values())
    return {k: round(v / s, 10) for k, v in alloc.items()}


def plan_t_position(entry, equity, atr_value, tier_state, split=DEFAULT_SPLIT, mmr=0.01, open_margin=0.0):
    sd = stop_pct(entry, atr_value, P1_STOP)
    risk_usd = min(T_LIMITS["risk_pct_max"], 0.01) * equity
    notional = min(risk_usd / sd, T_LIMITS["position_max_pct"] * equity)
    lev = leverage_for(sd, mmr)
    stop = entry * (1 - sd)
    alloc = live_allocation(tier_state, split)
    tranches = {}
    for tr, share in alloc.items():
        target = entry * (1 + TARGET_R[TRANCHE_TIER[tr]] * sd) if tr != "C" else None
        tranches[tr] = dict(share=share, target=target, status="open" if share > 0 else "none",
                            exit_price=None, exit_reason=None, pnl_usd=None,
                            max_hold_days=HOLD_DAYS[tr])
    return dict(entry_price=entry, stop_price=stop, stop_dist=sd, size_usd=round(notional, 2),
                risk_usd=round(notional * sd, 4), leverage=lev, margin_usd=round(notional / lev, 2),
                liquidation_price=liquidation_price(entry, lev, mmr),
                tp_price=entry * (1 + TARGET_R["P1"] * sd), atr=atr_value,
                chandelier_mult=CHANDELIER_ATR_MULT, tranches=tranches, split=list(split))


# ---------------------------------------------------------------- simulation des tranches
def step_tranches(pos, candles, slippage=0.0, candle_seconds=900, refine=None, now=None):
    """Avance une position en tranches. pos : dict (voir plan_t_position) + opened_ts,
    highest, lowest, stop_price, peak_ts (+ through, fin de la dernière bougie traitée).
    Modifie pos ; renvoie la liste des événements. Mêmes règles que simulate.step :
    bougies fermées seulement, chacune une seule fois ; bougie d'entrée et bougies à
    événement rejouées en 1 min si `refine` est fourni ; sinon stop d'abord dans une même
    bougie ; stop à l'entrée et stop suiveur appliqués à partir de la bougie suivante."""
    ev = []
    entry = pos["entry_price"]
    atr = pos.get("atr") or entry * pos["stop_dist"] / P1_STOP["mult"]
    pos.setdefault("audit", [])
    _, pos["through"] = simulate.walk(
        candles, candle_seconds, now, refine, pos["opened_ts"], pos.get("through"),
        lambda k: _t_eventful(pos, k, atr),
        lambda k, cs, fine: _t_advance(pos, k, cs, slippage, ev, entry, atr), pos["audit"])
    return ev


def _t_eventful(pos, k, atr):
    for d in pos["tranches"].values():
        if d["status"] != "open":
            continue
        if k["l"] <= d.get("stop", pos["stop_price"]) or (d["target"] and k["h"] >= d["target"]):
            return True
    c = pos["tranches"].get("C")
    if c and c["status"] == "open" and k["h"] > pos["highest"]:
        return k["l"] <= k["h"] - pos["chandelier_mult"] * atr
    return False


def _t_advance(pos, k, candle_seconds, slippage, ev, entry, atr):
    """Une bougie ; renvoie True quand toutes les tranches sont fermées."""
    if not [t for t, d in pos["tranches"].items() if d["status"] == "open"]:
        return True
    open_tr = [t for t, d in pos["tranches"].items() if d["status"] == "open"]
    end_ts = k["t"] + candle_seconds
    # 1) stop (commun à toutes les tranches ouvertes ; le coureur a son propre suiveur)
    for t in list(open_tr):
        d = pos["tranches"][t]
        st = d.get("stop", pos["stop_price"])
        if k["l"] <= st:
            fill = min(st, k["o"]) * (1 - slippage)
            if st <= pos["initial_stop_price"] * (1 + 1e-9):
                reason = "sl"
            elif abs(st - entry) / entry < 1e-9:
                reason = "breakeven"
            else:
                reason = "trailing"
            close_tranche(pos, t, fill, reason, k["t"])
            ev.append((t, reason, k["t"]))
    # 2) objectifs
    for t, d in pos["tranches"].items():
        if d["status"] == "open" and d["target"] and k["h"] >= d["target"]:
            close_tranche(pos, t, d["target"] * (1 - slippage), "tp", k["t"])
            ev.append((t, "tp", k["t"]))
    if k["h"] > pos["highest"]:
        pos["highest"], pos["peak_ts"] = k["h"], k["t"]
    pos["lowest"] = min(pos["lowest"], k["l"])
    # 3) après la tranche A : stop du solde à l'entrée
    if pos["tranches"]["A"]["status"] == "closed" and pos["tranches"]["A"]["exit_reason"] == "tp":
        if pos["stop_price"] < entry:
            pos["stop_price"] = entry
            ev.append(("*", "stop_to_entry", k["t"]))
    # 4) coureur : stop chandelier (plus haut - 3 x ATR), jamais sous le stop commun
    c = pos["tranches"]["C"]
    if c["status"] == "open":
        ch = pos["highest"] - pos["chandelier_mult"] * atr
        c["stop"] = max(pos["stop_price"], ch, c.get("stop", 0))
    for t, d in pos["tranches"].items():
        if t != "C" and d["status"] == "open":
            d["stop"] = pos["stop_price"]
    # 5) durée maximale par tranche
    for t, d in pos["tranches"].items():
        if d["status"] == "open" and end_ts >= pos["opened_ts"] + d["max_hold_days"] * 86400:
            close_tranche(pos, t, k["c"] * (1 - slippage), "time", end_ts)
            ev.append((t, "time", end_ts))
    return all(d["status"] != "open" for d in pos["tranches"].values())


def close_tranche(pos, t, price, reason, ts):
    d = pos["tranches"][t]
    d.update(status="closed", exit_price=price, exit_reason=reason, exit_ts=ts)


def settle(pos, fee_rate=0.0005, funding_8h=0.0001, last_price=None, now_ts=None, funding_rates=None):
    """Résultat agrégé : gains par tranche (dont la somme = total), R, MFE, MAE, pic."""
    entry, size = pos["entry_price"], pos["size_usd"]
    total = 0.0
    per = {}
    for t, d in pos["tranches"].items():
        if d["share"] <= 0:
            continue
        notional = size * d["share"]
        qty = notional / entry
        if d["status"] == "closed":
            px, ts = d["exit_price"], d["exit_ts"]
        else:
            if last_price is None:
                continue
            px, ts = last_price, now_ts
        fees = fee_rate * (notional + qty * px)
        funding = simulate.funding_cost(notional, pos["opened_ts"], ts, funding_rates, funding_8h)
        pnl = qty * (px - entry) - fees - funding
        d["pnl_usd"] = round(pnl, 6) if d["status"] == "closed" else None
        per[t] = pnl
        total += pnl
    return dict(pnl_usd=round(total, 6), per_tranche={k: round(v, 6) for k, v in per.items()},
                r_multiple=round(r_multiple(total, pos["risk_usd"]), 6) if pos["risk_usd"] else None,
                mfe_pct=round(pos["highest"] / entry - 1, 6), mae_pct=round(pos["lowest"] / entry - 1, 6),
                mfe_r=round((pos["highest"] / entry - 1) / pos["stop_dist"], 4),
                time_to_peak_h=round((pos.get("peak_ts", pos["opened_ts"]) - pos["opened_ts"]) / 3600, 2))


def new_pos(plan, opened_ts):
    pos = dict(plan)
    pos["tranches"] = {k: dict(v) for k, v in plan["tranches"].items()}
    pos.update(opened_ts=opened_ts, highest=plan["entry_price"], lowest=plan["entry_price"], peak_ts=opened_ts,
               initial_stop_price=plan["stop_price"])
    for d in pos["tranches"].values():
        d["stop"] = plan["stop_price"]
    return pos


def replay_split(entry, atr, candles, opened_ts, split, tier_state=None, slippage=0.001, candle_seconds=3600):
    """Rejoue une découpe sur des bougies (tous paliers « débloqués » à 1 % par défaut)."""
    ts = tier_state or {"P2": {"status": "unlocked", "risk_pct": 0.01}, "P3": {"status": "unlocked", "risk_pct": 0.01}}
    plan = plan_t_position(entry, 1000.0, atr, ts, split)
    pos = new_pos(plan, opened_ts)
    step_tranches(pos, candles, slippage, candle_seconds)
    last = candles[-1] if candles else None
    return settle(pos, last_price=last["c"] if last else None, now_ts=(last["t"] + candle_seconds) if last else None)


# ---------------------------------------------------------------- paliers autonomes (ombre)
def shadow_tier_trade(tier, entry, atr, candles, opened_ts, slippage=0.001, candle_seconds=3600):
    """Trade simulé d'un palier autonome : P1 stop 8-12 % / 2,5 R ; P2-P4 stop 3-6 % et
    objectif 6, 10 ou 50 R. Renvoie win (objectif atteint), r, r avec glissement x2."""
    spec = P1_STOP if tier == "P1" else PREC_STOP
    sd = stop_pct(entry, atr, spec)
    params = {"stop": {"type": "fixed_pct", "pct": sd}, "tp": {"type": "r_multiple", "r": TARGET_R[tier]},
              "max_leverage": 3, "max_hold_days": 10 if tier in ("P1", "P2") else 30,
              "breakeven_trigger_pct": None, "trailing": None}
    cfg = {"risk_pct": 0.01, "max_leverage": 3, "maintenance_margin_rate": 0.01, "liquidation_buffer_pct": 0.02}
    plan = risk.plan_position(params, entry, 1000.0, cfg)
    r1 = simulate.replay(plan, candles, opened_ts, 0.0005, 0.0001, slippage, candle_seconds)
    r2 = simulate.replay(plan, candles, opened_ts, 0.0005, 0.0001, 2 * slippage, candle_seconds)
    if r1 is None:
        return None
    return dict(tier=tier, stop_pct=sd, win=r1["exit_reason"] == "tp", exit=r1["exit_reason"],
                r=r1["r_multiple"], r_slip2=r2["r_multiple"], mfe_pct=r1["mfe_pct"], mae_pct=r1["mae_pct"],
                hold_hours=r1["hold_hours"], complete=r1["exit_reason"] != "open")


# ---------------------------------------------------------------- statistiques de déblocage
def wilson(k, n, z=1.2816):
    """Intervalle de Wilson (z = 1,2816 -> intervalle bilatéral à 80 %)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def mc_max_drawdown_r(rs, n_trades=50, n_sims=2000, seed=7):
    """95e centile du drawdown maximal (en R) sur n_trades tirés avec remise."""
    if not rs:
        return None
    rnd = random.Random(seed)
    dds = []
    for _ in range(n_sims):
        eq = peak = dd = 0.0
        for _ in range(n_trades):
            eq += rnd.choice(rs)
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        dds.append(dd)
    dds.sort()
    return dds[int(0.95 * n_sims) - 1]


def evaluate_unlock(tier, events, current, risk_pct_next=RISK_STEPS[0]):
    """events : trades d'ombre (un par événement indépendant, déjà filtrés et hors
    échantillon) avec win, r, r_slip2. Renvoie (ok, détail)."""
    n = len(events)
    k = sum(1 for e in events if e["win"])
    lo, hi = wilson(k, n)
    be = BREAKEVEN[tier]
    exp2 = sum(e["r_slip2"] for e in events) / n if n else None
    mc = mc_max_drawdown_r([e["r_slip2"] for e in events]) if n else None
    mc_ok = mc is not None and mc * risk_pct_next <= T_LIMITS["drawdown_halt"]
    need = MIN_EVENTS_UNLOCK.get(tier, 40)
    detail = dict(n=n, wins=k, win_rate=k / n if n else None, lo80=lo, hi80=hi, breakeven=be,
                  expectancy_slip2=exp2, mc_dd95_r=mc, min_events=need)
    reasons = []
    if n < need:
        reasons.append(f"{n} événements < {need}")
    if not lo >= be + 0.03 - 1e-12:
        reasons.append(f"borne basse 80 % {lo:.3f} < équilibre {be:.3f} + 3 pts")
    if exp2 is None or exp2 <= 0:
        reasons.append("espérance <= 0 avec glissement x2")
    if not mc_ok:
        reasons.append("Monte Carlo : drawdown 95 % trop élevé")
    detail["reasons"] = reasons
    return (not reasons), detail


def evaluate_demote(tier, last_events):
    """Retour en ombre si la borne haute 80 % sur les 40 derniers événements < équilibre."""
    ev = last_events[-40:]
    n = len(ev)
    k = sum(1 for e in ev if e["win"])
    lo, hi = wilson(k, n)
    demote = n >= 40 and hi < BREAKEVEN[tier]
    return demote, dict(n=n, wins=k, hi80=hi, breakeven=BREAKEVEN[tier])


def next_risk_step(current_risk, weeks_since_step, new_events_since_step):
    if weeks_since_step >= 3 and new_events_since_step >= 15:
        for s in RISK_STEPS:
            if s > current_risk + 1e-12:
                return s
    return current_risk


def tier_label(tier, status, n_events_tested, best_hi=None):
    """débloqué / ombre / inconclusif / impossible avec ces données."""
    if status == "unlocked":
        return "débloqué"
    if n_events_tested >= 100 and best_hi is not None and best_hi < BREAKEVEN[tier]:
        return "impossible avec ces données"
    if n_events_tested < MIN_EVENTS_UNLOCK.get(tier, 40):
        return "inconclusif"
    return "ombre"
