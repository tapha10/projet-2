"""Statistiques : Wilson, Brier, perte logarithmique, calibration, séries de pertes, tests multiples."""
from math import sqrt, log

import numpy as np
from scipy.stats import norm


def wilson(successes, n, conf=0.95):
    if n == 0:
        return (0.0, 1.0)
    z = norm.ppf(1 - (1 - conf) / 2)
    p = successes / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def brier(p, y):
    p = np.asarray(p, float); y = np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y, eps=1e-12):
    p = np.clip(np.asarray(p, float), eps, 1 - eps); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p, y, bins=10):
    p = np.asarray(p, float); y = np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b if b < 1 else p <= b)
        if m.sum():
            rows.append({"bin": f"{a:.1f}-{b:.1f}", "n": int(m.sum()),
                         "p_moy": float(p[m].mean()), "freq": float(y[m].mean())})
    return rows


def ece(p, y, bins=10):
    rows = calibration_table(p, y, bins)
    n = sum(r["n"] for r in rows)
    return float(sum(r["n"] * abs(r["p_moy"] - r["freq"]) for r in rows) / n) if n else float("nan")


def expected_longest_losing_streak(n, p_win):
    """Longueur attendue de la plus longue série d'échecs sur n essais (approximation classique)."""
    q = 1 - p_win
    if n <= 0 or q <= 0:
        return 0.0
    if q >= 1:
        return float(n)
    return log(n * p_win) / -log(q) if n * p_win > 1 else float(n)


def prob_streak_at_least(n, p_win, k, sims=20000, seed=0):
    """Probabilité d'observer au moins une série de k échecs consécutifs sur n essais (Monte-Carlo)."""
    rng = np.random.default_rng(seed)
    losses = rng.random((sims, n)) > p_win
    hit = np.zeros(sims, bool)
    run = np.zeros(sims, int)
    for j in range(n):
        run = np.where(losses[:, j], run + 1, 0)
        hit |= run >= k
    return float(hit.mean())


def benjamini_hochberg(pvalues, alpha=0.05):
    p = np.asarray(pvalues, float)
    m = len(p)
    if m == 0:
        return np.array([], bool)
    order = np.argsort(p)
    thresh = alpha * (np.arange(1, m + 1) / m)
    passed = p[order] <= thresh
    k = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def paired_logloss_test(p_a, p_b, y):
    """Test de Diebold-Mariano simplifié sur la différence de perte log (a - b). p-valeur unilatérale (b meilleur)."""
    p_a = np.clip(np.asarray(p_a, float), 1e-12, 1 - 1e-12)
    p_b = np.clip(np.asarray(p_b, float), 1e-12, 1 - 1e-12)
    y = np.asarray(y, float)
    la = -(y * np.log(p_a) + (1 - y) * np.log(1 - p_a))
    lb = -(y * np.log(p_b) + (1 - y) * np.log(1 - p_b))
    d = la - lb
    n = len(d)
    if n < 2 or d.std(ddof=1) == 0:
        return {"diff_moy": float(d.mean()) if n else 0.0, "z": 0.0, "p": 1.0, "n": n}
    z = d.mean() / (d.std(ddof=1) / sqrt(n))
    return {"diff_moy": float(d.mean()), "z": float(z), "p": float(1 - norm.cdf(z)), "n": n}


def verdict(n, successes, min_n=100):
    lo, hi = wilson(successes, n)
    if n < min_n:
        return {"statut": "échantillon insuffisant", "n": n, "taux": successes / n if n else None,
                "ic95": (lo, hi)}
    return {"statut": "évaluable", "n": n, "taux": successes / n, "ic95": (lo, hi)}
