"""R5 — optimisation : métriques en direct (probabilités verrouillées dans foot_features contre résultats),
comparaison des modèles, statut des seuils, prochaine hypothèse. Aucun changement appliqué sans validation
hors échantillon (section 9) ; un changement passe toujours par une version de foot_model_versions."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .db import Store
from .decision import should_switch, combo_judgeable, normal_losing_streak
from .memory import next_hypothesis
from .stats import brier, ece, log_loss

MODELS = ["p_m0", "p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4"]


def live_frame(store: Store):
    rows = store.query("select f.match_id, f.features, r.fthg, r.ftag, r.status, m.league, m.kickoff "
                       "from foot_features f join foot_results r on r.match_id=f.match_id "
                       "join foot_matches m on m.match_id=f.match_id where r.status='FT'")
    recs = []
    for r in rows:
        f = json.loads(r["features"]) if isinstance(r["features"], str) else r["features"]
        recs.append({"match_id": r["match_id"], "league": r["league"], "kickoff": r["kickoff"],
                     "y": float(r["fthg"] + r["ftag"] > 2.5), **{m: f.get(m) for m in MODELS}})
    df = pd.DataFrame(recs)
    return df.drop_duplicates("match_id") if len(df) else df


def live_model_table(store: Store):
    df = live_frame(store)
    if df.empty:
        return "Aucun match réglé avec probabilités verrouillées pour l'instant.", df
    lines = ["| modèle | n | perte log | Brier | ECE |", "|---|---|---|---|---|"]
    for m in MODELS:
        d = df.dropna(subset=[m])
        if len(d):
            lines.append(f"| {m} | {len(d)} | {log_loss(d[m], d.y):.4f} | {brier(d[m], d.y):.4f} | "
                         f"{ece(d[m], d.y):.3f} |")
    return "\n".join(lines), df


def run_r5(store: Store, deep=False):
    table, df = live_model_table(store)
    out = ["# R5 — optimisation" + (" approfondie" if deep else ""), "", "## Modèles en direct (hors échantillon)", table, ""]
    active = store.query("select model from foot_model_versions where status='active'")
    active = active[0]["model"] if active else "M3"
    col = f"p_{active.lower()}"
    if len(df):
        for m in MODELS:
            if m == col:
                continue
            d = df.dropna(subset=[col, m])
            ok, why = should_switch(d[col], d[m], d.y, groups=d.league, n_candidates=len(MODELS) - 1)
            out.append(f"- {active} -> {m} : {'CANDIDAT au changement' if ok else 'non'} ({why})")
    combos = store.query("select c.day, c.p_est, x.outcome from foot_combos c join foot_combo_results x on "
                         "x.combo_id=c.combo_id where c.variant='principal' and c.counted=1 and x.outcome!='void'")
    days = len({c["day"] for c in combos})
    out.append("")
    out.append(f"- Combinés comptés : {len(combos)} sur {days} jours ; jugeables : "
               f"{'oui' if combo_judgeable(days, len(combos)) else 'non (60 jours et 40 combinés requis)'}")
    if combos:
        p = float(np.mean([c["p_est"] for c in combos if c["p_est"]]))
        out.append(f"- Série d'échecs « normale » attendue sur {len(combos)} combinés à p≈{p:.1%} : "
                   f"{normal_losing_streak(len(combos), p):.1f}")
    h = next_hypothesis(store)
    out += ["", "## Prochaine idée (une seule à la fois)",
            f"- {h['title']} : {h['description']}" if h else "- aucune hypothèse en file"]
    out.append("Avant tout test : `python -m foot.cli exp-check ...` ; un test déjà enregistré n'est pas relancé.")
    return "\n".join(out)
