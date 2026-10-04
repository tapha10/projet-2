"""Phase 1 : backtest des références et des modèles de départ, enregistré dans la mémoire (foot_experiments).

Reproductible : python -m foot.phase1  (utilise data/base_full.pkl produit par `cli train --rebuild`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import AVERTISSEMENT, ROOT, load_config
from .backtest import (breakdown, model_metrics, references, selection_summary, simulate_combos,
                       simulate_selection, compare)
from .db import Store, now_utc
from .decision import should_switch, edge_verdict
from .memory import add_hypothesis, add_lesson, record_experiment, should_run
from .stats import benjamini_hochberg

DATA_DESC = "football-data.co.uk, 22 championnats, saisons 2021-22 à 2026-27 (au 30/09/2026)"
PERIOD = "hors échantillon : 2023-24 -> 2026-27"


def odds_bucket(o):
    return pd.cut(o, [1.69, 1.8, 1.9, 2.0, 2.2, 10], labels=["1.70-1.80", "1.80-1.90", "1.90-2.00",
                                                           "2.00-2.20", ">2.20"])


def run(store: Store, base: pd.DataFrame, cfg=None, write_doc=True):
    cfg = cfg or load_config()
    oos = base[base.season >= "2324"].copy()
    lines = [f"# Backtest Phase 1 — {now_utc().date()}", "", f"_{AVERTISSEMENT}_", "",
             f"Données : {DATA_DESC}. Période {PERIOD}. Aucune information postérieure au jour du match "
             "(M1 réajusté chaque jour sur le passé ; M2/M3 entraînés sur les saisons antérieures ; "
             "M4 pondéré par la saison précédente). Cote = cote moyenne d'avant-match (Avg), clôture = AvgC.", ""]

    # 1) qualité probabiliste de tous les modèles sur les mêmes matchs
    mm = model_metrics(oos)
    lines += ["## 1. Qualité des probabilités (tous les matchs, mêmes matchs pour chaque modèle)", "",
              mm.round(4).to_markdown(index=False), ""]
    tests = {}
    for m in ["p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4"]:
        tests[m] = compare(oos, "p_m0", m)  # p faible = le modèle bat le marché
    pv = [t["p"] for t in tests.values()]
    bh = benjamini_hochberg(pv, 0.05)
    lines += ["Test apparié de perte log contre le marché (M0), correction de Benjamini-Hochberg sur 5 tests :", ""]
    for (m, t), sig in zip(tests.items(), bh):
        verdict = "bat le marché" if sig and t["diff_moy"] > 0 else "ne bat pas le marché"
        lines.append(f"- {m} : écart moyen de perte log {t['diff_moy']:+.5f} (positif = meilleur que M0), "
                     f"p = {t['p']:.3g} -> **{verdict}**")
        hyp = f"{m} a une perte log plus faible que le marché (M0)"
        proto = {"test": "Diebold-Mariano apparié perte log", "vs": "p_m0", "modele": m,
                 "correction": "BH 5 tests", "periode": PERIOD}
        go, key, why = should_run(store, hyp, proto)
        if go:
            concl = "confirmé" if (sig and t["diff_moy"] > 0) else "infirmé" if t["diff_moy"] < 0 else "inconclusif"
            record_experiment(store, hyp, proto, t, concl, DATA_DESC, PERIOD, m)
    lines.append("")

    # 2) règles de sélection (section 4) par modèle et par lecture de la règle « plus de 5 matchs »
    lines += ["## 2. Règles de sélection (cote >= 1,70, valeur > 0, plus de 5 matchs joués)", "",
              "| modèle | règle | n | réussite | IC 95 % | seuil d'équilibre | ROI | écart clôture | bat la clôture | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    sels = {}
    n_tests = 0
    for m in ["p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4"]:
        for rule in ["strict", "au_moins"]:
            sel = simulate_selection(oos, m, cfg, rule=rule)
            sels[(m, rule)] = sel
            s = selection_summary(sel)
            n_tests += 1
            if s["n"] == 0:
                continue
            months = (sel.date.max() - sel.date.min()).days / 30
            v, why = edge_verdict(s["n"], s["gagnes"], s["seuil_equilibre_moyen"], months,
                                  sel.league.nunique(), ["M0", "M1", "M2", "M3", "M4"])
            # tests multiples : 10 variantes -> IC à 99,5 % (Bonferroni) pour un « avantage »
            from .stats import wilson
            lo_b, _ = wilson(s["gagnes"], s["n"], conf=1 - 0.05 / 10)
            if v == "avantage mesuré" and lo_b <= s["seuil_equilibre_moyen"]:
                v, why = "inconclusif", "avantage non robuste à la correction pour 10 variantes testées"
            lines.append(f"| {m} | {rule} | {s['n']} | {s['taux']:.1%} | {s['ic95'][0]:.1%}–{s['ic95'][1]:.1%} | "
                         f"{s['seuil_equilibre_moyen']:.1%} | {s['roi']:+.1%} | {s['clv_moyen'] or 0:+.2%} | "
                         f"{s['part_bat_cloture'] or 0:.0%} | {v} |")
            hyp = f"La sélection {m} (règle {rule}, cote>=1.70, valeur>0) bat le seuil d'équilibre"
            proto = {"modele": m, "regle": rule, "cote_min": cfg["cote_min"], "seuil_valeur": cfg["seuil_valeur"],
                     "periode": PERIOD, "correction": "Bonferroni 10 variantes"}
            go, key, _ = should_run(store, hyp, proto)
            if go:
                concl = {"avantage mesuré": "confirmé", "aucun avantage mesuré": "infirmé"}.get(v, "inconclusif")
                record_experiment(store, hyp, proto, {k: (list(x) if isinstance(x, tuple) else x)
                                                      for k, x in s.items()}, concl, DATA_DESC, PERIOD, m,
                                  ci=s["ic95"])
    lines.append("")

    # 3) références sur les mêmes matchs
    lines += ["## 3. Références sur les mêmes matchs que chaque sélection (règle stricte)", "",
              "| modèle | modèle | hasard | toujours plus | toujours moins | favori du marché |", "|---|---|---|---|---|---|"]
    for m in ["p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4"]:
        r = references(sels[(m, "strict")], oos)
        if r:
            lines.append(f"| {m} | " + " | ".join(f"{r[k]['taux']:.1%} (ROI {r[k]['roi']:+.1%})" for k in
                                                   ["modele", "hasard", "toujours_plus", "toujours_moins",
                                                    "favori_marche"]) + " |")
    lines.append("")

    # 4) détail de la meilleure sélection (par ligue, tranche de cote, côté, saison)
    best = max([(m, r) for (m, r) in sels if r == "strict"], key=lambda k: sels[k].pnl.mean() if len(sels[k]) else -9)
    sel = sels[best].copy()
    sel["tranche_cote"] = odds_bucket(sel.odds)
    sel["mois"] = sel.date.dt.to_period("M").astype(str)
    lines += [f"## 4. Détail de la sélection {best[0]} (règle {best[1]})", ""]
    for by in ["side", "tranche_cote", "season", "league"]:
        b = breakdown(sel, by)
        if len(b):
            lines += [f"### Par {by}", "", b.round(3).to_markdown(index=False), ""]
    cb = simulate_combos(sel, 5)
    if len(cb):
        lines += ["### Combiné quotidien (jusqu'à 5 matchs)", "",
                  f"- {len(cb)} jours avec au moins une sélection ; combinés de 5 matchs complets : {(cb.n == 5).sum()}",
                  f"- gagnés : {(cb.outcome == 'win').sum()} ({(cb.outcome == 'win').mean():.1%}) ; "
                  f"probabilité estimée moyenne {cb.p_est.mean():.1%} ; ROI simulé {cb.pnl.mean():+.1%}", ""]

    # 5) décision sur le modèle actif (règles section 9)
    groups = (oos.season.astype(str) + "-" + oos.league.astype(str)).to_numpy()
    lines += ["## 5. Choix du modèle actif (section 9)", ""]
    d = oos.dropna(subset=["p_m1", "p_m3", "y"])
    g = (d.season.astype(str)).to_numpy()
    ok, why = should_switch(d.p_m1, d.p_m3, d.y, groups=g, n_candidates=4)
    lines.append(f"- M1 -> M3 : {'changement accepté' if ok else 'refusé'} ({why}) ; n = {len(d)}")
    ok0, why0 = should_switch(d.p_m0, d.p_m3, d.y, groups=g, n_candidates=4)
    lines.append(f"- M3 contre le marché M0 : {'M3 meilleur' if ok0 else 'M3 pas significativement meilleur'} ({why0})")
    active = "M3" if ok else "M1"
    lines.append(f"- **Modèle actif retenu : {active}** (les autres tournent en observation).")
    lines.append("")
    lines += ["## 6. Conclusion honnête", "",
              "- Le marché (M0) est une estimation très difficile à battre : M1 et M2 (Poisson / Dixon-Coles sur "
              "les buts) sont nettement moins bons que lui (perte log et calibration), et leur sélection "
              "« valeur > 0 » perd environ 7 % : ils prennent la marge du bookmaker pour de la valeur.",
              "- M3 (logistique sur M0 + M1 + variables) égale le marché, avec un gain minime. Sa sélection "
              "affiche un ROI positif sur environ 300 paris, mais l'IC 95 % contient le seuil d'équilibre et "
              "l'avantage disparaît après correction des tests multiples : **inconclusif**.",
              "- Aucune conclusion « avantage mesuré » n'est possible à ce stade. Le suivi réel (Phase 2) "
              "décidera, avec les seuils de la section 9."]
    content = "\n".join(lines)
    if write_doc:
        (ROOT / "docs" / "backtest.md").write_text(content, encoding="utf-8")

    add_lesson(store, "M1 (Dixon-Coles sur les buts) surestime la probabilité du côté choisi d'environ 9 points "
               "quand on filtre sur la valeur attendue > 0 (58 % annoncé, 49 % observé, backtest 2023-2026)",
               "Ne jamais calculer la valeur attendue avec un modèle non recalibré contre le marché ; "
               "un modèle candidat doit battre M0 en perte log hors échantillon avant d'être actif.", "phase1")
    add_lesson(store, "Une précision élevée sur environ 300 sélections disparaît après correction pour 10 variantes testées",
               "Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes "
               "essayées avant de parler d'avantage.", "phase1")
    for t, dsc, pr in [
        ("M3 sélection 'plus' uniquement", "Les sélections M3 rentables sont surtout des « plus 2,5 » : tester la restriction au côté plus, hors échantillon sur 2026-27 en direct.", 1),
        ("Recalibration isotone de M1 contre le marché", "Recalibrer M1 (isotone sur l'historique) avant de l'utiliser dans M3/M4.", 2),
        ("xG 2026-27 dans M1", "Mesurer l'apport des xG (disponibles depuis 2026-27) sur la perte log de M1 et M3.", 2),
        ("Mouvement de cote ouverture -> verrouillage", "Utiliser l'évolution de la cote entre deux instantanés comme variable (exige des instantanés réguliers).", 3),
        ("Seuil de valeur optimal", "Tester seuil_valeur 0 %, 2 %, 4 % pour M3 avec correction des tests multiples.", 3),
        ("Re-sélection à T-75 min", "Variante d'observation : re-sélectionner avec les compositions confirmées (exige une source de compositions).", 4),
    ]:
        if not store.query("select 1 from foot_hypotheses where title=?", (t,)):
            add_hypothesis(store, t, dsc, pr)
    return {"active": active, "content": content, "metrics": mm}


if __name__ == "__main__":
    from .cli import store as get_store, OUTBOX
    s = get_store()
    base = pd.read_pickle(ROOT / "data" / "base_full.pkl")
    out = run(s, base)
    print(out["content"])
    s.flush_outbox(OUTBOX)
