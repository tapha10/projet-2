"""Règles de décision et d'arrêt (section 9) et criblage de variables avec correction des tests multiples."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import benjamini_hochberg, ece, log_loss, paired_logloss_test, wilson, expected_longest_losing_streak

MIN_CONCLUSION = 100
MIN_SWITCH = 300
MIN_NO_EDGE = 500
MIN_COMBO_DAYS, MIN_COMBOS = 60, 40


def sample_status(n, wins):
    lo, hi = wilson(wins, n)
    if n < MIN_CONCLUSION:
        return {"statut": "inconclusif", "motif": f"échantillon insuffisant ({n} < {MIN_CONCLUSION})",
                "ic95": (lo, hi)}
    return {"statut": "évaluable", "ic95": (lo, hi)}


def edge_verdict(n, wins, mean_breakeven, months_span, n_leagues, models_tested):
    """« avantage mesuré », « aucun avantage mesuré », ou « inconclusif »."""
    lo, hi = wilson(wins, n)
    if n < MIN_CONCLUSION:
        return "inconclusif", f"{n} prédictions < {MIN_CONCLUSION}"
    if lo > mean_breakeven:
        return "avantage mesuré", f"borne basse IC95 {lo:.3f} > seuil d'équilibre {mean_breakeven:.3f}"
    full = (n >= MIN_NO_EDGE and months_span >= 2 and n_leagues >= 3
            and set(models_tested) >= {"M0", "M1", "M2", "M3", "M4"})
    if hi < mean_breakeven and full:
        return "aucun avantage mesuré", f"borne haute IC95 {hi:.3f} < seuil {mean_breakeven:.3f} sur {n} prédictions"
    if full and lo <= mean_breakeven <= hi:
        return "aucun avantage mesuré", "IC95 contient le seuil d'équilibre après 500 prédictions : pas d'avantage démontré"
    return "inconclusif", f"IC95 [{lo:.3f}, {hi:.3f}] vs seuil {mean_breakeven:.3f} ; conditions d'arrêt non réunies"


def should_switch(p_active, p_cand, y, groups=None, n_candidates=1, alpha=0.05):
    """Changer de modèle actif seulement si : n >= 300, perte log meilleure (test apparié, seuil corrigé
    Bonferroni pour n_candidates), calibration (ECE) pas pire, amélioration dans la majorité des groupes."""
    p_active, p_cand, y = map(lambda v: np.asarray(v, float), (p_active, p_cand, y))
    n = len(y)
    if n < MIN_SWITCH:
        return False, f"{n} < {MIN_SWITCH} prédictions de comparaison"
    t = paired_logloss_test(p_active, p_cand, y)
    if t["p"] > alpha / max(n_candidates, 1):
        return False, f"amélioration non significative (p={t['p']:.3g}, seuil {alpha / n_candidates:.3g})"
    if ece(p_cand, y) > ece(p_active, y) + 0.005:
        return False, "calibration moins bonne"
    if groups is not None:
        g = np.asarray(groups)
        wins = []
        for k in np.unique(g):
            m = g == k
            if m.sum() >= 50:
                wins.append(log_loss(p_cand[m], y[m]) < log_loss(p_active[m], y[m]))
        if len(wins) < 2 or np.mean(wins) < 0.6:
            return False, f"amélioration non confirmée sur les périodes/ligues ({sum(wins)}/{len(wins)})"
    return True, f"meilleure perte log (p={t['p']:.3g}), calibration ok"


def screen_features(df: pd.DataFrame, base_cols, candidates, target="y", time_col="date", alpha=0.05):
    """Ajoute chaque variable candidate à un modèle logistique de base, mesure le gain de perte log
    HORS ÉCHANTILLON (première moitié chronologique -> seconde), puis correction de Benjamini-Hochberg."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    d = df.sort_values(time_col).dropna(subset=list(base_cols) + [target])
    cut = len(d) // 2
    tr, te = d.iloc[:cut], d.iloc[cut:]

    def fit_pred(cols):
        m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=500))
        m.fit(tr[cols].fillna(0), tr[target])
        return m.predict_proba(te[cols].fillna(0))[:, 1]

    base_p = fit_pred(list(base_cols)) if base_cols else np.full(len(te), tr[target].mean())
    res = []
    for c in candidates:
        p = fit_pred(list(base_cols) + [c])
        t = paired_logloss_test(base_p, p, te[target])
        res.append({"variable": c, "gain_logloss": t["diff_moy"], "p": t["p"]})
    out = pd.DataFrame(res)
    out["retenue"] = benjamini_hochberg(out.p.to_numpy(), alpha) if len(out) else []
    return out


def combo_judgeable(n_days, n_combos):
    return n_days >= MIN_COMBO_DAYS and n_combos >= MIN_COMBOS


def normal_losing_streak(n_combos, p_combo):
    return expected_longest_losing_streak(n_combos, p_combo)
