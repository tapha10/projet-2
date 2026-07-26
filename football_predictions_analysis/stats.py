"""
Boîte à outils statistique pour l'évaluation de pronostics sportifs.

Toutes les fonctions sont volontairement génériques et ne dépendent pas de
la taille de l'échantillon disponible : c'est à l'appelant (run_analysis.py,
rapport.md) de juger si un résultat est statistiquement exploitable (le seuil
retenu dans ce projet est n >= 100 par marché, cf. cahier des charges).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# Taux de réussite et intervalle de confiance
# ---------------------------------------------------------------------------

def wilson_confidence_interval(wins: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Intervalle de confiance de Wilson pour une proportion (plus fiable que
    l'approximation normale pour les petits échantillons ou les taux proches
    de 0 ou 1)."""
    if n == 0:
        return (0.0, 0.0)
    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(round(confidence, 2), 1.96)
    p = wins / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return max(0.0, low), min(1.0, high)


# ---------------------------------------------------------------------------
# Rentabilité (ROI, mise fixe de 1 unité)
# ---------------------------------------------------------------------------

@dataclass
class BetResult:
    won: bool
    odds: float | None  # cote décimale au moment du pari ; None si inconnue
    date: str | None = None  # pour les regroupements mensuels / le drawdown


def unit_profits(bets: Sequence[BetResult]) -> list[float]:
    """Profit (mise fixe = 1 unité) pour chaque pari. Un pari dont la cote
    est inconnue est exclu du calcul (retourne None à cette position)."""
    profits = []
    for b in bets:
        if b.odds is None:
            continue
        profits.append((b.odds - 1.0) if b.won else -1.0)
    return profits


def roi(bets: Sequence[BetResult]) -> float | None:
    profits = unit_profits(bets)
    if not profits:
        return None
    return sum(profits) / len(profits)


def implied_probability(odds: float) -> float:
    return 1.0 / odds if odds else 0.0


def max_losing_streak(bets: Sequence[BetResult]) -> int:
    streak = 0
    worst = 0
    for b in bets:
        if not b.won:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return worst


def max_drawdown(bets: Sequence[BetResult]) -> float:
    """Plus forte baisse (en unités) du solde cumulé par rapport à son plus
    haut niveau précédent, mise fixe de 1 unité, paris sans cote exclus."""
    profits = unit_profits(bets)
    if not profits:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    worst_dd = 0.0
    for p in profits:
        cumulative += p
        peak = max(peak, cumulative)
        worst_dd = min(worst_dd, cumulative - peak)
    return worst_dd


def monthly_hit_rate(bets: Sequence[BetResult]) -> dict[str, tuple[int, int]]:
    """Retourne {mois (YYYY-MM): (gagnants, total)} pour évaluer la stabilité
    dans le temps. Nécessite des dates au format ISO ou 'YYYY-MM-DD ...'."""
    out: dict[str, list[int]] = {}
    for b in bets:
        if not b.date:
            continue
        month = b.date[:7]
        out.setdefault(month, [0, 0])
        out[month][1] += 1
        if b.won:
            out[month][0] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Modèles de référence (benchmarks)
# ---------------------------------------------------------------------------

def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_match_probabilities(lambda_home: float, lambda_away: float, max_goals: int = 8):
    """Probabilités 1/N/2, plus de 2.5 buts, BTTS sous un modèle de Poisson
    indépendant simple (référence classique en pronostic sportif, ne prend
    pas en compte la corrélation entre les buts des deux équipes)."""
    p_home = p_draw = p_away = p_over25 = p_btts = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
            if h + a > 2.5:
                p_over25 += p
            if h > 0 and a > 0:
                p_btts += p
    return {
        "home": p_home, "draw": p_draw, "away": p_away,
        "over_2_5": p_over25, "under_2_5": 1 - p_over25,
        "btts_yes": p_btts, "btts_no": 1 - p_btts,
    }


# ---------------------------------------------------------------------------
# Découpage chronologique / validation glissante
# ---------------------------------------------------------------------------

def chronological_split(records: Sequence[dict], date_key: str,
                         train_frac: float = 0.6, tune_frac: float = 0.2):
    """Découpe une liste de dicts (triée par date croissante) en
    train/tune/test selon les fractions données. Ne mélange jamais les
    ensembles (pas de fuite temporelle)."""
    ordered = sorted(records, key=lambda r: r[date_key])
    n = len(ordered)
    n_train = int(n * train_frac)
    n_tune = int(n * tune_frac)
    return ordered[:n_train], ordered[n_train:n_train + n_tune], ordered[n_train + n_tune:]


def walk_forward_folds(records: Sequence[dict], date_key: str, n_folds: int = 5):
    """Validation glissante dans le temps : le fold i sert de test, tous les
    folds antérieurs (0..i-1) servent d'entraînement. Le premier fold n'a pas
    de test associé (pas assez de passé)."""
    ordered = sorted(records, key=lambda r: r[date_key])
    n = len(ordered)
    fold_size = max(1, n // n_folds)
    folds = [ordered[i:i + fold_size] for i in range(0, n, fold_size)]
    out = []
    for i in range(1, len(folds)):
        train = [r for fold in folds[:i] for r in fold]
        test = folds[i]
        out.append((train, test))
    return out


# ---------------------------------------------------------------------------
# Évaluation d'un filtre / d'une règle de sélection
# ---------------------------------------------------------------------------

@dataclass
class FilterEvaluation:
    rule_name: str
    n: int
    wins: int
    hit_rate: float
    ci_low: float
    ci_high: float
    avg_odds: float | None
    roi: float | None
    max_drawdown: float | None
    max_losing_streak: int


def evaluate_filter(rule_name: str, bets: Sequence[BetResult]) -> FilterEvaluation:
    n = len(bets)
    wins = sum(1 for b in bets if b.won)
    hit_rate = wins / n if n else 0.0
    ci_low, ci_high = wilson_confidence_interval(wins, n)
    odds_known = [b.odds for b in bets if b.odds is not None]
    avg_odds = sum(odds_known) / len(odds_known) if odds_known else None
    return FilterEvaluation(
        rule_name=rule_name,
        n=n,
        wins=wins,
        hit_rate=hit_rate,
        ci_low=ci_low,
        ci_high=ci_high,
        avg_odds=avg_odds,
        roi=roi(bets),
        max_drawdown=max_drawdown(bets),
        max_losing_streak=max_losing_streak(bets),
    )
