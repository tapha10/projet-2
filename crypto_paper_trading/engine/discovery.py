"""Addendum 2ter — découverte des critères d'entrée et décisions de palier.

Entrée : une liste d'ÉVÉNEMENTS INDÉPENDANTS (voir features.cluster_events), chacun avec
  ts, pair, criteria {nom: True/False/None}, outcomes {P1..P4: {win, r, r_slip2}}.
Sortie : statistiques par critère (et paire de critères) et par palier, critères
retenus (`entry_filters`), décisions de déblocage / ombre / blocage.

Prudence statistique : on teste beaucoup de critères ; la correction de
Benjamini-Hochberg et la validation walk-forward évitent de retenir le hasard.
"""
from __future__ import annotations

import itertools
import math

from . import tiers

Z80 = 1.2816
RETAIN = dict(min_with=30, min_lift=0.10, fdr_q=0.10, train_frac=0.70)


def norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def lift_stats(events, crit, tier):
    """Taux de réussite avec / sans le critère pour un palier."""
    w, wo = [], []
    for e in events:
        c = crit(e) if callable(crit) else e["criteria"].get(crit)
        o = (e.get("outcomes") or {}).get(tier)
        if c is None or o is None or o.get("win") is None:
            continue
        (w if c else wo).append(1 if o["win"] else 0)
    n1, n0 = len(w), len(wo)
    if n1 == 0 or n0 == 0:
        return dict(n_with=n1, n_without=n0, wr_with=None, wr_without=None, lift=None, lo80=None, hi80=None, p=1.0)
    p1, p0 = sum(w) / n1, sum(wo) / n0
    l1, u1 = tiers.wilson(sum(w), n1, Z80)
    l0, u0 = tiers.wilson(sum(wo), n0, Z80)
    d = p1 - p0
    # Newcombe (méthode hybride de Wilson) pour l'écart de deux proportions
    lo = d - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)
    pp = (sum(w) + sum(wo)) / (n1 + n0)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n0))
    p = norm_sf(d / se) if se > 0 else (0.0 if d > 0 else 1.0)   # unilatéral : lift > 0
    return dict(n_with=n1, n_without=n0, wr_with=p1, wr_without=p0, lift=d, lo80=lo, hi80=hi, p=p)


def benjamini_hochberg(pvals):
    """p-valeurs ajustées (BH), même ordre que l'entrée."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        adj[i] = min(1.0, prev)
    return adj


def criteria_names(events):
    names = set()
    for e in events:
        names.update(k for k, v in e["criteria"].items())
    return sorted(names)


def make_pair(a, b):
    def f(e):
        x, y = e["criteria"].get(a), e["criteria"].get(b)
        if x is None or y is None:
            return None
        return x and y
    return f


def analyse(events, tiers_list=("P1", "P2", "P3", "P4"), with_pairs=True, names=None):
    """Teste chaque critère et chaque paire, par palier. Renvoie la liste des tests."""
    events = sorted(events, key=lambda e: e["ts"])
    names = names or criteria_names(events)
    tests = []
    cut = int(round(len(events) * RETAIN["train_frac"]))
    valid = events[cut:]
    cands = [(n, n) for n in names]
    if with_pairs:
        cands += [(f"{a} & {b}", make_pair(a, b)) for a, b in itertools.combinations(names, 2)]
    for tier in tiers_list:
        for label, crit in cands:
            s = lift_stats(events, crit, tier)
            if s["lift"] is None:
                continue
            v = lift_stats(valid, crit, tier)
            s.update(tier=tier, criterion=label, valid_lift=v["lift"], valid_n_with=v["n_with"])
            tests.append(s)
    adj = benjamini_hochberg([t["p"] for t in tests]) if tests else []
    for t, a in zip(tests, adj):
        t["p_adj"] = a
        t["retained"] = retained(t)
        t["status"] = "retenu" if t["retained"] else ("hypothèse" if t["n_with"] < RETAIN["min_with"] else "rejeté")
    return tests


def retained(t):
    return (t["n_with"] >= RETAIN["min_with"] and t["lift"] is not None and t["lift"] >= RETAIN["min_lift"]
            and t["lo80"] is not None and t["lo80"] > 0 and t["p_adj"] <= RETAIN["fdr_q"]
            and t["valid_lift"] is not None and t["valid_lift"] > 0)


def filter_fn(label):
    if " & " in label:
        a, b = label.split(" & ")
        return make_pair(a, b)
    return lambda e: e["criteria"].get(label)


def decide_tiers(events, tier_state, tests, now_ts, read_only=False):
    """Décisions de déblocage / montée de risque / retour en ombre pour P2-P4.
    tier_state : {tier: {status, risk_pct, since_ts, events_at_step}}. Renvoie (nouvel état, décisions)."""
    events = sorted(events, key=lambda e: e["ts"])
    cut = int(round(len(events) * RETAIN["train_frac"]))
    oos = events[cut:]
    new_state = {k: dict(v) for k, v in tier_state.items()}
    decisions = []
    for tier in ("P2", "P3", "P4"):
        st = new_state.setdefault(tier, {"status": "shadow", "risk_pct": 0.0})
        best = sorted([t for t in tests if t["tier"] == tier and t["retained"]], key=lambda t: -t["lift"])
        flt = filter_fn(best[0]["criterion"]) if best else None
        sel = [e for e in oos if (flt is None or flt(e)) and (e.get("outcomes") or {}).get(tier)]
        outs = [e["outcomes"][tier] for e in sel if e["outcomes"][tier].get("complete", True)]
        if st["status"] == "unlocked":
            recent = [e["outcomes"][tier] for e in events if (flt is None or flt(e)) and (e.get("outcomes") or {}).get(tier)]
            dem, det = tiers.evaluate_demote(tier, recent)
            if dem:
                decisions.append(dict(tier=tier, action="demote", detail=det,
                                      why=f"borne haute 80 % {det['hi80']:.3f} < équilibre {det['breakeven']:.3f} sur 40 événements"))
                if not read_only:
                    new_state[tier] = {"status": "shadow", "risk_pct": 0.0, "since_ts": now_ts}
                continue
            weeks = (now_ts - st.get("since_ts", now_ts)) / (7 * 86400)
            new_ev = len(events) - st.get("events_at_step", len(events))
            nxt = min(tiers.next_risk_step(st["risk_pct"], weeks, new_ev), tiers.RISK_CAP[tier])
            if nxt > st["risk_pct"]:
                ok, det = tiers.evaluate_unlock(tier, outs, st, nxt)
                if ok:
                    decisions.append(dict(tier=tier, action="risk_up", from_=st["risk_pct"], to=nxt, detail=det))
                    if not read_only:
                        st.update(risk_pct=nxt, since_ts=now_ts, events_at_step=len(events))
            continue
        if not best:
            decisions.append(dict(tier=tier, action="stay_shadow", why="aucun critère retenu pour ce palier",
                                  detail=dict(n=len(outs))))
            continue
        ok, det = tiers.evaluate_unlock(tier, outs, st, tiers.RISK_STEPS[0])
        det["filter"] = best[0]["criterion"]
        if ok:
            decisions.append(dict(tier=tier, action="unlock", to=tiers.RISK_STEPS[0], detail=det))
            if not read_only:
                new_state[tier] = {"status": "unlocked", "risk_pct": tiers.RISK_STEPS[0], "since_ts": now_ts,
                                   "events_at_step": len(events), "filter": best[0]["criterion"]}
        else:
            decisions.append(dict(tier=tier, action="stay_shadow", why="; ".join(det["reasons"]), detail=det))
    return new_state, decisions


def p4_rare_events(signals, threshold=2.5):
    """Fréquence des hausses > 250 % (10 jours) sur l'univers surveillé et proportion où
    un stop proche (<= 6 %) n'aurait pas sauté avant le pic."""
    with_outcome = [s for s in signals if s.get("outcome_max_gain_pct") is not None]
    big = [s for s in with_outcome if float(s["outcome_max_gain_pct"]) >= threshold]
    caught = [s for s in big if s.get("outcome_max_dd_pct") is not None and float(s["outcome_max_dd_pct"]) > -0.06]
    n = len(with_outcome)
    return dict(n_signals=n, n_big=len(big), freq=(len(big) / n) if n else None, n_catchable=len(caught),
                verdict="inconclusif" if len(big) < 5 else ("possible" if caught else "pas de positionnement possible"))


def compare_splits(rows, current="50/30/20"):
    """rows : [{ts, split_r: {nom: R}}]. Compare les découpes sur la partie hors
    apprentissage (30 % récents). Change seulement si IC bootstrap de la différence > 0."""
    from . import stats
    rows = sorted(rows, key=lambda r: r["ts"])
    cut = int(round(len(rows) * RETAIN["train_frac"]))
    test = rows[cut:]
    out = {}
    for name in tiers.SPLITS:
        rs = [r["split_r"][name] for r in test if r["split_r"].get(name) is not None]
        out[name] = dict(n=len(rs), mean_r=(sum(rs) / len(rs)) if rs else None)
    best = max((k for k in out if out[k]["mean_r"] is not None), key=lambda k: out[k]["mean_r"], default=None)
    change = None
    if best and best != current:
        d = [r["split_r"][best] - r["split_r"][current] for r in test
             if r["split_r"].get(best) is not None and r["split_r"].get(current) is not None]
        ci = stats.bootstrap_mean_ci(d) if len(d) >= 2 else None
        if ci and ci["lo"] > 0 and len(d) >= 30:
            change = dict(to=best, ci=ci)
    return dict(by_split=out, best=best, change=change, n_test=len(test))
