"""Routine 7 — chaînes de victoires (PAPIER UNIQUEMENT). Ligne de commande et logique.

Les fonctions `daily`, `decide`, `weekly` sont pures : elles prennent les données de la base
(`select paper_chain_data();`) et renvoient une liste d'« actions » ; `to_sql` les traduit en SQL
exécuté par la routine (et `dryrun7` les rejoue en mémoire pour le cycle sec de 14 jours).

python3 -m engine.cli7 decide  --data chain.json --out decide.sql
python3 -m engine.cli7 daily   --data chain.json --out daily.sql [--attempt 2]
python3 -m engine.cli7 weekly  --data chain.json --history docs/chain_history_events.json --out weekly.sql
python3 -m engine.cli7 history --out docs/chain_history_events.json [--days 150 --pairs 80]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import chains as C
from . import market, stats
from .sqlgen import load_json_loose, q, qts

PARIS = ZoneInfo("Europe/Paris")
DAY = 86400


def unwrap(d):
    """Accepte le résultat brut de execute_sql ([{"paper_chain_data": {...}}]) ou l'objet."""
    if isinstance(d, list) and d:
        d = d[0]
    if isinstance(d, dict) and len(d) == 1 and isinstance(next(iter(d.values())), dict):
        d = next(iter(d.values()))
    return d


def cfg(data, key, default=None):
    v = (data.get("config") or {}).get(key, default)
    return v if v is not None else default


def ts_of(x):
    return stats.parse_ts(x) if isinstance(x, str) else (x or 0)


def readonly(data, now):
    ro = cfg(data, "chain_readonly_until")
    return bool(ro) and now < ts_of(ro)


def params_of(row, gating_rows):
    p = C.variant(**{k: v for k, v in (row.get("params") or {}).items() if k in C.BASE})
    g = {int(r["k"]): float(r["min_score"]) for r in gating_rows if r["params_id"] == row["id"]}
    if g:
        p["gating"] = [g.get(k, p["gating"][k - 1]) for k in range(1, int(p["chain_len"]) + 1)]
    p["params_id"] = row["id"]
    return p


def all_params(data):
    return [(row, params_of(row, data.get("gating", []))) for row in data.get("params", [])
            if row.get("status") not in ("retiré",)]


def champion(data):
    for row, p in all_params(data):
        if row.get("status") == "champion":
            return row, p
    return None, None


def criteria_weights(data):
    """Poids des critères validés par la routine 6 (entry_filters retenus), selon le lift (borne basse)."""
    w = {}
    for f in data.get("entry_filters", []):
        lo = f.get("lo80")
        if lo is not None and float(lo) > 0:
            w[f["criterion"]] = max(w.get(f["criterion"], 0.0), round(10 * float(lo), 2))
    return w


def preconditions(data, now):
    """La routine 7 (05:45) ne tourne que si les routines 5 et 6 ont fini avec succès aujourd'hui."""
    day = datetime.fromtimestamp(now, PARIS).date()
    ok = {}
    for row in data.get("routine_log", []):
        if row["routine"] not in ("routine5", "routine6"):
            continue
        d = datetime.fromtimestamp(ts_of(row["created_at"]), PARIS).date()
        st = (row.get("change") or {}).get("status")
        if d == day and st == "ok":
            ok[row["routine"]] = True
    missing = [r for r in ("routine5", "routine6") if not ok.get(r)]
    return (not missing), ("routines terminées" if not missing else "en attente de " + " et ".join(missing))


# ----------------------------------------------------------------- événements papier réel / ombre
def live_events(data, fetch, now, weights=None):
    """Signaux enregistrés (routines 1 et 1b) -> événements avec résultats rejoués pour la grille."""
    weights = criteria_weights(data) if weights is None else weights
    btc = []
    try:
        btc = fetch("BTCUSDT", "1d", now - 80 * DAY, now)
    except Exception:
        pass
    evs = []
    for s in data.get("signals", []):
        if s.get("is_reference") or not s.get("price_at_detection"):
            continue
        det = ts_of(s["detected_at"])
        try:
            rows = fetch(s["pair"], "1h", det - 3600, min(now, det + 11 * DAY))
        except Exception:
            continue
        rows = [r for r in rows if r["t"] >= det - 1 and r["t"] + 3600 <= now]
        if not rows:
            continue
        entry = float(s["price_at_detection"])
        crit = {k: v for k, v in (s.get("criteria") or {}).items() if v is not None}
        evs.append(dict(id=s["id"], ts=det, pair=s["pair"], base_score=float(s.get("score") or 0),
                        score=C.quality_score(s.get("score"), crit, weights), crit=crit,
                        outcomes=C.event_outcomes(entry, rows, det), vol24h=_f(s.get("quote_vol_24h")),
                        regime=C.btc_regime(btc, det) if btc else "inconnu", decision=s.get("decision"),
                        source="shadow"))
    return evs


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- 14:20 : décisions papier réel
def decide(data, price_fn, now, slip=0.001):
    acts = []
    row, p = champion(data)
    if not row:
        return [dict(kind="decision", action="non_exécutée", logic="aucune variante championne")]
    ro = readonly(data, now)
    gdd = float(data.get("global_drawdown") or 0)
    if gdd >= C.HARD["drawdown_halt"]:
        return [dict(kind="decision", params_id=row["id"], action="suspendue", read_only=ro,
                     logic=f"drawdown global {gdd:.1%} >= 15 % : routine 7 suspendue (GUARDRAILS 10)",
                     numbers=dict(global_drawdown=gdd))]
    eq = float(data.get("k_equity") or 1000.0)
    weights = criteria_weights(data)
    open_k = data.get("open_k", [])
    busy_pairs = {x["pair"] for x in open_k}
    busy_chains = {x.get("chain_id") for x in open_k}
    used = {s.get("signal_id") for s in data.get("steps", [])}
    live = [c for c in data.get("chains", []) if c["source"] == "live_paper" and c["state"] == "ouverte"
            and c["params_id"] == row["id"]]
    slots = [dict(c) for c in live]
    for i in range(max(0, p["max_open_chains"] - len(live))):
        slots.append(dict(id=None, new_index=i, level=0, gate_level=0, house=0.0))
    explore = chain_exploration(data, now)
    cands = []
    for s in data.get("signals", []):
        if s.get("is_reference") or s["id"] in used or now - ts_of(s["detected_at"]) > DAY:
            continue
        ok = s.get("decision") == "enter"
        # exploration : signal refusé seulement pour son score (aucune alerte), seuil du niveau 1 moins 1
        exp = (explore and s.get("decision") == "skip" and not s.get("alerts")
               and str(s.get("decision_reason") or "").startswith("score"))
        if not (ok or exp):
            continue
        crit = {k: v for k, v in (s.get("criteria") or {}).items() if v is not None}
        cands.append(dict(s, qscore=C.quality_score(s.get("score"), crit, weights), explore=not ok))
    cands.sort(key=lambda s: (s["explore"], -s["qscore"]))
    explored = False
    for c in slots:
        if c.get("id") in busy_chains:
            continue
        k = int(c.get("level") or 0) + 1
        gk = min(int(c.get("gate_level") or 0) + 1, int(p["chain_len"]))
        gate = p["gating"][gk - 1]
        # option « sécuriser » : délai dépassé sans signal assez bon -> gain verrouillé
        if p["option"] == "secure" and k > 1 and p.get("wait_days"):
            idle = now - ts_of(_last_close(data, c["id"]) or c.get("started_at") or now)
            if idle > p["wait_days"] * DAY:
                acts.append(dict(kind="secure_chain", chain_id=c["id"], read_only=ro, params_id=row["id"],
                                 logic=f"aucun signal de score >= {gate} en {p['wait_days']} j : gain verrouillé au niveau {k - 1}"))
                continue
        pick, why_not = None, []
        for s in cands:
            if s["pair"] in busy_pairs:
                why_not.append(f"{s['pair']} déjà ouvert")
                continue
            if s["explore"]:
                if k > 1 or explored or s["qscore"] < gate - 1:
                    continue
                pick = s
                explored = True
                break
            if s["qscore"] < gate:
                why_not.append(f"{s['pair']} score {s['qscore']:.1f} < seuil {gate:g}")
                continue
            pick = s
            break
        if not pick:
            acts.append(dict(kind="decision", chain_id=c.get("id"), params_id=row["id"], action="attendre", read_only=ro,
                             logic=f"niveau {k} : aucun signal accepté du jour avec un score >= {gate:g}",
                             numbers=dict(level=k, gate=gate, rejected=why_not[:8], n_candidates=len(cands))))
            continue
        try:
            last = price_fn(pick["pair"])
        except Exception as e:
            acts.append(dict(kind="decision", chain_id=c.get("id"), params_id=row["id"], action="attendre", read_only=ro,
                             logic=f"prix indisponible pour {pick['pair']} : {str(e)[:80]}"))
            continue
        entry = last * (1 + slip)
        det_px = float(pick.get("price_at_detection") or entry)
        stop_pct = p["stops"][k - 1]
        if entry > det_px * 1.05:
            acts.append(dict(kind="decision", chain_id=c.get("id"), params_id=row["id"], action="attendre", read_only=ro,
                             logic=f"{pick['pair']} : déjà +{entry / det_px - 1:.1%} depuis la détection (> 5 %), entrée trop tardive"))
            continue
        risk = (eq * p["risk_pct"]) if k == 1 or float(c.get("house") or 0) <= 0 else float(c["house"])
        if pick.get("explore"):
            risk *= 0.5                                   # exploration : demi-risque
        plan = C.step_size(risk, stop_pct, p["r_mult"], eq, min(p["max_leverage"], C.HARD["max_leverage_live"]),
                           _f(pick.get("quote_vol_24h")), slip)
        if plan.get("refused"):
            acts.append(dict(kind="decision", chain_id=c.get("id"), params_id=row["id"], action="attendre", read_only=ro,
                             logic=f"{pick['pair']} refusé : {plan['refused']}"))
            continue
        lev = max(1.0, math.ceil(plan["size"] / eq * 100) / 100)
        step = dict(kind="open_step", chain_id=c.get("id"), new_chain=c.get("id") is None, params_id=row["id"],
                    k=k, signal_id=pick["id"], pair=pick["pair"], score=pick["qscore"], gate=gate, entry=entry,
                    stop=entry * (1 - stop_pct), target=entry * (1 + stop_pct * p["r_mult"]), stop_pct=stop_pct,
                    r_mult=p["r_mult"], risk=plan["risk"], size=plan["size"], leverage=lev,
                    vol_24h=_f(pick.get("quote_vol_24h")), reduced=plan["reason"], read_only=ro,
                    logic=(("EXPLORATION (aucune étape depuis 7 j, demi-risque) — " if pick.get("explore") else "")
                           + f"niveau {k} : {pick['pair']} score {pick['qscore']:.1f} "
                           + (f">= seuil {gate:g} - 1" if pick.get("explore") else f">= seuil {gate:g}") + " ; risque "
                           f"{plan['risk']:.2f} ({'1 % du capital' if k == 1 else 'gain de l étape précédente'}), stop "
                           f"{stop_pct:.0%}, objectif +{stop_pct * p['r_mult']:.0%} ({p['r_mult']}R)"
                           + (f" ; risque réduit ({plan['reason']})" if plan["reason"] else "")))
        acts.append(step)
        busy_pairs.add(pick["pair"])
        cands.remove(pick)
    return acts


def chain_exploration(data, now, days=7):
    """Anti-cercle vicieux : aucune étape de chaîne décidée depuis 7 jours (ou depuis la fin de la
    lecture seule) -> une étape 1 d'exploration autorisée, demi-risque, seuil du niveau 1 moins 1."""
    ro = cfg(data, "chain_readonly_until")
    ref = ts_of(ro) if ro else 0
    for st in data.get("steps", []):
        if st.get("decided_at"):
            ref = max(ref, ts_of(st["decided_at"]))
    return bool(ref) and now - ref >= days * DAY


def _last_close(data, chain_id):
    xs = [s.get("closed_at") for s in data.get("steps", []) if s["chain_id"] == chain_id and s.get("closed_at")]
    return max(xs) if xs else None


# ----------------------------------------------------------------- 05:45 : mise à jour et simulations
def daily(data, fetch, now, attempt=1, hist_p_levels=None):
    ok, why = preconditions(data, now)
    if not ok:
        if attempt == 1:
            return [dict(kind="wait", logic=why)]
        return [dict(kind="decision", action="non_exécutée", logic=f"routine 7 non exécutée : {why} (après 2 essais)"),
                dict(kind="log", status="skipped", rationale=f"Routine 7 (05:45) non exécutée : {why}.")]
    acts = []
    evs = live_events(data, fetch, now)
    prev = {(s["variant"], s["source"]): s for s in data.get("stats", [])}
    hist_levels = hist_p_levels or _hist_levels(data)
    for row, p in all_params(data):
        res = C.run_chains(evs, p, source="shadow")
        s1 = C.summarize(res, p)
        s2 = C.summarize(C.run_chains(evs, p, slip_mult=2), p)
        acts.append(dict(kind="sim_run", source="shadow", params_id=row["id"], variant=p["name"], s=s1, s2=s2,
                         period=_period(evs)))
        lv = hist_levels.get(p["name"]) or {k: (v["wins"], v["n"]) for k, v in s1["p_win_by_level"].items()}
        mc = C.monte_carlo({int(k): tuple(v) for k, v in lv.items()}, p, n_chains=10000, seed=row["id"],
                           win_r=s1.get("mean_win_r"), loss_r=-1.0, r_levels=s1.get("r_by_level"))
        acts.append(dict(kind="sim_run", source="monte_carlo", params_id=row["id"], variant=p["name"], mc=mc))
        pl = {k: v["p"] for k, v in s1["p_win_by_level"].items()}
        old = prev.get((p["name"], "shadow"))
        trend = "→"
        if old and old.get("p_full") is not None and s1["p_full"] is not None:
            trend = "↗" if s1["p_full"] > float(old["p_full"]) + 1e-9 else ("↘" if s1["p_full"] < float(old["p_full"]) - 1e-9 else "→")
        acts.append(dict(kind="stats", params_id=row["id"], variant=p["name"], source="shadow", n_done=s1["n_chains"],
                         reach=s1["reach"], p_levels=pl, p_full=s1["p_full"], trend=trend,
                         detail=dict(p_table=C.p_win_table(res["steps"]), mc_p_full=mc["p_full"],
                                     mc_lo80=mc["p_full_lo80"], mc_hi80=mc["p_full_hi80"])))
    acts.append(dict(kind="decision", action="statistiques", read_only=readonly(data, now),
                     logic=f"Mise à jour 05:45 : {len(evs)} signal(aux) rejoué(s) en ombre pour {len(all_params(data))} variantes ; "
                           "Monte Carlo 10 000 chaînes par variante (estimation de plage, jamais une preuve).",
                     numbers=dict(n_events=len(evs))))
    acts.append(dict(kind="log", status="ok", rationale=f"Routine 7 (05:45) : {len(evs)} événements, ombre + Monte Carlo."))
    return acts


def _hist_levels(data):
    """Taux par niveau du dernier rejeu historique de chaque variante (pour le Monte Carlo)."""
    out = {}
    for r in data.get("sim_runs", []):
        if r.get("source") == "replay_history" and (r.get("detail") or {}).get("p_win_by_level"):
            out[r["variant"]] = {int(k): (v["wins"], v["n"]) for k, v in r["detail"]["p_win_by_level"].items()}
    return out


def _period(evs):
    if not evs:
        return (None, None)
    return (min(e["ts"] for e in evs), max(e["ts"] for e in evs))


# ----------------------------------------------------------------- dimanche 11:30 : optimisation
def weekly(data, hist, now, live_evs=None):
    ro = readonly(data, now)
    hevs = [e for e in hist.get("events", [])]
    for e in hevs:
        e.setdefault("score", e.get("base_score", 0))
    evs = sorted(hevs + list(live_evs or []), key=lambda e: e["ts"])
    acts = []
    if len(evs) < 20:
        return [dict(kind="decision", action="inconclusif", read_only=ro,
                     logic=f"seulement {len(evs)} événements : rien à optimiser")]
    cut = int(0.7 * len(evs))
    test = evs[cut:]
    live_done = sum(1 for c in data.get("chains", []) if c["source"] == "live_paper" and c["state"] != "ouverte")
    results = []
    for row, p in all_params(data):
        ev = C.evaluate(evs, p)
        ev_test = C.evaluate(test, p, n_random=20)
        good_test, why_test = C.beats_references(ev_test)
        lv = {k: (v["wins"], v["n"]) for k, v in ev["variant"]["p_win_by_level"].items()}
        mc = C.monte_carlo(lv, p, n_chains=10000, seed=row["id"],
                           chains_per_year=max(12, int(12 * (ev["variant"]["chains_per_month"] or 1))),
                           win_r=ev["slip2"].get("mean_win_r"), loss_r=-1.0, r_levels=ev["slip2"].get("r_by_level"))
        res = C.run_chains(evs, p)
        indep = len({s.get("cluster") or (s["pair"], int(s["ts"] // (10 * DAY))) for s in res["steps"]
                     if s["k"] >= 2 and "pnl" in s})
        a = C.assess(ev, mc, p, n_live_chains=live_done, n_indep_events=indep)
        if a["status"] in ("challenger",) and not good_test:
            a = dict(a, status="ombre", reason=f"hors échantillon : {why_test}")
        cvf = C.chain_vs_fixed(ev)
        results.append(dict(name=p["name"], row=row, ev=ev, test=ev_test, assess=a, mc=mc, indep=indep, vs_fixed=cvf))
        acts.append(dict(kind="sim_run", source="replay_history", params_id=row["id"], variant=p["name"],
                         s=ev["variant"], s2=ev["slip2"], period=_period(evs),
                         extra=dict(references=dict(aleatoire=ev["aleatoire"], prend_tout=_brief(ev["prend_tout"]),
                                                    risque_fixe=ev["fixed_risk"], risque_fixe_slip2=ev["fixed_risk_slip2"]),
                                    test_30pc=dict(variant=_brief(ev_test["variant"]), aleatoire=ev_test["aleatoire"],
                                                   prend_tout=_brief(ev_test["prend_tout"]), bat_references=good_test,
                                                   pourquoi=why_test),
                                    assess=a, vs_fixed=cvf, independent_events=indep,
                                    n_events=len(evs), n_hist=len(hevs))))
        acts.append(dict(kind="sim_run", source="monte_carlo", params_id=row["id"], variant=p["name"], mc=mc))
        if row.get("status") != "champion":
            acts.append(dict(kind="params_status", params_id=row["id"], status=a["status"], reason=a["reason"][:400]))
        else:
            acts.append(dict(kind="params_status", params_id=row["id"], status="champion",
                             reason=("variante de départ de l'utilisateur ; mesure : " + a["reason"])[:400]))
    hh = C.hot_hand(evs)
    crow, cp = champion(data)
    kept, rep = C.criterion_search(evs, 0.05, 3)
    kept10, rep10 = C.criterion_search(evs, 0.10, 3)
    weights = dict(kept10)
    weights.update(kept)
    prop = C.propose_gating(C.rescore(evs, weights), cp) if cp else dict(change=None, reason="pas de champion")
    if prop.get("change") and not ro:
        ch = prop["change"]
        acts.append(dict(kind="gating_change", params_id=crow["id"], level=ch["level"],
                         old=cp["gating"][ch["level"] - 1], new=ch["gating"][ch["level"] - 1],
                         logic=prop["reason"], numbers=_clean(ch)))
    acts.append(dict(kind="decision", action="proposition_seuil" if prop.get("change") else "seuils_inchangés",
                     params_id=crow["id"] if crow else None, read_only=ro or not prop.get("change"),
                     logic=prop["reason"] + (" (lecture seule : non appliqué)" if ro and prop.get("change") else ""),
                     numbers=dict(criteres_retenus=weights, change=_clean(prop.get("change")))))
    from .chain_history import target_calibration
    calib = target_calibration([e for e in evs if e.get("mfe10") is not None])
    verdict = C.verdict(results, max(r["indep"] for r in results) if results else 0)
    acts.append(dict(kind="decision", action="synthèse_hebdo", read_only=ro, logic=verdict,
                     numbers=dict(main_chaude=hh, calibration_objectif=calib, n_events=len(evs), n_hist=len(hevs),
                                  meilleures=[dict(nom=r["name"], ev_R=r["ev"]["variant"]["ev_chain_R"],
                                                   p5=r["ev"]["variant"]["p_full"], statut=r["assess"]["status"])
                                              for r in sorted(results, key=lambda r: -(r["ev"]["slip2"]["ev_chain_R"] or -1e9))[:5]],
                                  criteres=[dict(c=t["criterion"], lift=t["lift"], p_adj=t.get("p_adj"),
                                                 retenu=t.get("retenu")) for t in (rep + rep10)][:20])))
    acts.append(dict(kind="log", status="ok", rationale=f"Routine 7 (dimanche) : {len(results)} variantes, {len(evs)} événements ; {verdict}"))
    return acts


def _brief(s):
    return {k: s.get(k) for k in ("n_chains", "full", "p_full", "ev_chain_R", "max_dd", "chains_per_month")}


def _clean(x):
    return json.loads(json.dumps(x, default=str)) if x is not None else None


# ----------------------------------------------------------------- SQL
def to_sql(acts, now=None):
    out = []
    for a in acts:
        k = a["kind"]
        if k == "wait":
            out.append(f"select {q('ATTENTE : ' + a['logic'])} as routine7;")
        elif k == "decision":
            out.append("insert into chain_decisions(chain_id, params_id, action, read_only, logic, numbers) values ("
                       f"{q(a.get('chain_id'))}, {q(a.get('params_id'))}, {q(a['action'])}, {q(bool(a.get('read_only')))}, "
                       f"{q(a.get('logic'))}, {q(_clean(a.get('numbers')) or {})});")
        elif k == "log":
            out.append("insert into iteration_log(routine, change, rationale) values ('routine7', "
                       f"{q(dict(action='chains', status=a['status']))}, {q(a['rationale'])});")
        elif k == "sim_run":
            s, s2, mc = a.get("s"), a.get("s2"), a.get("mc")
            if mc:
                vals = (mc["n"], mc["p_full"], mc["p_full_lo80"], mc["p_full_hi80"], mc["ev_chain_R"], None, mc)
            else:
                vals = (s["n_chains"], s["p_full"], s["p_full_lo80"], s["p_full_hi80"], s["ev_chain_R"],
                        s2["ev_chain_R"] if s2 else None, dict(s, **(a.get("extra") or {})))
            per = a.get("period") or (None, None)
            out.append("insert into chain_sim_runs(source, params_id, variant, n_chains, p_full, p_full_lo80, p_full_hi80, "
                       "ev_chain_r, ev_chain_r_slip2, period_start, period_end, detail) values ("
                       f"{q(a['source'])}, {q(a['params_id'])}, {q(a['variant'])}, {q(vals[0])}, {q(vals[1])}, {q(vals[2])}, "
                       f"{q(vals[3])}, {q(vals[4])}, {q(vals[5])}, {qts(per[0])}, {qts(per[1])}, {q(_clean(vals[6]))});")
        elif k == "stats":
            out.append("insert into chain_stats(params_id, variant, source, n_done, reach, p_levels, p_full, trend, detail) values ("
                       f"{q(a['params_id'])}, {q(a['variant'])}, {q(a['source'])}, {q(a['n_done'])}, {q(_clean(a['reach']))}, "
                       f"{q(_clean(a['p_levels']))}, {q(a['p_full'])}, {q(a['trend'])}, {q(_clean(a['detail']))}) "
                       "on conflict (day, variant, source) do update set n_done=excluded.n_done, reach=excluded.reach, "
                       "p_levels=excluded.p_levels, p_full=excluded.p_full, trend=excluded.trend, detail=excluded.detail;")
        elif k == "params_status":
            out.append(f"update chain_params set status={q(a['status'])}, reason={q(a['reason'])}, updated_at=now() "
                       f"where id={int(a['params_id'])} and status <> 'retiré';")
        elif k == "gating_change":
            out.append(f"update chain_gating set min_score={q(a['new'])}, updated_at=now(), history = history || "
                       f"{q([dict(at=now or time.time(), old=a['old'], new=a['new'], why=a['logic'])])} "
                       f"where params_id={int(a['params_id'])} and k={int(a['level'])};")
            out.append(f"update chain_params set params = jsonb_set(params, '{{gating,{int(a['level']) - 1}}}', "
                       f"to_jsonb({float(a['new'])})), updated_at=now() where id={int(a['params_id'])};")
            out.append("insert into chain_decisions(params_id, action, logic, numbers) values ("
                       f"{int(a['params_id'])}, 'changer_seuil', {q(a['logic'])}, {q(a['numbers'])});")
        elif k == "secure_chain":
            if a.get("read_only"):
                out.append("insert into chain_decisions(chain_id, params_id, action, read_only, logic) values ("
                           f"{q(a['chain_id'])}, {q(a['params_id'])}, 'sécuriser', true, {q(a['logic'])});")
            else:
                out.append(f"update chains set state='sécurisée', bank=gains, house=0, ended_at=now(), end_reason={q(a['logic'])} "
                           f"where id={int(a['chain_id'])} and state='ouverte';")
                out.append("insert into chain_decisions(chain_id, params_id, action, logic) values ("
                           f"{int(a['chain_id'])}, {q(a['params_id'])}, 'sécuriser', {q(a['logic'])});")
        elif k == "open_step":
            out.append(open_step_sql(a))
    return "\n".join(out) + "\n"


def open_step_sql(a):
    nums = {x: a[x] for x in ("k", "pair", "score", "gate", "entry", "stop", "target", "risk", "size", "leverage",
                              "vol_24h", "reduced")}
    if a.get("read_only"):
        return ("insert into chain_decisions(chain_id, params_id, action, read_only, logic, numbers) values ("
                f"{q(a.get('chain_id'))}, {q(a['params_id'])}, 'entrer', true, "
                f"{q('LECTURE SEULE (aurait ouvert) — ' + a['logic'])}, {q(_clean(nums))});")
    cid = "null" if a.get("new_chain") else str(int(a["chain_id"]))
    return f"""do $$
declare cid bigint := {cid}; pid bigint; vk bigint;
begin
  if cid is null then
    insert into chains(params_id, source, risk_initial) values ({int(a['params_id'])}, 'live_paper', {q(a['risk'])}) returning id into cid;
  end if;
  select id into vk from strategy_versions where arm = 'K' and status <> 'retired' order by id limit 1;
  insert into chain_steps(chain_id, k, signal_id, pair, score, gate, entry, stop, target, stop_pct, r_mult, risk, size,
                          leverage, vol_24h, outcome, reason)
  values (cid, {int(a['k'])}, {q(a['signal_id'])}, {q(a['pair'])}, {q(a['score'])}, {q(a['gate'])}, {q(a['entry'])},
          {q(a['stop'])}, {q(a['target'])}, {q(a['stop_pct'])}, {q(a['r_mult'])}, {q(a['risk'])}, {q(a['size'])},
          {q(a['leverage'])}, {q(a['vol_24h'])}, 'ouverte', {q(a['logic'])});
  insert into positions(arm, strategy_version_id, signal_id, pair, side, opened_at, entry_price, size_usd, leverage,
                        stop_price, tp_price, max_hold_until, margin_usd, chain_id, chain_step, last_checked_at)
  values ('K', vk, {q(a['signal_id'])}, {q(a['pair'])}, 'long', now(), {q(a['entry'])}, {q(a['size'])}, {q(a['leverage'])},
          {q(a['stop'])}, {q(a['target'])}, now() + interval '10 days', {q(a['size'] / a['leverage'])}, cid, {int(a['k'])}, now())
  returning id into pid;
  update chain_steps set position_id = pid where chain_id = cid and k = {int(a['k'])};
  insert into chain_decisions(chain_id, params_id, action, logic, numbers)
  values (cid, {int(a['params_id'])}, 'entrer', {q(a['logic'])}, {q(_clean(nums))});
exception when others then
  insert into chain_decisions(chain_id, params_id, action, logic, numbers)
  values (case when {cid} is null then null else {cid} end, {int(a['params_id'])}, 'refus_garde_fou', sqlerrm, {q(_clean(nums))});
end $$;"""


# ----------------------------------------------------------------- rapport hebdomadaire
def report_section(data):
    L = ["## Chaînes de victoires (routine 7, papier uniquement)\n"]
    ro = cfg(data, "chain_readonly_until")
    if ro and time.time() < ts_of(ro):
        L.append(f"> Lecture seule jusqu'au {str(ro)[:16]} : la routine analyse sans ouvrir de chaîne.\n")
    runs = {}
    for r in data.get("sim_runs", []):
        runs[(r["variant"], r["source"])] = r          # le plus récent l'emporte (ordre croissant)
    names = [row["name"] for row in data.get("params", [])]
    status = {row["name"]: row.get("status") for row in data.get("params", [])}
    L.append("| Variante | Source | Chaînes terminées | Niveaux 2/3/4/5 | P(5) [IC 80 %] | Monte Carlo P(5) | Bilan médian | Espérance (R) / glissement x2 | Statut |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for n in names:
        mc = runs.get((n, "monte_carlo"))
        for src in ("replay_history", "shadow", "live_paper"):
            r = runs.get((n, src))
            if not r:
                continue
            d = r.get("detail") or {}
            reach = d.get("reach") or {}
            lv = "/".join(str(reach.get(str(k), reach.get(k, 0))) for k in (2, 3, 4, 5))
            pf = r.get("p_full")
            L.append(f"| {n} | {src} | {r.get('n_chains')} | {lv} | "
                     + (f"{float(pf):.1%} [{float(r['p_full_lo80']):.1%} ; {float(r['p_full_hi80']):.1%}]" if pf is not None else "—")
                     + " | " + (f"{float(mc['p_full']):.1%}" if mc and mc.get("p_full") is not None else "—")
                     + f" | {_fmt(d.get('median_balance'))} | {_fmt(r.get('ev_chain_r'))} / {_fmt(r.get('ev_chain_r_slip2'))} | {status.get(n)} |")
    gating = [g for g in data.get("gating", []) if any(row["id"] == g["params_id"] and row.get("status") == "champion"
                                                         for row in data.get("params", []))]
    if gating:
        L.append("\n**Seuils actuels (variante de départ)** : " + ", ".join(f"niveau {g['k']} ≥ {float(g['min_score']):g}"
                                                                          for g in sorted(gating, key=lambda g: g["k"])))
    week = [d for d in data.get("decisions", []) if time.time() - ts_of(d.get("created_at")) < 7 * DAY]
    syn = next((d for d in reversed(week) if d["action"] == "synthèse_hebdo"), None)
    chg = [d for d in week if d["action"] in ("changer_seuil", "proposition_seuil")]
    L.append("\n**Changements de seuils cette semaine** : " + ("; ".join(d["logic"] for d in chg) if chg else "aucun"))
    if syn:
        n = syn.get("numbers") or {}
        hh = n.get("main_chaude") or {}
        L.append(f"\n**Test « main chaude »** : {hh.get('conclusion', '—')}"
                 + (f" (P(victoire) 1re étape {hh['p_first']:.0%} sur {hh['n_first']}, après 2 victoires "
                    f"{hh['p_after2']:.0%} sur {hh['n_after2']}, p = {hh['p_value']:.2f})" if hh.get("p_first") is not None else ""))
        cal = n.get("calibration_objectif") or {}
        if cal.get("tous"):
            L.append(f"\n**Objectif atteignable** : hausse maximale médiane sur 10 jours = {cal['tous']['median']:.0%} "
                     f"sur {cal['tous']['n']} signaux (tous, y compris ceux qui n'ont rien donné)"
                     + (f" ; cas de pump connus : {cal['cas_de_pump']['median']:.0%}" if cal.get("cas_de_pump") else "") + ".")
        L.append(f"\n**Verdict** : {syn['logic']}")
    live = [c for c in data.get("chains", []) if c["source"] == "live_paper"]
    L.append(f"\n**Papier réel** : {sum(1 for c in live if c['state'] == 'ouverte')} chaîne(s) ouverte(s), "
             f"{sum(1 for c in live if c['state'] != 'ouverte')} terminée(s) ; "
             f"{sum(1 for c in live if c['state'] == 'réussie')} à 5 victoires.")
    L.append("\n- Monte Carlo : estimation de la plage normale, jamais une preuve ; les sources (papier réel, ombre, "
             "rejeu, Monte Carlo) ne sont jamais mélangées dans les statistiques de promotion.")
    return L


def _fmt(x, d=2):
    try:
        return f"{float(x):.{d}f}"
    except (TypeError, ValueError):
        return "—"


# ----------------------------------------------------------------- CLI
def default_fetch(sources=market.DEFAULT_SOURCES):
    return lambda pair, iv, a, b: market.candles(pair, iv, a, b, sources)[0]


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("decide", "daily", "weekly", "report"):
        sp = sub.add_parser(name)
        sp.add_argument("--data", required=True)
        sp.add_argument("--out")
        if name == "daily":
            sp.add_argument("--attempt", type=int, default=1)
        if name == "weekly":
            sp.add_argument("--history", required=True)
    h = sub.add_parser("history")
    h.add_argument("--out", required=True)
    h.add_argument("--days", type=int, default=150)
    h.add_argument("--pairs", type=int, default=80)
    a = ap.parse_args(argv)
    now = time.time()
    if a.cmd == "history":
        from . import chain_history
        r = chain_history.build(days=a.days, n_pairs=a.pairs)
        with open(a.out, "w") as f:
            json.dump(r, f)
        print(f"{len(r['events'])} événements historiques, {len(r['errors'])} erreur(s)")
        return
    data = unwrap(load_json_loose(a.data))
    sources = tuple(cfg(data, "data_sources", list(market.DEFAULT_SOURCES)))
    if a.cmd == "decide":
        acts = decide(data, lambda pair: market.last_price(pair, sources)[0], now,
                      float(cfg(data, "slippage_pct", 0.001)))
    elif a.cmd == "daily":
        acts = daily(data, default_fetch(sources), now, a.attempt)
    elif a.cmd == "weekly":
        with open(a.history) as f:
            hist = json.load(f)
        acts = weekly(data, hist, now, live_events(data, default_fetch(sources), now))
    else:
        print("\n".join(report_section(data)))
        return
    sql = to_sql(acts, now)
    if a.out:
        with open(a.out, "w") as f:
            f.write(sql)
    for x in acts:
        if x["kind"] in ("decision", "open_step", "wait", "gating_change", "secure_chain"):
            print(f"- {x['kind']}/{x.get('action', '')} : {x.get('logic', '')}")
    print(f"{len(acts)} action(s)")


if __name__ == "__main__":
    main()
