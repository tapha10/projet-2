"""Cotes : retrait de la marge, cote d'un combiné, seuil d'équilibre."""
from math import prod

from scipy.optimize import brentq


def implied(odds):
    return [1.0 / o for o in odds]


def overround(odds):
    return sum(implied(odds)) - 1.0


def remove_margin(odds, method="proportional"):
    """Probabilités sans marge pour un marché complet (ex. [cote_plus, cote_moins]).

    proportional : p_i = (1/o_i) / somme(1/o_j)
    power        : p_i = (1/o_i)^k avec k tel que somme = 1 (corrige un peu le biais favori/outsider)
    """
    if any(o is None or o <= 1.0 for o in odds):
        raise ValueError(f"cotes invalides : {odds}")
    raw = implied(odds)
    if method == "proportional":
        s = sum(raw)
        return [r / s for r in raw]
    if method == "power":
        if abs(sum(raw) - 1.0) < 1e-12:
            return raw
        k = brentq(lambda k: sum(r ** k for r in raw) - 1.0, 0.2, 5.0)
        return [r ** k for r in raw]
    raise ValueError(method)


def combo_odds(odds):
    return prod(odds)


def breakeven_prob(o):
    """Probabilité de réussite minimale pour ne pas perdre à la cote o."""
    return 1.0 / o


def combo_breakeven(odds):
    return 1.0 / combo_odds(odds)


def expected_value(p, o):
    """Valeur attendue par unité misée : p*o - 1."""
    return p * o - 1.0
