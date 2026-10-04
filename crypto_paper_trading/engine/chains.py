"""Routine 7 — « chaînes de victoires » (PAPIER UNIQUEMENT).

Une chaîne risque 1 % du capital à l'étape 1, puis à chaque étape seulement le gain de
l'étape précédente (« argent de la maison ») : la perte maximale d'une chaîne est donc 1 %.
Hypothèse à tester, pas un fait : chaque variante est comparée hors échantillon à
- une chaîne à entrées aléatoires (même stop, même objectif, mêmes frais) ;
- une chaîne « prends tout signal » (seuils de score à 0) ;
- la même stratégie sans enchaînement (risque fixe 1 % à chaque trade).

Un « événement » est une occasion d'entrée datée (un signal) avec, pour chaque couple
(stop, R) de la grille, le résultat simulé par le moteur de rejeu existant (simulate.replay) :
victoire = objectif atteint ; perte = stop ; sortie par le temps = fin de chaîne.
Les résultats d'un événement ne dépendent pas du niveau de la chaîne : le niveau ne change
que le stop, l'objectif et le score exigé.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from . import discovery, features, risk, simulate

DAY = 86400.0
GRID_STOPS = (0.05, 0.075, 0.10, 0.15)
GRID_R = (2, 3, 4, 5)
STOP_MAX = 0.15
HARD = dict(max_leverage_live=3.0, max_open_chains=3, liq_vs_stop=2.0, stop_max=STOP_MAX,
            liquidity_share=0.001, drawdown_halt=0.15, risk_pct=0.01)
STATUSES = ("explore", "ombre", "challenger", "champion", "restreint", "pause", "retiré", "inconclusif")


def gkey(stop, r):
    return f"{float(stop):.3f}|{int(r)}"


# ----------------------------------------------------------------- paramètres
BASE = dict(name="utilisateur_5x3R", chain_len=5, stops=[0.10, 0.05, 0.05, 0.05, 0.05], r_mult=3,
            reinvest=1.0, max_leverage=3.0, gating=[3, 3, 4, 5, 5], option="wait", wait_days=None,
            cash_share=0.5, risk_pct=0.01, max_open_chains=3, max_hold_days=10)


def variant(**kw):
    p = dict(BASE)
    p.update(kw)
    n = int(p["chain_len"])
    p["stops"] = (list(p["stops"]) + [p["stops"][-1]] * n)[:n]
    p["gating"] = (list(p["gating"]) + [p["gating"][-1]] * n)[:n]
    return p


def default_variants():
    """Variantes testées en ombre (points de départ arbitraires, pas des indices de réussite)."""
    return [
        variant(),
        variant(name="chaine_3", chain_len=3),
        variant(name="R2", r_mult=2), variant(name="R4", r_mult=4), variant(name="R5", r_mult=5),
        variant(name="stop10_constant", stops=[0.10] * 5),
        variant(name="stop5_constant", stops=[0.05] * 5),
        variant(name="stop15_45pc", stops=[0.15] * 5),
        variant(name="reinvest_75", reinvest=0.75), variant(name="reinvest_50", reinvest=0.5),
        variant(name="securiser_3j", option="secure", wait_days=3),
        variant(name="reinitialiser_50", option="reset", wait_days=3, cash_share=0.5),
        variant(name="seuils_plats_3", gating=[3] * 5),
        variant(name="seuils_stricts", gating=[4, 4, 5, 6, 6]),
        variant(name="levier_5x_ombre", max_leverage=5.0),
        variant(name="levier_7x_ombre", max_leverage=7.0),
    ]


def reference_variants(p):
    """Références obligatoires pour une variante p."""
    return dict(prend_tout=dict(p, name=p["name"] + "|prend_tout", gating=[-1e9] * p["chain_len"]))


# ----------------------------------------------------------------- arithmétique d'une étape
def step_size(risk_usd, stop_pct, r_mult, equity, max_leverage, vol24h=None, slip=0.001, mmr=0.01):
    """Taille d'une étape. Le stop n'est jamais élargi : si le levier, la liquidation ou la
    liquidité ne permettent pas la taille voulue, c'est le RISQUE qui est réduit.
    Renvoie dict(size, risk, leverage, tp_pct, reduced, reason) ou dict(refused=raison)."""
    if stop_pct <= 0 or stop_pct > STOP_MAX + 1e-12:
        return dict(refused=f"stop {stop_pct:.1%} > plafond {STOP_MAX:.0%}")
    if risk_usd <= 0 or equity <= 0:
        return dict(refused="risque ou capital nul")
    size = risk_usd / stop_pct
    lev_liq = 1.0 / (HARD["liq_vs_stop"] * (stop_pct + slip) + mmr)     # liquidation >= 2x le stop
    lev_cap = min(max_leverage, lev_liq)
    caps = [(lev_cap * equity, f"levier {lev_cap:.2f}x")]
    if vol24h:
        caps.append((HARD["liquidity_share"] * vol24h, "liquidité 0,1 % du volume 24 h"))
    reason = None
    for cap, why in caps:
        if size > cap:
            size, reason = cap, why
    return dict(size=size, risk=size * stop_pct, leverage=size / equity, tp_pct=stop_pct * r_mult,
                reduced=reason is not None, reason=reason, lev_cap=lev_cap)


def chain_ledger(risk1, r_mult, n, reinvest=1.0):
    """Arithmétique pure (sans frais) : risques, gains et bilan d'échec à chaque étape."""
    risks, gains, bank = [], [], 0.0
    r = risk1
    fail_balance = []
    acc = 0.0
    for _ in range(n):
        risks.append(r)
        fail_balance.append(acc - r)          # bilan de la chaîne si l'étape échoue
        g = r * r_mult
        gains.append(g)
        acc += g
        bank += (1 - reinvest) * g
        r = reinvest * g
    return dict(risks=risks, gains=gains, total=acc, fail_balance=fail_balance)


# ----------------------------------------------------------------- résultats d'un événement
def event_outcomes(entry, candles, opened_ts, candle_seconds=3600, fee=0.00055, fund=0.0001, slip=0.001,
                   max_hold_days=10, stops=GRID_STOPS, rs=GRID_R):
    """Rejoue l'entrée pour toute la grille (stop, R) avec le moteur existant (stop d'abord
    si l'ordre est inconnu, frais, funding, glissement ; glissement x2 en parallèle)."""
    out = {}
    for s in stops:
        for r in rs:
            plan = dict(entry_price=entry, size_usd=100.0, leverage=1.0, stop_price=entry * (1 - s),
                        tp_price=entry * (1 + s * r), max_hold_days=max_hold_days, liquidation_price=None)
            a = simulate.replay(plan, candles, opened_ts, fee, fund, slip, candle_seconds)
            b = simulate.replay(plan, candles, opened_ts, fee, fund, 2 * slip, candle_seconds)
            if a is None:
                continue
            out[gkey(s, r)] = dict(win=a["exit_reason"] == "tp", reason=a["exit_reason"],
                                   r=a["r_multiple"], r2=b["r_multiple"],
                                   exit_ts=opened_ts + a["hold_hours"] * 3600,
                                   complete=a["exit_reason"] != "open")
    return out


def btc_regime(btc_daily, ts):
    """Condition de marché à la date ts (bougies BTC journalières fermées avant ts)."""
    rows = [k for k in btc_daily if k["t"] + DAY <= ts]
    if len(rows) < 21:
        return "inconnu"
    closes = [k["c"] for k in rows]
    trs = [max(k["h"] - k["l"], abs(k["h"] - p["c"]), abs(k["l"] - p["c"])) for p, k in zip(rows[-15:-1], rows[-14:])]
    atr_pct = sum(trs) / len(trs) / closes[-1]
    sma20 = sum(closes[-20:]) / 20
    ret20 = closes[-1] / closes[-21] - 1
    if atr_pct > 0.04:
        return "forte_volatilite"
    if closes[-1] > sma20 and ret20 > 0.03:
        return "haussier"
    if closes[-1] < sma20 and ret20 < -0.03:
        return "baissier"
    return "calme"


# ----------------------------------------------------------------- simulation de chaînes
@dataclass
class Chain:
    cid: int
    start_ts: float
    level: int = 0                      # victoires acquises
    gate_level: int = 0                 # niveau utilisé pour le seuil (option « réinitialiser »)
    house: float = 0.0                  # gains de la chaîne non encaissés (risque de l'étape suivante)
    bank: float = 0.0                   # gains encaissés
    balance: float = 0.0                # bilan net de la chaîne
    state: str = "ouverte"
    open_step: dict | None = None
    idle_since: float = 0.0
    end_ts: float | None = None
    steps: list = field(default_factory=list)
    reason: str = ""


def run_chains(events, p, capital=1000.0, slip_mult=1, source="replay_history", rng=None, accept=None,
               slip=0.001, max_chains_total=None):
    """Fait tourner une variante sur un flux d'événements daté. accept(event, chain) remplace le
    seuil de score (références « aléatoire »). Renvoie dict(chains, steps, equity_curve)."""
    evs = sorted(events, key=lambda e: e["ts"])
    rkey = "r2" if slip_mult == 2 else "r"
    n = int(p["chain_len"])
    chains, done, steps = [], [], []
    equity = capital
    curve = [(evs[0]["ts"] if evs else 0, equity)]
    next_id = [1]

    def settle_until(t):
        nonlocal equity
        pend = sorted((c for c in chains if c.open_step and c.open_step["exit_ts"] <= t),
                      key=lambda c: c.open_step["exit_ts"])
        for c in pend:
            st = c.open_step
            c.open_step = None
            pnl = st["risk"] * st[rkey]
            st["pnl"] = pnl
            equity += pnl
            curve.append((st["exit_ts"], equity))
            c.balance += pnl
            c.idle_since = st["exit_ts"]
            if st["win"]:
                c.level += 1
                c.gate_level += 1
                c.house += pnl * p["reinvest"]
                c.bank += pnl * (1 - p["reinvest"])
                if c.level >= n:
                    c.state, c.end_ts, c.reason = "réussie", st["exit_ts"], f"{n} victoires"
                    c.bank, c.house = c.balance, 0.0
            else:
                c.state = "échouée"
                c.end_ts = st["exit_ts"]
                c.reason = "stop touché" if st["reason"] in ("sl", "liquidation") else f"sortie {st['reason']}"
                c.house = 0.0
        for c in [c for c in chains if c.state != "ouverte"]:
            chains.remove(c)
            done.append(c)

    def timeouts(t):
        if p["option"] not in ("secure", "reset") or not p.get("wait_days"):
            return
        for c in chains:
            if c.open_step or c.level == 0 or t - c.idle_since < p["wait_days"] * DAY:
                continue
            if p["option"] == "secure":
                c.bank, c.house = c.balance, 0.0
                c.state, c.end_ts, c.reason = "sécurisée", c.idle_since + p["wait_days"] * DAY, \
                    f"aucun signal assez bon en {p['wait_days']} j : gain verrouillé au niveau {c.level}"
            else:  # reset : on encaisse une part, le reste repart avec les seuils du niveau 1
                part = c.house * p["cash_share"]
                c.bank += part
                c.house -= part
                c.gate_level = 0
                c.idle_since = t
        for c in [c for c in chains if c.state != "ouverte"]:
            chains.remove(c)
            done.append(c)

    for e in evs:
        t = e["ts"]
        settle_until(t)
        timeouts(t)
        if max_chains_total and next_id[0] > max_chains_total and not chains:
            break
        while len(chains) < p["max_open_chains"] and (not max_chains_total or next_id[0] <= max_chains_total):
            chains.append(Chain(cid=next_id[0], start_ts=t, idle_since=t))
            next_id[0] += 1
        busy_pairs = {c.open_step["pair"] for c in chains if c.open_step}
        for c in chains:
            if c.open_step or e["pair"] in busy_pairs:
                continue
            k = c.level + 1
            gk = min(c.gate_level + 1, n)
            ok = accept(e, c) if accept else e.get("score", 0) >= p["gating"][gk - 1]
            if not ok:
                continue
            stop = p["stops"][k - 1]
            o = (e.get("outcomes") or {}).get(gkey(stop, p["r_mult"]))
            if not o or not o.get("complete"):
                continue
            # étape 1 : 1 % du capital ; ensuite (ou après « réinitialiser ») : argent de la maison seulement
            risk_usd = c.house if c.house > 0 else p["risk_pct"] * equity
            plan = step_size(risk_usd, stop, p["r_mult"], max(equity, 1e-9), p["max_leverage"],
                             e.get("vol24h"), slip * slip_mult)
            if plan.get("refused"):
                continue
            st = dict(k=k, event_id=e.get("id"), pair=e["pair"], ts=t, score=e.get("score"),
                      gate=p["gating"][gk - 1], regime=e.get("regime", "inconnu"), stop=stop,
                      r_mult=p["r_mult"], risk=plan["risk"], size=plan["size"], leverage=plan["leverage"],
                      reduced=plan["reason"], win=o["win"], reason=o["reason"], r=o["r"], r2=o["r2"],
                      exit_ts=o["exit_ts"], source=source, chain=c.cid, cluster=e.get("cluster"))
            if c.house > 0:
                c.bank += max(0.0, c.house - plan["risk"])   # risque réduit : le reste est encaissé
            c.house = 0.0
            c.open_step = st
            c.steps.append(st)
            steps.append(st)
            busy_pairs.add(e["pair"])
            break
    settle_until(float("inf"))
    done.extend(chains)           # chaînes encore ouvertes en fin de données
    return dict(chains=done, steps=steps, curve=curve, equity=equity)


def random_accept(rate, seed):
    rng = random.Random(seed)
    return lambda e, c: rng.random() < rate


def fixed_risk(events, p, capital=1000.0, slip_mult=1):
    """Même stratégie SANS enchaînement : chaque signal qui passe le seuil du niveau 1, risque
    fixe de 1 % du capital, stop et objectif du niveau 1."""
    rkey = "r2" if slip_mult == 2 else "r"
    eq, peak, mdd, trades = capital, capital, 0.0, []
    for e in sorted(events, key=lambda e: e["ts"]):
        if e.get("score", 0) < p["gating"][0]:
            continue
        o = (e.get("outcomes") or {}).get(gkey(p["stops"][0], p["r_mult"]))
        if not o or not o.get("complete"):
            continue
        pnl = p["risk_pct"] * eq * o[rkey]
        eq += pnl
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        trades.append(pnl)
    return dict(n=len(trades), total=eq - capital, ev_trade=(sum(trades) / len(trades)) if trades else None,
                max_dd=mdd)


# ----------------------------------------------------------------- statistiques
def wilson(k, n, z=1.2816):
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    m = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def max_drawdown(curve):
    peak, mdd = -1e18, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, 1 - e / peak)
    return mdd


def independent_wins(chain):
    """Victoires indépendantes d'une chaîne : plusieurs victoires sur la même hausse d'un même pair
    (entrées à moins de 10 jours) ne comptent qu'une fois."""
    wins = [s for s in chain.steps if s.get("win")]
    rows = [dict(pair=s["pair"], ts=s["ts"]) for s in wins]
    return len(features.cluster_events(rows, window_days=10)) if rows else 0


def summarize(res, p, capital=1000.0, months=None):
    ch = [c for c in res["chains"] if c.state != "ouverte"]
    n = len(ch)
    risk1 = p["risk_pct"] * capital
    reach = {k: sum(1 for c in ch if c.level >= k) for k in range(1, int(p["chain_len"]) + 1)}
    full = reach.get(int(p["chain_len"]), 0)
    bal = sorted(c.balance for c in ch)
    failed = [c.balance for c in ch if c.state == "échouée"]
    dur = [((c.end_ts or c.start_ts) - c.start_ts) / DAY for c in ch]
    by_level, by_regime = {}, {}
    for s in res["steps"]:
        if "pnl" not in s:
            continue
        a = by_level.setdefault(s["k"], [0, 0])
        a[0] += s["win"]
        a[1] += 1
        b = by_regime.setdefault(s["regime"], [0, 0, 0.0])
        b[0] += s["win"]
        b[1] += 1
        b[2] += s["pnl"]
    span = months
    if span is None and res["steps"]:
        span = max(1e-9, (max(s["exit_ts"] for s in res["steps"]) - min(s["ts"] for s in res["steps"])) / (30 * DAY))
    lo, hi = wilson(full, n)
    ev = sum(bal) / n if n else None
    return dict(name=p["name"], n_chains=n, reach=reach, full=full, p_full=(full / n) if n else None,
                p_full_lo80=lo, p_full_hi80=hi, median_balance=bal[n // 2] if n else None,
                mean_balance=ev, ev_chain_R=(ev / risk1) if n else None,
                mean_loss_failed=(sum(failed) / len(failed)) if failed else None,
                mean_days=(sum(dur) / n) if n else None,
                chains_per_month=(n / span) if span else None, full_per_month=(full / span) if span else None,
                ev_month=(sum(bal) / span) if span else None, max_dd=max_drawdown(res["curve"]),
                p_win_by_level={k: dict(wins=w, n=m, p=w / m if m else None) for k, (w, m) in sorted(by_level.items())},
                by_regime={g: dict(wins=w, n=m, pnl=round(x, 4)) for g, (w, m, x) in by_regime.items()},
                independent_full=sum(1 for c in ch if c.level >= p["chain_len"] and independent_wins(c) >= p["chain_len"]),
                r_by_level={k: (_mean([s["r"] for s in res["steps"] if "pnl" in s and s["k"] == k and s["win"]]),
                                _mean([s["r"] for s in res["steps"] if "pnl" in s and s["k"] == k and not s["win"]]))
                            for k in sorted({s["k"] for s in res["steps"]})},
                mean_win_r=_mean([s["r"] for s in res["steps"] if "pnl" in s and s["win"]]),
                mean_loss_r=_mean([s["r"] for s in res["steps"] if "pnl" in s and not s["win"]]),
                reduced_steps=sum(1 for s in res["steps"] if s.get("reduced")))


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def evaluate(events, p, capital=1000.0, n_random=30, seed=7):
    """Variante + références (aléatoire, prend tout, risque fixe), glissement x1 et x2."""
    base = run_chains(events, p, capital)
    s1 = summarize(base, p, capital)
    s2 = summarize(run_chains(events, p, capital, slip_mult=2), p, capital)
    take = reference_variants(p)["prend_tout"]
    st = summarize(run_chains(events, take, capital), take, capital)
    usable = [e for e in events if (e.get("outcomes") or {}).get(gkey(p["stops"][0], p["r_mult"]), {}).get("complete")]
    rate = (sum(1 for e in usable if e.get("score", 0) >= p["gating"][0]) / len(usable)) if usable else 0.0
    rnd = [summarize(run_chains(events, p, capital, accept=random_accept(rate, seed + i)), p, capital)
           for i in range(n_random)]
    evs = sorted(x["ev_chain_R"] for x in rnd if x["ev_chain_R"] is not None)
    fulls = sorted(x["p_full"] for x in rnd if x["p_full"] is not None)
    return dict(variant=s1, slip2=s2, prend_tout=st, fixed_risk=fixed_risk(events, p, capital),
                fixed_risk_slip2=fixed_risk(events, p, capital, 2),
                aleatoire=dict(rate=rate, ev_chain_R_median=evs[len(evs) // 2] if evs else None,
                               ev_chain_R_p90=evs[int(0.9 * (len(evs) - 1))] if evs else None,
                               p_full_median=fulls[len(fulls) // 2] if fulls else None))


def beats_references(ev):
    """Une variante n'est bonne que si elle bat les références (à vérifier HORS échantillon)."""
    v, a, t = ev["variant"], ev["aleatoire"], ev["prend_tout"]
    if v["ev_chain_R"] is None:
        return False, "aucune chaîne terminée"
    why = []
    if a["ev_chain_R_p90"] is not None and v["ev_chain_R"] <= a["ev_chain_R_p90"]:
        why.append("ne bat pas 90 % des chaînes aléatoires")
    if t["ev_chain_R"] is not None and v["ev_chain_R"] <= t["ev_chain_R"]:
        why.append("ne bat pas « prends tout »")
    return not why, "; ".join(why) or "bat les références"


def chain_vs_fixed(ev, capital=1000.0):
    """L'enchaînement bat-il le risque fixe en espérance ET en drawdown ? (sur la même période)"""
    v, f = ev["variant"], ev["fixed_risk"]
    if v["ev_month"] is None or f["n"] == 0:
        return None
    months = v["n_chains"] / v["chains_per_month"] if v.get("chains_per_month") else None
    f_month = f["total"] / months if months else None
    better = f_month is not None and v["ev_month"] > f_month and v["max_dd"] <= f["max_dd"]
    return dict(chain_ev_month=v["ev_month"], fixed_ev_month=f_month, chain_dd=v["max_dd"], fixed_dd=f["max_dd"],
                verdict="l'enchaînement bat le risque fixe" if better else "l'enchaînement ne bat pas le risque fixe")


# ----------------------------------------------------------------- probabilités, test main chaude
def p_win_table(steps, prior_strength=5.0):
    """P(victoire | niveau, score) lissée (Beta centrée sur le taux global)."""
    done = [s for s in steps if "pnl" in s]
    if not done:
        return {}
    base = sum(s["win"] for s in done) / len(done)
    a0, b0 = prior_strength * base, prior_strength * (1 - base)
    out = {}
    for s in done:
        key = (s["k"], int(math.floor(s["score"] or 0)))
        w, n = out.get(key, (0, 0))
        out[key] = (w + s["win"], n + 1)
    return {f"{k}|{sc}": dict(wins=w, n=n, p=(w + a0) / (n + a0 + b0)) for (k, sc), (w, n) in sorted(out.items())}


def hot_hand(events, stop=0.05, r_mult=3, gate=-1e9, capital=1000.0):
    """Test « main chaude » : chaînes à paramètres constants (même stop, même objectif, même seuil
    à tous les niveaux) ; on compare P(victoire | 2 victoires avant dans la chaîne) à P(victoire |
    première étape). Test bilatéral de deux proportions ; effet retenu seulement si p < 0,05."""
    p = variant(name="main_chaude", stops=[stop] * 5, r_mult=r_mult, gating=[gate] * 5, max_open_chains=1)
    res = run_chains(events, p, capital)
    first = [s for s in res["steps"] if s["k"] == 1 and "pnl" in s]
    after2 = [s for s in res["steps"] if s["k"] >= 3 and "pnl" in s]
    n1, n2 = len(first), len(after2)
    if n1 < 10 or n2 < 10:
        return dict(n_first=n1, n_after2=n2, conclusion="inconclusif : pas assez d'étapes après 2 victoires")
    p1 = sum(s["win"] for s in first) / n1
    p2 = sum(s["win"] for s in after2) / n2
    pp = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(max(pp * (1 - pp) * (1 / n1 + 1 / n2), 1e-12))
    z = (p2 - p1) / se
    pval = 2 * discovery.norm_sf(abs(z))
    eff = pval < 0.05
    return dict(n_first=n1, n_after2=n2, p_first=p1, p_after2=p2, z=z, p_value=pval,
                conclusion=("effet de série mesuré" if eff else
                            "aucun effet de série mesuré : le niveau n'est pas une cause, seule la somme engagée change"))


def ev_per_chain(pw, p, win_r=None, loss_r=-1.0):
    """Espérance d'une chaîne en multiples du risque initial, pour une probabilité de victoire
    par étape pw (étapes indépendantes)."""
    wr = p["r_mult"] if win_r is None else win_r
    n = int(p["chain_len"])
    ev, house, acc, prob = 0.0, 1.0, 0.0, 1.0
    for k in range(1, n + 1):
        risk_k = 1.0 if k == 1 else house
        ev += prob * (1 - pw) * (acc + risk_k * loss_r)
        g = risk_k * wr
        acc += g
        house = g * p["reinvest"]
        prob *= pw
    return ev + prob * acc


def breakeven(p, win_r=None, loss_r=-1.0):
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ev_per_chain(mid, p, win_r, loss_r) > 0:
            hi = mid
        else:
            lo = mid
    pw = (lo + hi) / 2
    return dict(p_step=pw, p_full=pw ** int(p["chain_len"]))


def monte_carlo(p_levels, p, n_chains=10000, seed=1, chains_per_year=60, capital=1000.0, win_r=None,
                loss_r=-1.0, n_paths=500, r_levels=None):
    """10 000 chaînes à partir des taux observés par niveau (wins, n) avec incertitude (Beta).
    Sert à estimer la plage normale et le risque de drawdown, JAMAIS à prouver qu'une stratégie marche."""
    rng = random.Random(seed)
    n = int(p["chain_len"])
    wr = p["r_mult"] if win_r is None else win_r
    draws_full, fulls, bal = [], 0, []
    per = max(1, n_chains // 200)
    # a priori centré sur le taux observé tous niveaux confondus (force 5) : un niveau sans donnée
    # n'est PAS supposé gagner une fois sur deux
    tw = sum(w for w, m in p_levels.values())
    tn = sum(m for w, m in p_levels.values())
    pbar = (tw + 1) / (tn + 2)
    a0 = 5.0
    for _ in range(200):
        pk = [rng.betavariate(a0 * pbar + w, a0 * (1 - pbar) + (m - w))
              for w, m in (p_levels.get(k, (0, 0)) for k in range(1, n + 1))]
        draws_full.append(math.prod(pk))
        for _ in range(per):
            acc, risk_k = 0.0, 1.0
            ok = True
            for k in range(n):
                wr_k, lr_k = (r_levels or {}).get(k + 1, (None, None))
                wr_k = wr if wr_k is None else wr_k
                lr_k = loss_r if lr_k is None else lr_k
                if rng.random() < pk[k]:
                    g = risk_k * wr_k
                    acc += g
                    risk_k = g * p["reinvest"]
                else:
                    acc += risk_k * lr_k
                    ok = False
                    break
            fulls += ok
            bal.append(acc)
    draws_full.sort()
    risk1 = p["risk_pct"] * capital
    dd_hits = 0
    for _ in range(n_paths):
        eq = peak = capital
        mdd = 0.0
        for _ in range(chains_per_year):
            eq += rng.choice(bal) * risk1
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        dd_hits += mdd > 0.25
    return dict(n=len(bal), p_full=fulls / len(bal), p_full_lo80=draws_full[int(0.1 * 199)],
                p_full_hi80=draws_full[int(0.9 * 199)], ev_chain_R=sum(bal) / len(bal),
                p_dd_over_25=dd_hits / n_paths)


# ----------------------------------------------------------------- score et critères
def quality_score(base_score, crit, weights):
    """Score de qualité = score de la routine 1 (substitut tant qu'aucun critère n'est validé)
    + poids (selon le lift) des critères validés présents."""
    return float(base_score or 0) + sum(w for c, w in (weights or {}).items() if crit.get(c))


def criterion_search(events, stop, r_mult, min_n=30, q=0.10, seed=0):
    """Critères qui relèvent P(victoire) pour un couple (stop, R) : lift, IC 80 % (Newcombe),
    Benjamini-Hochberg, puis confirmation sur la période récente (30 %). Renvoie {critère: poids}."""
    rows = []
    for e in sorted(events, key=lambda e: e["ts"]):
        o = (e.get("outcomes") or {}).get(gkey(stop, r_mult))
        if o and o.get("complete"):
            rows.append(dict(crit=e.get("crit") or {}, win=o["win"]))
    if len(rows) < 2 * min_n:
        return {}, []
    cut = int(0.7 * len(rows))
    train, test = rows[:cut], rows[cut:]
    names = sorted({c for r in rows for c in r["crit"]})
    tests = []
    for c in names:
        a = _lift(train, c)
        if a is None or a["n_with"] < min_n * 0.7 or a["n_without"] < min_n * 0.7:
            continue
        tests.append(dict(criterion=c, **a))
    adj = discovery.benjamini_hochberg([t["p"] for t in tests]) if tests else []
    kept, report = {}, []
    for t, pa in zip(tests, adj):
        t["p_adj"] = pa
        v = _lift(test, t["criterion"])
        t["valid_lift"] = v["lift"] if v else None
        ok = pa < q and t["lo80"] > 0 and v is not None and v["lift"] > 0 and v["p"] < 0.20
        t["retenu"] = ok
        if ok:
            kept[t["criterion"]] = round(10 * t["lo80"], 2)
        report.append(t)
    return kept, report


def _lift(rows, c):
    w = [r["win"] for r in rows if r["crit"].get(c) is True]
    wo = [r["win"] for r in rows if r["crit"].get(c) is False]
    if len(w) < 5 or len(wo) < 5:
        return None
    p1, p0 = sum(w) / len(w), sum(wo) / len(wo)
    l1, h1 = wilson(sum(w), len(w))
    l0, h0 = wilson(sum(wo), len(wo))
    lift = p1 - p0
    lo = lift - math.sqrt((p1 - l1) ** 2 + (h0 - p0) ** 2)
    pp = (sum(w) + sum(wo)) / (len(w) + len(wo))
    se = math.sqrt(max(pp * (1 - pp) * (1 / len(w) + 1 / len(wo)), 1e-12))
    pval = discovery.norm_sf(lift / se)             # unilatéral : le critère relève P(victoire)
    return dict(n_with=len(w), n_without=len(wo), wr_with=p1, wr_without=p0, lift=lift, lo80=lo, p=pval)


def rescore(events, weights):
    return [dict(e, score=quality_score(e.get("base_score", e.get("score")), e.get("crit") or {}, weights))
            for e in events]


def ev_model(res, p, slip_mult=2):
    """Espérance d'une chaîne (en R du risque initial) MODÉLISÉE à partir des taux de victoire lissés
    par niveau (Beta(1,1)) et des R moyens gagnés / perdus observés : beaucoup moins bruitée que la
    moyenne des bilans, dominée par quelques chaînes complètes (~360 R chacune en 3R)."""
    key = "r2" if slip_mult == 2 else "r"
    n = int(p["chain_len"])
    stats = {k: [0, 0, [], []] for k in range(1, n + 1)}
    for s_ in res["steps"]:
        if "pnl" not in s_:
            continue
        a = stats[s_["k"]]
        a[0] += s_["win"]
        a[1] += 1
        (a[2] if s_["win"] else a[3]).append(s_[key])
    ev, acc, risk_k, prob = 0.0, 0.0, 1.0, 1.0
    pk = []
    for k in range(1, n + 1):
        w, m, rw, rl = stats[k]
        pw = (w + 1) / (m + 2)
        pk.append(pw)
        win_r = sum(rw) / len(rw) if rw else p["r_mult"]
        loss_r = sum(rl) / len(rl) if rl else -1.0
        ev += prob * (1 - pw) * (acc + risk_k * loss_r)
        g = risk_k * win_r
        acc += g
        risk_k = g * p["reinvest"]
        prob *= pw
    return dict(ev=ev + prob * acc, p_full=math.prod(pk), p_levels=pk, n_levels=[stats[k][1] for k in stats])


def propose_gating(events, p, capital=1000.0, q=0.10):
    """UNE modification de seuil à la fois (niveau k : ±1), choisie sur 70 % anciens, gardée seulement
    si, sur les 30 % récents, l'espérance modélisée (glissement x2) ET la probabilité d'aller à 5
    s'améliorent, et si la hausse du taux de victoire au niveau modifié est significative après
    correction des tests multiples (Benjamini-Hochberg)."""
    evs = sorted(events, key=lambda e: e["ts"])
    cut = int(0.7 * len(evs))
    train, test = evs[:cut], evs[cut:]
    if len(test) < 20:
        return dict(change=None, reason="pas assez d'événements récents pour valider")
    cur_tr = ev_model(run_chains(train, p, capital, slip_mult=2), p)
    cur_te_res = run_chains(test, p, capital, slip_mult=2)
    cur_te = ev_model(cur_te_res, p)
    cands = []
    for k in range(int(p["chain_len"])):
        for d in (+1, -1):
            g = list(p["gating"])
            g[k] += d
            q_ = dict(p, gating=g)
            tr = ev_model(run_chains(train, q_, capital, slip_mult=2), q_)
            if tr["ev"] <= cur_tr["ev"]:
                continue
            te_res = run_chains(test, q_, capital, slip_mult=2)
            te = ev_model(te_res, q_)
            pv = _level_p(te_res, cur_te_res, k + 1)
            cands.append(dict(level=k + 1, delta=d, gating=g, train_ev=tr["ev"], test_ev=te["ev"],
                              test_p_full=te["p_full"], cur_test_ev=cur_te["ev"], cur_test_p_full=cur_te["p_full"], p=pv))
    if not cands:
        return dict(change=None, reason="aucune modification n'améliore l'espérance sur les données anciennes")
    adj = discovery.benjamini_hochberg([c["p"] for c in cands])
    for c, a in zip(cands, adj):
        c["p_adj"] = a
    ok = [c for c in cands if c["test_ev"] > c["cur_test_ev"] and c["test_p_full"] >= c["cur_test_p_full"]
          and c["p_adj"] < q]
    if not ok:
        return dict(change=None, candidates=cands,
                    reason="aucune modification ne tient hors échantillon après correction des tests multiples")
    best = max(ok, key=lambda c: c["test_ev"])
    return dict(change=best, candidates=cands, reason=f"niveau {best['level']} : seuil {p['gating'][best['level'] - 1]} → "
                                                       f"{best['gating'][best['level'] - 1]}")


def _level_p(res_a, res_b, k):
    """p unilatéral : le taux de victoire au niveau k est plus haut dans res_a que dans res_b."""
    a = [s_["win"] for s_ in res_a["steps"] if s_["k"] == k and "pnl" in s_]
    b = [s_["win"] for s_ in res_b["steps"] if s_["k"] == k and "pnl" in s_]
    if len(a) < 5 or len(b) < 5:
        return 1.0
    pa, pb = sum(a) / len(a), sum(b) / len(b)
    pp = (sum(a) + sum(b)) / (len(a) + len(b))
    se = math.sqrt(max(pp * (1 - pp) * (1 / len(a) + 1 / len(b)), 1e-12))
    return discovery.norm_sf((pa - pb) / se)


def _boot_p(a, b, n_boot, seed):
    """p unilatéral (bootstrap) que la moyenne de a dépasse celle de b."""
    if len(a) < 5 or len(b) < 5:
        return 1.0
    rng = random.Random(seed)
    worse = 0
    for _ in range(n_boot):
        ma = sum(rng.choice(a) for _ in a) / len(a)
        mb = sum(rng.choice(b) for _ in b) / len(b)
        worse += ma <= mb
    return (worse + 1) / (n_boot + 1)


def assess(ev, mc, p, n_live_chains=0, n_indep_events=0, min_n=30):
    """Statut proposé selon les règles de promotion (comme les autres stratégies)."""
    v, s2 = ev["variant"], ev["slip2"]
    be = breakeven(p)
    if max(n_live_chains, n_indep_events) < min_n:
        return dict(status="inconclusif", missing=min_n - max(n_live_chains, n_indep_events), breakeven=be,
                    reason=f"il manque {min_n - max(n_live_chains, n_indep_events)} chaîne(s) ou événement(s) indépendant(s)")
    reasons = []
    if s2["ev_chain_R"] is None or s2["ev_chain_R"] <= 0:
        reasons.append("espérance <= 0 avec glissement x2")
    if v["p_full_lo80"] <= be["p_full"]:
        reasons.append(f"borne basse P(5) {v['p_full_lo80']:.2%} <= équilibre {be['p_full']:.2%}")
    if mc and mc["p_dd_over_25"] >= 0.10:
        reasons.append(f"Monte Carlo : P(drawdown > 25 %) = {mc['p_dd_over_25']:.0%}")
    good, why = beats_references(ev)
    if not good:
        reasons.append(why)
    regimes = {g: x for g, x in v["by_regime"].items() if x["n"] >= 10}
    pos = [g for g, x in regimes.items() if x["pnl"] > 0]
    if reasons:
        if pos and len(pos) < len(regimes):
            return dict(status="restreint", breakeven=be, reason="marche seulement si " + ", ".join(pos) + " ; " + "; ".join(reasons))
        return dict(status="ombre", breakeven=be, reason="; ".join(reasons))
    return dict(status="challenger", breakeven=be, reason="passe les règles de promotion")


def verdict(results, n_indep_chains):
    """Verdict honnête sur l'ensemble des variantes."""
    passing = [r for r in results if r["assess"]["status"] in ("challenger", "champion")]
    if passing:
        return "au moins une variante a un avantage mesuré (à confirmer en papier réel)"
    if n_indep_chains >= 100:
        return "impossible avec ces critères : aucune variante ne passe la borne basse sur 100 chaînes indépendantes"
    return f"inconclusif : la chaîne de 5 n'a pas d'avantage mesuré pour l'instant ({n_indep_chains}/100 chaînes indépendantes)"
