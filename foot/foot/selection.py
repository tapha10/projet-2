"""Filtres de sélection et construction des combinés."""
from __future__ import annotations

from math import prod

import numpy as np
import pandas as pd

from .features import eligible_played
from .odds import expected_value

EXCLUDED_COMPETITION_WORDS = ("cup", "coupe", "copa", "pokal", "coppa", "taça", "friendly", "amical",
                              "champions", "europa", "conference", "play-off", "playoff", "nations")


def is_national_league(league_code, cfg, competition_name=None):
    """Championnat national uniquement : code présent dans la liste config et nom non « coupe/amical/… »."""
    if league_code not in cfg["ligues"]:
        return False
    if competition_name and any(w in competition_name.lower() for w in EXCLUDED_COMPETITION_WORDS):
        return False
    return True


def pick_side(p_over):
    return ("over", p_over) if p_over >= 0.5 else ("under", 1 - p_over)


def evaluate_match(row, p_over, cfg, odds_source="Avg", rule=None):
    """Retourne un dict décrivant la décision (retenu ou motif d'exclusion)."""
    from .data import odds_for
    rule = rule or cfg.get("regle_min_matchs", "strict")
    res = {"match_id": row["match_id"], "p_over": p_over, "retenu": False, "motif": None}
    if not is_national_league(row["league"], cfg):
        res["motif"] = "pas un championnat national de la liste"; return res
    if not eligible_played(row, cfg["min_matchs_joues"], rule):
        res["motif"] = "pas assez de matchs joués"; return res
    if p_over is None or np.isnan(p_over):
        res["motif"] = "probabilité indisponible"; return res
    side, p = pick_side(p_over)
    o, src = odds_for(row, side, odds_source)
    res.update(side=side, p=p, odds=o, odds_src=src)
    if o is None:
        res["motif"] = "cote indisponible"; return res
    if o < cfg["cote_min"]:
        res["motif"] = f"cote {o:.2f} < {cfg['cote_min']:.2f}"; return res
    ev = expected_value(p, o)
    res["ev"] = ev
    if ev <= cfg["seuil_valeur"]:
        res["motif"] = f"valeur {ev:+.3f} <= seuil {cfg['seuil_valeur']:+.3f}"; return res
    res["retenu"] = True
    return res


def build_combo(selections: list[dict], size=5, key="ev", conflicts=None):
    """Les meilleures sélections (valeur attendue puis probabilité), un seul pari par rencontre.

    conflicts : fonction (sel_a, sel_b) -> motif ou None (facteur commun : même arbitre, météo…).
    Retourne (jambes, notes).
    """
    pool = [s for s in selections if s.get("retenu")]
    if key == "ev":
        pool.sort(key=lambda s: (-s["ev"], -s["p"]))
    elif key == "odds_low":
        pool.sort(key=lambda s: (s["odds"], -s["p"]))
    elif key == "safe":
        pool.sort(key=lambda s: (-s["p"], -s["ev"]))
    legs, seen, notes = [], set(), []
    for s in pool:
        if s["match_id"] in seen:
            continue
        if conflicts:
            for l in legs:
                why = conflicts(s, l)
                if why:
                    notes.append(f"{s['match_id']} / {l['match_id']} : {why}")
        legs.append(s); seen.add(s["match_id"])
        if len(legs) == size:
            break
    if len(legs) < size:
        notes.append(f"seulement {len(legs)} sélection(s) éligible(s) sur {size} demandées")
    return legs, notes


def combo_summary(legs, dependence_factor=1.0):
    if not legs:
        return {"n": 0, "cote": None, "p_estimee": None, "seuil_equilibre": None}
    o = prod(l["odds"] for l in legs)
    p = prod(l["p"] for l in legs) * dependence_factor
    return {"n": len(legs), "cote": o, "p_estimee": p, "seuil_equilibre": 1 / o,
            "valeur_attendue": p * o - 1}


def same_referee(a, b):
    ra, rb = a.get("referee"), b.get("referee")
    if ra and rb and isinstance(ra, str) and ra == rb:
        return f"même arbitre ({ra})"
    return None
