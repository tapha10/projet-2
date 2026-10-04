"""Rapports quotidien (R4) et hebdomadaire (R6) — courts, lisibles sur mobile."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np

from . import AVERTISSEMENT
from .db import Store, now_utc
from .pipeline import cumulative, phase_of, prediction_outcome
from .stats import wilson, log_loss, brier

SIDE_FR = {"over": "Plus 2,5", "under": "Moins 2,5"}
PHASE_FR = {"0": "Phase 0 — audit", "1": "Phase 1 — base historique", "2": "Phase 2 — observation",
            "3": "Phase 3 — optimisation"}


def _pct(x):
    return "—" if x is None else f"{100 * x:.1f} %"


def _match_label(store, mid):
    m = store.query("select home, away, league from foot_matches where match_id=?", (mid,))
    return f"{m[0]['home']} – {m[0]['away']} ({m[0]['league']})" if m else mid


def predictions_of_day(store: Store, day: date, variant="principal"):
    return store.query("select * from foot_predictions where variant=? and selected=1 and substr(kickoff,1,10)=? "
                       "order by kickoff", (variant, day.isoformat()))


def references_for(store: Store, preds):
    """Références sur les mêmes matchs : toujours plus, toujours moins, favori du marché (M0)."""
    out = {"toujours_plus": [0, 0], "toujours_moins": [0, 0], "favori_marche": [0, 0]}
    for p in preds:
        r = store.query("select fthg, ftag, status from foot_results where match_id=?", (p["match_id"],))
        if not r or r[0]["status"] != "FT":
            continue
        over = r[0]["fthg"] + r[0]["ftag"] > 2.5
        out["toujours_plus"][0] += over; out["toujours_plus"][1] += 1
        out["toujours_moins"][0] += (not over); out["toujours_moins"][1] += 1
        f = store.query("select features from foot_features where match_id=? order by computed_at limit 1",
                        (p["match_id"],))
        p0 = json.loads(f[0]["features"]).get("p_m0") if f else None
        if p0 is not None:
            out["favori_marche"][0] += (p0 >= 0.5) == over; out["favori_marche"][1] += 1
    return out


def daily_report(store: Store, day: date, today_combo=None):
    """Rapport du lendemain : `day` = la veille ; `today_combo` = combiné du jour (après verrouillage)."""
    phase = phase_of(store, day + timedelta(days=1))
    cum = cumulative(store)
    L = [f"# Rapport du {(day + timedelta(days=1)).strftime('%d/%m/%Y')} — matchs du {day.strftime('%d/%m')}",
         f"_{AVERTISSEMENT}_", "",
         f"**{PHASE_FR.get(phase, phase)}** · prédictions comptées cumulées : **{cum['n']}**"
         + (" · échantillon insuffisant" if cum["n"] < 100 else ""), ""]
    preds = predictions_of_day(store, day)
    L.append("## Hier, match par match")
    if not preds:
        L.append("Aucune sélection hier.")
    wins = n = 0
    for p in preds:
        res = store.query("select fthg, ftag, status from foot_results where match_id=?", (p["match_id"],))
        o = prediction_outcome(store, p["id"])
        score = f"{res[0]['fthg']}-{res[0]['ftag']}" if res and res[0]["status"] == "FT" else (
            res[0]["status"] if res else "en attente")
        mark = {"win": "✅", "loss": "❌", "void": "⚪", "pending": "⏳"}[o]
        L.append(f"- {mark} {_match_label(store, p['match_id'])} : {SIDE_FR[p['side']]} @ {p['odds']:.2f}, "
                 f"p = {_pct(p['prob'])} → {score}")
        if o in ("win", "loss"):
            n += 1; wins += o == "win"
    if n:
        L.append(f"Précision hier : {wins}/{n}.")
    combos = store.query("select c.*, x.outcome, x.payout, x.notes as xnotes from foot_combos c left join "
                         "foot_combo_results x on x.combo_id=c.combo_id where c.day=? order by c.variant",
                         (day.isoformat(),))
    if combos:
        L.append("")
        L.append("## Combinés d'hier")
        for c in combos:
            oc = c["outcome"] or "en attente"
            L.append(f"- {c['variant']} ({c['n_legs']} matchs, cote {c['combo_odds'] or 0:.2f}, "
                     f"p estimée {_pct(c['p_est'])}) : **{oc}**" + (f" — {c['xnotes']}" if c["xnotes"] else ""))
    L += ["", "## Cumul (prédictions comptées)"]
    lo, hi = cum["ic95"]
    L.append(f"- Précision : {_pct(cum['taux'])} sur {cum['n']} (IC 95 % {_pct(lo)}–{_pct(hi)}) ; "
             f"seuil d'équilibre moyen {_pct(cum['seuil_equilibre'])} ; ROI simulé {_pct(cum['roi'])}")
    allp = store.query("select * from foot_predictions where variant='principal' and selected=1 and counted=1")
    refs = references_for(store, allp)
    noms = {"toujours_plus": "toujours plus", "toujours_moins": "toujours moins", "favori_marche": "favori du marché"}
    L.append("- Références sur les mêmes matchs : " + " · ".join(
        f"{noms[k]} {_pct(v[0] / v[1]) if v[1] else '—'}" for k, v in refs.items()) + " · hasard 50 % (attendu)")
    errs = store.query("select e.cause, e.evidence, e.match_id from foot_error_analysis e join foot_predictions p "
                       "on p.id=e.prediction_id where substr(p.kickoff,1,10)=?", (day.isoformat(),))
    L += ["", "## Erreurs d'hier"]
    L += [f"- {_match_label(store, e['match_id'])} : {e['cause']} — {e['evidence']}" for e in errs] or ["Aucune."]
    lessons = store.query("select rule from foot_lessons where substr(created_at,1,10)>=? order by id",
                          (day.isoformat(),))
    L += ["", "## Leçons ajoutées"] + ([f"- {l['rule']}" for l in lessons] or ["Aucune."])
    L += ["", "## Combiné du jour"]
    if today_combo and today_combo.get("legs"):
        for l in today_combo["legs"]:
            L.append(f"- {l['home']} – {l['away']} ({l['league']}) : {SIDE_FR[l['side']]} @ {l['odds']:.2f}, "
                     f"p = {_pct(l['p'])}, valeur {l['ev']:+.3f}")
        L.append(f"Cote {today_combo['cote']:.2f} · p estimée {_pct(today_combo['p_estimee'])} · "
                 f"seuil d'équilibre {_pct(today_combo['seuil_equilibre'])}")
        if today_combo.get("notes"):
            L.append("Notes : " + " ; ".join(today_combo["notes"]))
    else:
        L.append("Pas de combiné aujourd'hui (aucune sélection éligible ou pas de matchs couverts par la source).")
    L += ["", "## Limites", "- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n'utilise "
          "que le repos et l'enjeu.", "- Résultats football-data publiés avec 1 à 3 jours de retard : certains "
          "matchs restent « en attente »."]
    content = "\n".join(L)
    store.insert("foot_daily_reports", {"day": day.isoformat(), "phase": phase, "n_predictions_cum": cum["n"],
                                        "content": content, "created_at": now_utc()}, upsert=True)
    return content


def weekly_report(store: Store, week_end: date, model_table=None, verdict=None):
    start = week_end - timedelta(days=6)
    phase = phase_of(store, week_end)
    rows = store.query("select p.*, r.fthg, r.ftag, r.status, m.league from foot_predictions p join foot_results r "
                       "on r.match_id=p.match_id join foot_matches m on m.match_id=p.match_id where p.selected=1 "
                       "and p.variant='principal' and substr(p.kickoff,1,10) between ? and ?",
                       (start.isoformat(), week_end.isoformat()))
    rows = [r for r in rows if r["status"] == "FT"]
    cum = cumulative(store)
    L = [f"# Rapport hebdomadaire — semaine du {start.strftime('%d/%m')} au {week_end.strftime('%d/%m/%Y')}",
         f"_{AVERTISSEMENT}_", "", f"**{PHASE_FR.get(phase, phase)}** · cumul compté : {cum['n']} prédictions", ""]
    if rows:
        y = np.array([(r["fthg"] + r["ftag"] > 2.5) == (r["side"] == "over") for r in rows], float)
        p = np.array([r["prob"] for r in rows])
        lo, hi = wilson(int(y.sum()), len(y))
        L.append(f"- Semaine : {int(y.sum())}/{len(y)} ({_pct(y.mean())}, IC 95 % {_pct(lo)}–{_pct(hi)}), "
                 f"p moyenne annoncée {_pct(p.mean())}, Brier {brier(p, y):.3f}")
        by = {}
        for r, yy in zip(rows, y):
            by.setdefault(r["league"], []).append(yy)
        L.append("- Par ligue : " + ", ".join(f"{k} {int(sum(v))}/{len(v)}" for k, v in sorted(by.items())))
    else:
        L.append("- Aucune prédiction réglée cette semaine.")
    combos = store.query("select c.variant, x.outcome from foot_combos c join foot_combo_results x on "
                         "x.combo_id=c.combo_id where c.day between ? and ?", (start.isoformat(), week_end.isoformat()))
    if combos:
        agg = {}
        for c in combos:
            agg.setdefault(c["variant"], []).append(c["outcome"])
        L.append("- Combinés : " + ", ".join(f"{k} {v.count('win')}/{len([o for o in v if o != 'void'])}"
                                             for k, v in sorted(agg.items())))
    if model_table:
        L += ["", "## Modèles (hors échantillon)", model_table]
    lessons = store.query("select rule from foot_lessons where active=1 order by id desc limit 5")
    L += ["", "## Leçons actives"] + ([f"- {l['rule']}" for l in lessons] or ["Aucune."])
    hyp = store.query("select title from foot_hypotheses where status='à tester' order by priority, id limit 1")
    L += ["", "## Prochaine expérience", f"- {hyp[0]['title']}" if hyp else "- (aucune en file)"]
    need = max(0, 100 - cum["n"])
    L += ["", "## Verdict", verdict or (
        f"Échantillon insuffisant : il manque {need} prédictions comptées avant toute conclusion (seuil 100), "
        "300 pour changer de modèle, 500 sur 2 mois pour conclure à l'absence d'avantage." if need else
        "Voir le tableau des modèles : conclusion seulement si les seuils de la section 9 sont atteints.")]
    content = "\n".join(L)
    store.insert("foot_weekly_reports", {"week_start": start.isoformat(), "phase": phase,
                                         "verdict": verdict or "insuffisant", "content": content,
                                         "created_at": now_utc()}, upsert=True)
    return content


def append_today_combo(store: Store, yesterday: date, combo):
    """R1 (10:00) complète le rapport du matin (R4, 08:15) avec le combiné du jour, une fois verrouillé."""
    rows = store.query("select * from foot_daily_reports where day=?", (yesterday.isoformat(),))
    section = ["## Combiné du jour"]
    if combo and combo.get("legs"):
        for l in combo["legs"]:
            section.append(f"- {l['home']} – {l['away']} ({l['league']}) : {SIDE_FR[l['side']]} @ {l['odds']:.2f}, "
                           f"p = {_pct(l['p'])}, valeur {l['ev']:+.3f}")
        section.append(f"Cote {combo['cote']:.2f} · p estimée {_pct(combo['p_estimee'])} · "
                       f"seuil d'équilibre {_pct(combo['seuil_equilibre'])}")
    else:
        section.append("Pas de combiné aujourd'hui : " + "; ".join((combo or {}).get("notes") or
                                                                    ["aucune sélection éligible"]))
    if combo and combo.get("legs") and combo.get("notes"):
        section.append("Notes : " + " ; ".join(combo["notes"]))
    if not rows:
        return None
    content = rows[0]["content"]
    start = content.find("## Combiné du jour")
    end = content.find("\n## ", start + 5)
    new = content[:start] + "\n".join(section) + ("\n" + content[end + 1:] if end != -1 else "")
    store.insert("foot_daily_reports", {**rows[0], "content": new}, upsert=True)
    return new
