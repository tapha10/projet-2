"""Cycle quotidien : R1 prédictions, R2 nouvelles d'avant-match, R3 résultats, R4 rapport, R5 optimisation,
R6 rapport hebdomadaire. Toutes les écritures passent par Store (SQLite local + boîte d'envoi Supabase).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import AVERTISSEMENT, load_config
from .backtest import add_m0, add_learned_models
from .db import Store, iso, now_utc, payload_hash
from .features import match_features
from .memory import RoutineRun, add_lesson
from .models import DixonColes, M2Adjust, M3Logistic, m4_combine, m4_weights, p_over_from_lambdas
from .selection import build_combo, combo_summary, evaluate_match, same_referee
from .settle import settle_combo, settle_side
from .stats import log_loss, wilson

PARIS = ZoneInfo("Europe/Paris")
MODEL_VERSIONS = {
    "M0": ("M0-v1", {"marge": "proportionnelle", "cote": "Avg"}),
    "M1": ("M1-v1", {"demi_vie_jours": 180, "fenetre_jours": 730, "xg_weight": 0.5, "shrink": 3}),
    "M2": ("M2-v1", {"base": "M1-v1", "variables": ["repos<=3j", "rien à jouer", "fin de saison",
                                                    "absences chiffrées"]}),
    "M3": ("M3-v1", {"type": "logistique L2 C=0.5", "validation": "saisons glissantes"}),
    "M3gbm": ("M3gbm-v1", {"type": "gradient boosting, profondeur 3", "statut": "observation"}),
    "M4": ("M4-v1", {"type": "moyenne pondérée des logits", "poids": "softmax(-50 x perte log récente)"}),
}


# ------------------------------------------------------------------ phase
def phase_of(store: Store, day: date):
    cfg = {r["key"]: r["value"] for r in store.query("select key, value from foot_config")}
    start = cfg.get("date_jour1")
    if not start:
        return "0"
    start = date.fromisoformat(start.strip('"'))
    n = store.query("select count(*) n from foot_predictions where selected=1 and counted=1 "
                    "and variant='principal'")[0]["n"]
    k = (day - start).days + 1
    if k < 1:
        return "0"
    if k <= 2:
        return "1"
    if k <= 16 or n < 100:
        return "2"
    return "3"


def counted_flag(store: Store, day: date):
    """Les 3 premiers jours après activation sont en lecture seule : rien n'est compté."""
    rows = store.query("select value from foot_config where key='date_activation'")
    if not rows:
        return False
    act = date.fromisoformat(rows[0]["value"].strip('"'))
    return day >= act + timedelta(days=3)


def ensure_model_versions(store: Store, active="M1"):
    for m, (v, params) in MODEL_VERSIONS.items():
        status = "active" if m == active else ("observation" if m != "M0" else "candidate")
        if not store.query("select 1 from foot_model_versions where version=?", (v,)):
            store.insert("foot_model_versions", {"version": v, "model": m, "params": params,
                                                 "status": status, "created_at": now_utc()})


# ------------------------------------------------------------------ R1
def fit_learned(hist_base: pd.DataFrame):
    """Entraîne M2/M3/M3gbm sur tout l'historique déjà réglé (base issue du backtest)."""
    tr = hist_base.dropna(subset=["y", "p_m1", "p_m0"])
    m2 = M2Adjust().fit(tr)
    tr = tr.copy(); tr["p_m2"] = m2.p_over(tr)
    m3 = M3Logistic().fit(tr)
    g = M3Logistic(kind="gbm").fit(tr)
    return m2, m3, g


def predict_frame(hist: pd.DataFrame, fixtures: pd.DataFrame, cfg, learned=None, m4w=None):
    """Probabilités de tous les modèles pour les matchs à venir (aucune information postérieure)."""
    allm = pd.concat([hist, fixtures[~fixtures.match_id.isin(hist.match_id)]], ignore_index=True)
    feats = match_features(allm, cfg.get("poids_saison_precedente_demi_vie_matchs", 6))
    fx = add_m0(feats[feats.match_id.isin(fixtures.match_id)]).copy()
    done = hist.dropna(subset=["fthg", "ftag"])
    window = pd.Timedelta(days=cfg.get("dc_fenetre_jours", 730))
    for c in ["m1_lh", "m1_la", "m1_rho", "p_m1"]:
        fx[c] = np.nan
    for (lg, d), grp in fx.groupby(["league", "date"]):
        tr = done[(done.league == lg) & (done.date < d) & (done.date >= d - window)]
        if len(tr) < 60:
            continue
        m = DixonColes(cfg.get("dc_demi_vie_jours", 180), cfg.get("xg_weight", 0.5)).fit(tr, d)
        for i, r in grp.iterrows():
            lh, la = m.lambdas(r.home, r.away)
            if np.isnan(lh):
                continue
            fx.loc[i, ["m1_lh", "m1_la", "m1_rho"]] = [lh, la, m.rho]
            fx.loc[i, "p_m1"] = float(p_over_from_lambdas(lh, la, m.rho)[0])
    for c in ["p_m2", "p_m3", "p_m3gbm", "p_m4"]:
        fx[c] = np.nan
    if learned:
        m2, m3, g = learned
        ok = fx.p_m1.notna()
        if ok.any():
            fx.loc[ok, "p_m2"] = m2.p_over(fx[ok])
            ok3 = ok & fx.p_m0.notna()
            if ok3.any():
                fx.loc[ok3, "p_m3"] = m3.p_over(fx[ok3])
                fx.loc[ok3, "p_m3gbm"] = g.p_over(fx[ok3])
        if m4w:
            fx["p_m4"] = [m4_combine({k: r[k] for k in m4w}, m4w) for _, r in fx.iterrows()]
    return fx


def record_match(store: Store, r):
    store.insert("foot_matches", {"match_id": r.match_id, "league": r.league, "season": r.season,
                                  "kickoff": iso(r.kickoff.to_pydatetime()) if pd.notna(r.kickoff) else None,
                                  "home": r.home, "away": r.away,
                                  "referee": r.referee if isinstance(r.referee, str) else None,
                                  "status": "SCHEDULED", "created_at": now_utc()}, upsert=False)


FEATURE_KEYS = ["p_m0", "p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4", "m1_lh", "m1_la", "m1_rho",
                "o_over_avg", "o_under_avg", "o_over_b365", "o_under_b365", "h_played_season", "a_played_season",
                "h_ew_over", "a_ew_over", "h_ew_tot", "a_ew_tot", "h_ew_xgf", "a_ew_xgf", "h_rest_days", "a_rest_days",
                "h_nothing_to_play", "a_nothing_to_play", "h_frac_season"]


def record_features(store: Store, r, now, captured_at):
    """Probabilités de tous les modèles et variables clés, verrouillées en même temps que les prédictions."""
    feats = {k: (None if pd.isna(r.get(k)) else float(r.get(k))) for k in FEATURE_KEYS if k in r}
    store.insert("foot_features", {"match_id": r.match_id, "model_version": "all-v1", "computed_at": iso(now),
                                   "data_cutoff": iso(captured_at), "features": feats})


def record_odds(store: Store, r, captured_at):
    for side in ("over", "under"):
        for src in ("avg", "b365", "max"):
            v = r.get(f"o_{side}_{src}")
            if v is not None and pd.notna(v) and v > 1:
                store.insert("foot_odds_snapshots", {"match_id": r.match_id, "side": side, "line": 2.5,
                                                     "odds": float(v), "source": f"football-data:{src}",
                                                     "captured_at": captured_at})


def lock_prediction(store: Store, r, model, version, e, variant, phase, counted, locked_at):
    kickoff = r.kickoff.to_pydatetime()
    if locked_at >= kickoff:
        return None  # trop tard : jamais de prédiction après le coup d'envoi
    side = e.get("side") or ("over" if r[f"p_{model.lower()}"] >= 0.5 else "under")
    p_over = r[f"p_{model.lower()}"]
    prob = p_over if side == "over" else 1 - p_over
    body = {"match_id": r.match_id, "model": model, "model_version": version, "variant": variant,
            "side": side, "prob": round(float(prob), 6),
            "odds": e.get("odds"), "odds_source": e.get("odds_src"),
            "odds_captured_at": iso(e.get("captured_at")), "ev": None if e.get("ev") is None else round(e["ev"], 6),
            "selected": 1 if e.get("retenu") else 0, "phase": phase, "counted": 1 if counted else 0,
            "kickoff": iso(kickoff), "locked_at": iso(locked_at)}
    h = payload_hash(body)
    pid = f"{r.match_id}-{model}-{variant}-{locked_at.strftime('%Y%m%d')}"
    store.insert("foot_predictions", {"id": pid, **body, "payload_hash": h, "created_at": locked_at})
    return pid


def run_r1(store: Store, hist: pd.DataFrame, fixtures: pd.DataFrame, captured_at, day: date, cfg=None,
           hist_base=None, now=None, dry=False, learned=None):
    """Collecte + prédictions + combiné du jour, verrouillés à l'heure `now` (avant les coups d'envoi)."""
    cfg = cfg or load_config()
    now = now or now_utc()
    with RoutineRun(store, "R1", day, dry) as run:
        day_fx = fixtures[fixtures.kickoff.dt.tz_convert(PARIS).dt.date == day]
        run.read = {"matchs_du_jour_source": int(len(day_fx)), "capture_cotes": iso(captured_at)}
        phase = phase_of(store, day); counted = counted_flag(store, day)
        active = cfg.get("modele_actif", "M1")
        ensure_model_versions(store, active)
        if learned is None and hist_base is not None and len(hist_base) > 2000:
            learned = fit_learned(hist_base)
        m4w = cfg.get("_m4_poids")
        fx = predict_frame(hist, day_fx, cfg, learned, m4w) if len(day_fx) else day_fx
        decisions, n_pred = [], 0
        for _, r in fx.iterrows():
            record_match(store, r)
            record_odds(store, r, captured_at)
            if r.kickoff.to_pydatetime() > now:
                record_features(store, r, now, captured_at)
            for model in ["M0", "M1", "M2", "M3", "M3gbm", "M4"]:
                col = f"p_{model.lower()}"
                if col not in r or pd.isna(r[col]):
                    continue
                e = evaluate_match(r, r[col], cfg, cfg.get("source_cote", "Avg"))
                e["captured_at"] = captured_at
                e["referee"] = r.referee if isinstance(r.referee, str) else None
                e["home"], e["away"], e["league"], e["kickoff"] = r.home, r.away, r.league, r.kickoff
                if not e["retenu"]:
                    continue  # probabilités de tous les modèles déjà verrouillées dans foot_features
                variant = "principal" if model == active else "observation"
                pid = lock_prediction(store, r, model, MODEL_VERSIONS[model][0], e, variant, phase, counted, now)
                if pid:
                    n_pred += 1
                    if model == active:
                        e["prediction_id"] = pid
                        decisions.append(e)
        combos = {}
        for variant, size, key in [("principal", cfg["taille_combine"], "ev"), ("top2", 2, "ev"),
                                   ("top3", 3, "ev"), ("top4", 4, "ev"),
                                   ("top5_cotes_basses", 5, "odds_low"), ("top5_plus_sur", 5, "safe")]:
            legs, notes = build_combo(decisions, size, key, conflicts=same_referee)
            combos[variant] = lock_combo(store, day, variant, legs, notes, phase, counted, now)
        run.changed = {"predictions": n_pred, "selections": sum(d.get("retenu", False) for d in decisions),
                       "combine_principal_jambes": len(combos["principal"]["legs"]),
                       "notes_combine": combos["principal"]["notes"]}
        run.why = f"phase {phase} ; modèle actif {active}"
        return {"fx": fx, "decisions": decisions, "combos": combos, "phase": phase}


def lock_combo(store, day, variant, legs, notes, phase, counted, now):
    summ = combo_summary(legs)
    if not legs:  # aucun match éligible : pas de combiné (motif conservé dans le journal et le rapport)
        return {"combo_id": None, "legs": [], "notes": notes or ["aucune sélection éligible"], **summ}
    cid = f"{day.isoformat()}-{variant}"
    body = {"combo_id": cid, "day": day.isoformat(), "variant": variant, "n_legs": len(legs),
            "combo_odds": summ["cote"], "p_est": summ["p_estimee"], "breakeven": summ["seuil_equilibre"],
            "phase": phase, "counted": 1 if counted else 0, "locked_at": iso(now),
            "legs": [l["prediction_id"] for l in legs]}
    h = payload_hash(body)
    body.pop("legs")
    store.insert("foot_combos", {**body, "payload_hash": h, "notes": "; ".join(notes) or None,
                                 "created_at": now})
    for i, l in enumerate(legs, 1):
        store.insert("foot_combo_legs", {"combo_id": cid, "leg_no": i, "prediction_id": l["prediction_id"],
                                         "match_id": l["match_id"]})
    return {"combo_id": cid, "legs": legs, "notes": notes, **summ}


# ------------------------------------------------------------------ R2
def run_r2(store: Store, news: list[dict], now=None, dry=False):
    """Enregistre compositions/absences récentes ; ne modifie jamais une prédiction verrouillée.

    news : liste de dicts {match_id, team, player, role, status, impact_metric, impact_value, source, captured_at}
    (vide si aucune source de compositions n'est accessible : c'est alors noté dans le journal).
    """
    now = now or now_utc()
    with RoutineRun(store, "R2", now.date(), dry) as run:
        n = 0
        for x in news:
            locked = store.query("select 1 from foot_predictions where match_id=? and locked_at < ?",
                                 (x["match_id"], iso(x.get("captured_at", now))))
            store.insert("foot_team_news", {**x, "after_lock": 1 if locked else 0,
                                            "captured_at": x.get("captured_at", now)})
            n += 1
        run.changed = {"nouvelles": n}
        run.why = "aucune source de compositions accessible" if not news else "nouvelles enregistrées"
        return n


# ------------------------------------------------------------------ R3
def run_r3(store: Store, results: pd.DataFrame, now=None, dry=False):
    """Règle les matchs (temps réglementaire) et les combinés. results : match_id, fthg, ftag, status, source."""
    now = now or now_utc()
    with RoutineRun(store, "R3", now.date(), dry) as run:
        pending = store.query("select distinct p.match_id from foot_predictions p left join foot_results r "
                              "on r.match_id = p.match_id where r.match_id is null")
        ids = {p["match_id"] for p in pending}
        res = results[results.match_id.isin(ids)]
        n = 0
        for _, r in res.iterrows():
            st = r.get("status", "FT")
            if st == "FT" and (pd.isna(r.fthg) or pd.isna(r.ftag)):
                continue
            store.insert("foot_results", {"match_id": r.match_id,
                                          "fthg": None if pd.isna(r.fthg) else int(r.fthg),
                                          "ftag": None if pd.isna(r.ftag) else int(r.ftag),
                                          "total": None if pd.isna(r.fthg) else int(r.fthg + r.ftag),
                                          "status": st, "source": r.get("source", "football-data"),
                                          "settled_at": now})
            if st != "FT":
                store.insert("foot_matches", {"match_id": r.match_id, "status": st}, upsert=True)
            n += 1
        nc = settle_combos(store, now)
        run.changed = {"resultats": n, "combines_regles": nc}
        return n


def prediction_outcome(store: Store, pid):
    r = store.query("select p.side, r.fthg, r.ftag, r.status from foot_predictions p join foot_results r "
                    "on r.match_id = p.match_id where p.id = ?", (pid,))
    if not r:
        return "pending"
    r = r[0]
    return settle_side(r["side"], r["fthg"], r["ftag"], r["status"])


def settle_combos(store: Store, now):
    open_ = store.query("select c.combo_id from foot_combos c left join foot_combo_results x "
                        "on x.combo_id = c.combo_id where x.combo_id is null or x.outcome='pending'")
    n = 0
    for c in open_:
        legs = store.query("select l.prediction_id, p.odds from foot_combo_legs l join foot_predictions p "
                           "on p.id = l.prediction_id where l.combo_id = ? order by leg_no", (c["combo_id"],))
        if not legs:
            store.insert("foot_combo_results", {"combo_id": c["combo_id"], "outcome": "void", "payout": 1.0,
                                                "notes": "aucune jambe", "settled_at": now}, upsert=True)
            n += 1
            continue
        outs = [prediction_outcome(store, l["prediction_id"]) for l in legs]
        if "loss" in outs:
            outcome, pay = "loss", 0.0
        elif "pending" in outs:
            continue
        else:
            outcome, pay = settle_combo(outs, [l["odds"] for l in legs])
        nv = outs.count("void")
        store.insert("foot_combo_results", {
            "combo_id": c["combo_id"], "outcome": outcome, "payout": pay, "legs_void": nv,
            "notes": f"{nv} jambe(s) annulée(s) : combiné recalculé sur les autres" if nv else None,
            "settled_at": now}, upsert=True)
        n += 1
    return n


# ------------------------------------------------------------------ erreurs
def analyse_errors(store: Store, day: date):
    """Classe chaque prédiction principale ratée. Sans preuve d'une autre cause : « variance normale »
    si la probabilité annoncée laissait ≥ 25 % d'échec, sinon « indéterminé » (à examiner)."""
    rows = store.query(
        "select p.id, p.match_id, p.side, p.prob, r.fthg, r.ftag, r.status from foot_predictions p "
        "join foot_results r on r.match_id = p.match_id where p.selected = 1 and p.variant='principal' "
        "and substr(p.kickoff,1,10) = ?", (day.isoformat(),))
    out = []
    for r in rows:
        if r["status"] != "FT" or settle_side(r["side"], r["fthg"], r["ftag"]) != "loss":
            continue
        late = store.query("select player, role, impact_value from foot_team_news where match_id=? and after_lock=1",
                           (r["match_id"],))
        if late:
            cause = "absence tardive"
            ev = f"{len(late)} information(s) postérieure(s) au verrouillage : " + ", ".join(
                f"{x['player']} ({x['role']})" for x in late[:3])
        elif r["prob"] < 0.75:
            cause = "variance normale"
            ev = (f"probabilité annoncée {r['prob']:.0%} : un échec arrive {1 - r['prob']:.0%} du temps ; "
                  f"score {r['fthg']}-{r['ftag']}")
        else:
            cause = "indéterminé"
            ev = f"probabilité annoncée {r['prob']:.0%} et échec : à examiner (score {r['fthg']}-{r['ftag']})"
        store.insert("foot_error_analysis", {"prediction_id": r["id"], "match_id": r["match_id"],
                                             "cause": cause, "evidence": ev, "created_at": now_utc()})
        out.append({"id": r["id"], "cause": cause, "preuve": ev})
    return out


# ------------------------------------------------------------------ statistiques cumulées
def cumulative(store: Store, model_variant="principal", counted_only=True):
    q = ("select p.*, r.fthg, r.ftag, r.status from foot_predictions p join foot_results r on "
         "r.match_id = p.match_id where p.selected=1 and p.variant=? " + ("and p.counted=1" if counted_only else ""))
    rows = store.query(q, (model_variant,))
    rows = [r for r in rows if r["status"] == "FT"]
    wins = sum(settle_side(r["side"], r["fthg"], r["ftag"]) == "win" for r in rows)
    n = len(rows)
    lo, hi = wilson(wins, n)
    roi = (sum((r["odds"] - 1) if settle_side(r["side"], r["fthg"], r["ftag"]) == "win" else -1 for r in rows) / n
           if n else None)
    be = float(np.mean([1 / r["odds"] for r in rows])) if n else None
    return {"n": n, "gagnes": wins, "taux": wins / n if n else None, "ic95": (lo, hi), "roi": roi,
            "seuil_equilibre": be}
