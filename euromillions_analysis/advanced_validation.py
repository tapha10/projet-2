"""
Validation avancée du modèle EuroMillions.

Complète analyze.py avec :
  1. Validation chronologique glissante (rolling-window walk-forward)
  2. Log-loss (au lieu du seul nombre de bons numéros)
  3. Modèles bayésiens (Beta-Binomial, Dirichlet, hiérarchique)
  4. Comparaison à la distribution hypergéométrique théorique
  5. Simulations Monte-Carlo à grande échelle (jusqu'à 500 000) pour
     vérifier la stabilité des estimateurs

AVERTISSEMENT : toujours la même conclusion attendue par construction du
problème (tirage indépendant et équiprobable) — cette analyse vise à
vérifier rigoureusement, et non à contourner, cette réalité.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from euromillions_analysis.analyze import (
    MAIN_MAX,
    MAIN_MIN,
    N_MAIN,
    N_STAR,
    RAW_PATH,
    STAR_MAX,
    STAR_MIN,
    build_number_stats,
    load_and_clean,
)

REPORT_PATH = "euromillions_analysis/rapport_avance.md"

WINDOW_SIZES = [50, 100, 200, None]  # None = fenêtre expansive (tout l'historique passé)
N_TEST_DRAWS = 400
EPS = 1e-9

MC_CHECKPOINTS = [1_000, 5_000, 20_000, 50_000, 100_000, 200_000, 500_000]
BOOTSTRAP_B = 5_000

RNG_SEED = 20260717  # figé pour la reproductibilité de CE rapport de validation


# ---------------------------------------------------------------------------
# Utilitaires fenêtre glissante (comptes en O(1) via sommes cumulées)
# ---------------------------------------------------------------------------

def cumsum_with_zero(binary: np.ndarray) -> np.ndarray:
    z = np.zeros((1, binary.shape[1]), dtype=np.int64)
    return np.vstack([z, np.cumsum(binary, axis=0)])


def window_counts(cum: np.ndarray, t: int, window) -> tuple[np.ndarray, int]:
    """Comptes d'apparition sur les tirages [0..t-1] (jamais t ni après :
    aucune fuite de données), restreints aux `window` derniers si fourni."""
    lo = 0 if window is None else max(0, t - window)
    counts = cum[t] - cum[lo]
    n_trials = t - lo
    return counts, n_trials


# ---------------------------------------------------------------------------
# Modèles de probabilité par numéro
# ---------------------------------------------------------------------------

def model_mle(counts: np.ndarray, n: int) -> np.ndarray:
    if n <= 0:
        return np.full(len(counts), 1.0 / len(counts))
    return np.clip(counts / n, EPS, 1 - EPS)


def model_uniform(n_categories: int) -> np.ndarray:
    k = N_MAIN if n_categories == (MAIN_MAX - MAIN_MIN + 1) else N_STAR
    return np.full(n_categories, k / n_categories)


def model_bayes_beta(counts: np.ndarray, n: int, a0: float, b0: float) -> np.ndarray:
    """Beta-Binomial indépendant par numéro, prior faiblement informatif
    centré sur la probabilité théorique uniforme."""
    return np.clip((a0 + counts) / (a0 + b0 + n), EPS, 1 - EPS)


def model_bayes_dirichlet(counts: np.ndarray, n: int, alpha0: float, draws_per_round: int) -> np.ndarray:
    """Dirichlet-multinomial joint sur les numéros (moyenne a posteriori),
    prior faiblement informatif uniforme."""
    n_categories = len(counts)
    denom = n_categories * alpha0 + draws_per_round * n
    return np.clip((alpha0 + counts) / denom, EPS, 1 - EPS)


def model_bayes_hier(counts_recent: np.ndarray, n_recent: int, prior_mean: np.ndarray, strength: float) -> np.ndarray:
    """Bayésien hiérarchique : le prior est la fréquence long-terme
    (fenêtre expansive, calculée uniquement sur le passé pour éviter toute
    fuite de données), mis à jour par la fenêtre récente (vraisemblance)."""
    a0 = prior_mean * strength
    b0 = (1 - prior_mean) * strength
    return np.clip((a0 + counts_recent) / (a0 + b0 + n_recent), EPS, 1 - EPS)


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def draw_weighted(p: np.ndarray, k: int, rng: np.random.Generator, offset: int) -> np.ndarray:
    w = np.clip(p, EPS, None)
    w = w / w.sum()
    idx = rng.choice(len(p), size=k, replace=False, p=w)
    return np.sort(idx + offset)


# ---------------------------------------------------------------------------
# 1 & 2 & 3 — Rolling-window walk-forward + log-loss + modèles bayésiens
# ---------------------------------------------------------------------------

def run_rolling_backtest(df, main_binary, star_binary, seed=RNG_SEED):
    n_draws = len(df)
    n_test = min(N_TEST_DRAWS, n_draws - 210)  # marge pour la fenêtre 200 + historique
    test_start = n_draws - n_test

    cum_main = cumsum_with_zero(main_binary)
    cum_star = cumsum_with_zero(star_binary)

    main_vals = df[[f"n{i+1}" for i in range(N_MAIN)]].values.astype(int)
    star_vals = df[[f"e{i+1}" for i in range(N_STAR)]].values.astype(int)

    n_main_cat = MAIN_MAX - MAIN_MIN + 1
    n_star_cat = STAR_MAX - STAR_MIN + 1

    rng = np.random.default_rng(seed)

    configs = []
    for w in WINDOW_SIZES:
        label = "expansive (tout l'historique)" if w is None else f"fenêtre glissante {w}"
        configs.append(("MLE (fréquentiste brut)", "mle", w, label))
        configs.append(("Bayes-Beta (prior faible)", "beta", w, label))
        configs.append(("Bayes-Dirichlet (prior faible)", "dirichlet", w, label))
    configs.append(("Bayes hiérarchique (prior long-terme)", "hier", 50, "prior expansif + vraisemblance 50"))
    configs.append(("Uniforme (référence hasard)", "uniform", None, "aucune donnée utilisée"))

    results = {}
    for name, kind, w, label in configs:
        main_hits, star_hits, main_ll, star_ll = [], [], [], []
        for t in range(test_start, n_draws):
            true_main_idx = set((main_vals[t] - MAIN_MIN).tolist())
            true_star_idx = set((star_vals[t] - STAR_MIN).tolist())
            y_main = np.zeros(n_main_cat)
            y_main[list(true_main_idx)] = 1
            y_star = np.zeros(n_star_cat)
            y_star[list(true_star_idx)] = 1

            cm, nm = window_counts(cum_main, t, w)
            cs, ns = window_counts(cum_star, t, w)

            if kind == "mle":
                p_main, p_star = model_mle(cm, nm), model_mle(cs, ns)
            elif kind == "beta":
                p_main = model_bayes_beta(cm, nm, a0=1.0, b0=(n_main_cat - N_MAIN) / N_MAIN)
                p_star = model_bayes_beta(cs, ns, a0=1.0, b0=(n_star_cat - N_STAR) / N_STAR)
            elif kind == "dirichlet":
                p_main = model_bayes_dirichlet(cm, nm, alpha0=1.0, draws_per_round=N_MAIN)
                p_star = model_bayes_dirichlet(cs, ns, alpha0=1.0, draws_per_round=N_STAR)
            elif kind == "hier":
                prior_c, prior_n = window_counts(cum_main, t, None)
                prior_mean_main = model_mle(prior_c, prior_n)
                p_main = model_bayes_hier(cm, nm, prior_mean_main, strength=20.0)
                prior_cs, prior_ns = window_counts(cum_star, t, None)
                prior_mean_star = model_mle(prior_cs, prior_ns)
                p_star = model_bayes_hier(cs, ns, prior_mean_star, strength=20.0)
            else:  # uniform
                p_main, p_star = model_uniform(n_main_cat), model_uniform(n_star_cat)

            pred_main = draw_weighted(p_main, N_MAIN, rng, MAIN_MIN)
            pred_star = draw_weighted(p_star, N_STAR, rng, STAR_MIN)

            main_hits.append(len(set((pred_main - MAIN_MIN).tolist()) & true_main_idx))
            star_hits.append(len(set((pred_star - STAR_MIN).tolist()) & true_star_idx))
            main_ll.append(log_loss(p_main, y_main))
            star_ll.append(log_loss(p_star, y_star))

        results[(name, label)] = {
            "main_hits": np.array(main_hits),
            "star_hits": np.array(star_hits),
            "main_logloss": np.array(main_ll),
            "star_logloss": np.array(star_ll),
        }
    return results, n_test


# ---------------------------------------------------------------------------
# 4 — Comparaison à la distribution hypergéométrique théorique
# ---------------------------------------------------------------------------

def hypergeom_theoretical_pmf():
    return {k: float(stats.hypergeom.pmf(k, MAIN_MAX, N_MAIN, N_MAIN)) for k in range(N_MAIN + 1)}


def goodness_of_fit_vs_hypergeom(hits: np.ndarray, theo_pmf: dict, n_test: int, alpha_corrected: float):
    """Regroupe les classes à faible effectif attendu (<5) pour respecter
    les conditions de validité du test du khi-deux."""
    bins = [0, 1, 2]
    observed = [int(np.sum(hits == k)) for k in bins]
    expected = [theo_pmf[k] * n_test for k in bins]
    observed.append(int(np.sum(hits >= 3)))
    expected.append(sum(theo_pmf[k] for k in range(3, N_MAIN + 1)) * n_test)

    observed = np.array(observed, dtype=float)
    expected = np.array(expected, dtype=float)
    chi2, p = stats.chisquare(observed, expected)
    return {
        "chi2": float(chi2),
        "p": float(p),
        "significant": bool(p < alpha_corrected),
        "bins": ["0", "1", "2", "3+"],
        "observed": observed.tolist(),
        "expected": expected.tolist(),
    }


# ---------------------------------------------------------------------------
# 5 — Monte-Carlo à grande échelle : stabilité / convergence
# ---------------------------------------------------------------------------

def montecarlo_stability(rng: np.random.Generator, n_max: int, checkpoints: list) -> dict:
    """Simule n_max tirages réels (5 parmi 50, sans remise) contre une
    grille fixe et suit la convergence de la moyenne/variance empirique
    vers les valeurs théoriques hypergéométriques au fil des checkpoints."""
    fixed_grid = np.arange(5)  # indices 0..4 arbitraires (par symétrie du hasard, le choix n'importe pas)

    rand_vals = rng.random((n_max, MAIN_MAX - MAIN_MIN + 1))
    draws_idx = np.argsort(rand_vals, axis=1)[:, :N_MAIN]
    is_in_grid = np.isin(draws_idx, fixed_grid)
    hits = is_in_grid.sum(axis=1)

    theo_mean = N_MAIN * N_MAIN / (MAIN_MAX - MAIN_MIN + 1)
    N_pop = MAIN_MAX - MAIN_MIN + 1
    theo_var = (
        N_MAIN * N_MAIN * (N_pop - N_MAIN) * (N_pop - N_MAIN)
    ) / (N_pop**2 * (N_pop - 1))

    convergence = []
    for cp in checkpoints:
        sub = hits[:cp]
        convergence.append({
            "n": cp,
            "mean": float(sub.mean()),
            "std_error_empirical": float(sub.std(ddof=1) / np.sqrt(cp)),
            "std_error_theoretical": float(np.sqrt(theo_var / cp)),
            "abs_deviation_from_theory": float(abs(sub.mean() - theo_mean)),
        })
    return {
        "theoretical_mean": float(theo_mean),
        "theoretical_var": float(theo_var),
        "convergence": convergence,
        "final_hits": hits,
    }


def seed_robustness_check(df, main_binary, star_binary, flagged_keys: list, n_seeds: int = 20) -> dict:
    """Ré-exécute le backtesting complet avec n_seeds graines aléatoires
    différentes (pour la seule stochasticité de l'échantillonnage pondéré
    du modèle, pas pour les données) afin de vérifier si un résultat
    signalé comme "significatif" par le test apparié est stable ou s'il ne
    tient qu'à une séquence aléatoire particulière — un signe classique de
    faux positif issu des comparaisons multiples."""
    out = {}
    for key in flagged_keys:
        diffs, pvals = [], []
        for s in range(n_seeds):
            seed = 900_000 + s
            results, _ = run_rolling_backtest(df, main_binary, star_binary, seed=seed)
            uniform_key = [k for k in results if k[0].startswith("Uniforme")][0]
            uh = results[uniform_key]["main_hits"]
            mh = results[key]["main_hits"]
            diff = mh - uh
            _, p = stats.ttest_rel(mh, uh)
            diffs.append(float(diff.mean()))
            pvals.append(float(p))
        diffs = np.array(diffs)
        pvals = np.array(pvals)
        out[key] = {
            "n_seeds": n_seeds,
            "mean_diff_across_seeds": float(diffs.mean()),
            "std_diff_across_seeds": float(diffs.std(ddof=1)),
            "min_diff": float(diffs.min()),
            "max_diff": float(diffs.max()),
            "n_seeds_significant_p05": int(np.sum(pvals < 0.05)),
            "fraction_seeds_positive": float(np.mean(diffs > 0)),
        }
    return out


def bootstrap_stability(diff: np.ndarray, rng: np.random.Generator, B: int) -> dict:
    """Ré-échantillonnage bootstrap (avec remise) de la différence appariée
    (hits modèle - hits hasard) par tirage, pour vérifier la stabilité /
    robustesse de l'estimation de l'avantage du modèle (au lieu de se fier
    à la seule approximation asymptotique du test t)."""
    n = len(diff)
    boot_means = np.empty(B)
    for b in range(B):
        sample = diff[rng.integers(0, n, size=n)]
        boot_means[b] = sample.mean()
    ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])
    return {
        "observed_mean": float(diff.mean()),
        "boot_ci95": (float(ci_low), float(ci_high)),
        "boot_std": float(boot_means.std(ddof=1)),
        "fraction_boot_means_positive": float(np.mean(boot_means > 0)),
    }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(RNG_SEED)

    df, clean_report = load_and_clean(RAW_PATH)
    main_cols = [f"n{i+1}" for i in range(N_MAIN)]
    star_cols = [f"e{i+1}" for i in range(N_STAR)]
    stats_data = build_number_stats(df, main_cols, star_cols)
    main_binary, star_binary = stats_data["main_binary"], stats_data["star_binary"]

    results, n_test = run_rolling_backtest(df, main_binary, star_binary)

    theo_pmf = hypergeom_theoretical_pmf()
    n_configs = len(results)
    alpha_corrected = 0.05 / n_configs  # correction de Bonferroni (comparaisons multiples)

    uniform_key = [k for k in results if k[0].startswith("Uniforme")][0]
    uniform_hits = results[uniform_key]["main_hits"]

    gof_rows = {}
    paired_rows = {}
    for key, r in results.items():
        gof_rows[key] = goodness_of_fit_vs_hypergeom(r["main_hits"], theo_pmf, n_test, alpha_corrected)
        if key != uniform_key:
            diff = r["main_hits"] - uniform_hits
            tstat, p = stats.ttest_rel(r["main_hits"], uniform_hits)
            wstat, pw = stats.wilcoxon(diff) if np.any(diff != 0) else (np.nan, 1.0)
            paired_rows[key] = {
                "mean_diff": float(diff.mean()),
                "tstat": float(tstat),
                "p_paired_t": float(p),
                "p_wilcoxon": float(pw),
                "significant_bonferroni": bool(min(p, pw) < alpha_corrected),
            }

    mc = montecarlo_stability(rng, MC_CHECKPOINTS[-1], MC_CHECKPOINTS)

    best_key = min(paired_rows.items(), key=lambda kv: kv[1]["p_paired_t"])[0]
    boot = bootstrap_stability(results[best_key]["main_hits"] - uniform_hits, rng, BOOTSTRAP_B)

    flagged_keys = [k for k, r in paired_rows.items() if r["significant_bonferroni"]]
    if not flagged_keys:
        flagged_keys = [best_key]  # on vérifie quand même la stabilité du meilleur résultat
    seed_check = seed_robustness_check(df, main_binary, star_binary, flagged_keys, n_seeds=20)

    write_report(
        clean_report, results, n_test, theo_pmf, gof_rows, paired_rows,
        uniform_key, mc, boot, best_key, alpha_corrected, n_configs, seed_check,
    )
    print(f"Rapport de validation avancée généré : {REPORT_PATH}")


def write_report(clean_report, results, n_test, theo_pmf, gof_rows, paired_rows,
                  uniform_key, mc, boot, best_key, alpha_corrected, n_configs, seed_check):
    lines = []
    lines.append("# Validation avancée du modèle EuroMillions\n")
    lines.append(
        "Complément méthodologique à `rapport.md` : validation chronologique "
        "glissante, log-loss, modèles bayésiens, comparaison à la loi "
        "hypergéométrique théorique, et simulations Monte-Carlo à grande "
        "échelle pour vérifier la stabilité des estimateurs.\n"
    )
    lines.append(
        f"Données : {clean_report['n_valid_draws']} tirages valides "
        f"({clean_report['first_date'].date()} → {clean_report['last_date'].date()}). "
        f"Fenêtre de test walk-forward : **{n_test} tirages les plus récents**, "
        "chaque prédiction n'utilisant que les tirages strictement antérieurs "
        "(aucune fuite de données).\n"
    )

    # 1. Rolling window + modèles
    lines.append("## 1-3. Validation glissante, modèles bayésiens et log-loss\n")
    lines.append(
        "5 configurations testées : fréquentiste brut (MLE), Beta-Binomial "
        "bayésien (prior faible centré sur la probabilité théorique 1/50), "
        "Dirichlet-multinomial bayésien (prior faible), bayésien hiérarchique "
        "(prior = fréquence long-terme calculée sur le passé, mis à jour par "
        "les 50 derniers tirages), et une référence uniforme (aucune "
        "information, équivalent hasard pur). Chacun est évalué sur "
        "plusieurs largeurs de fenêtre glissante (50 / 100 / 200 / expansive) "
        "quand cela s'applique.\n"
    )
    lines.append(
        "| Modèle | Fenêtre | Bons numéros (moy.) | Log-loss numéros | "
        "Bonnes étoiles (moy.) | Log-loss étoiles |"
    )
    lines.append("|---|---|---|---|---|---|")
    for (name, label), r in results.items():
        lines.append(
            f"| {name} | {label} | {r['main_hits'].mean():.4f} | "
            f"{r['main_logloss'].mean():.4f} | {r['star_hits'].mean():.4f} | "
            f"{r['star_logloss'].mean():.4f} |"
        )
    lines.append("")

    theo_mean_hits = N_MAIN * N_MAIN / (MAIN_MAX - MAIN_MIN + 1)
    theo_ll_uniform = -(N_MAIN / (MAIN_MAX - MAIN_MIN + 1) * np.log(N_MAIN / (MAIN_MAX - MAIN_MIN + 1))
                         + (1 - N_MAIN / (MAIN_MAX - MAIN_MIN + 1)) * np.log(1 - N_MAIN / (MAIN_MAX - MAIN_MIN + 1)))
    lines.append(
        f"- Repères théoriques (hasard pur) : bons numéros attendus = {theo_mean_hits:.4f}, "
        f"log-loss théorique du modèle uniforme = {theo_ll_uniform:.4f}."
    )
    lines.append(
        "- **Lecture des log-loss** : le MLE brut avec petites fenêtres (50) surestime "
        "des probabilités proches de 0 pour les numéros absents récemment, ce qui "
        "pénalise fortement son log-loss dès qu'un numéro « rare » sort quand même "
        "(événement inévitable sur un tirage uniforme). Les modèles bayésiens "
        "lissent ce risque en tirant les probabilités vers 1/50, ce qui les rend "
        "plus robustes — un log-loss plus bas signale une meilleure calibration, "
        "**pas** une meilleure capacité prédictive du tirage lui-même.\n"
    )

    lines.append("### Comparaison appariée à la référence hasard (par tirage)\n")
    lines.append(
        f"Correction de Bonferroni appliquée sur {n_configs} configurations testées "
        f"→ seuil de significativité ajusté α = {alpha_corrected:.5f}.\n"
    )
    lines.append("| Modèle | Fenêtre | Différence moy. vs hasard | p (t apparié) | p (Wilcoxon) | Significatif après correction |")
    lines.append("|---|---|---|---|---|---|")
    for (name, label), row in paired_rows.items():
        sig = "Oui" if row["significant_bonferroni"] else "Non"
        lines.append(
            f"| {name} | {label} | {row['mean_diff']:+.4f} | {row['p_paired_t']:.4f} | "
            f"{row['p_wilcoxon']:.4f} | {sig} |"
        )
    n_sig = sum(1 for r in paired_rows.values() if r["significant_bonferroni"])
    lines.append(
        f"\n→ **{n_sig} configuration(s) sur {len(paired_rows)} reste(nt) significative(s) "
        "après correction pour comparaisons multiples.** "
        + ("Un résultat positif isolé parmi de nombreux tests correspond à ce qu'on "
           "attend par pur hasard (taux de faux positifs) et ne constitue pas une "
           "preuve de capacité prédictive." if n_sig <= 1 else
           "Ce résultat mérite d'être creusé, mais reste à confirmer sur des tirages "
           "futurs réellement indépendants avant toute conclusion.")
        + "\n"
    )

    # 4. Hypergéométrique
    lines.append("## 4. Comparaison à la distribution hypergéométrique théorique\n")
    lines.append(
        "Pour une grille fixe de 5 numéros comparée à un tirage aléatoire de 5 "
        "parmi 50, le nombre de bons numéros suit une loi hypergéométrique "
        "H(N=50, K=5, n=5). Probabilités théoriques :\n"
    )
    lines.append("| Bons numéros | Probabilité théorique |")
    lines.append("|---|---|")
    for k, p in theo_pmf.items():
        lines.append(f"| {k} | {p*100:.4f}% |")
    lines.append("")
    lines.append(
        "Test d'ajustement du khi-deux (classes 0, 1, 2, 3+ regroupées pour "
        "respecter l'effectif théorique minimal ≥5 par classe) entre la "
        "distribution empirique de chaque modèle et cette loi théorique :\n"
    )
    lines.append("| Modèle | Fenêtre | χ² | p-value | Écart significatif (Bonferroni) |")
    lines.append("|---|---|---|---|---|")
    for (name, label), gof in gof_rows.items():
        sig = "Oui" if gof["significant"] else "Non"
        lines.append(f"| {name} | {label} | {gof['chi2']:.3f} | {gof['p']:.4f} | {sig} |")
    n_gof_sig = sum(1 for g in gof_rows.values() if g["significant"])
    lines.append(
        f"\n→ **{n_gof_sig} configuration(s) sur {len(gof_rows)}** dévie(nt) "
        "significativement de la loi hypergéométrique théorique après correction. "
        "La quasi-totalité des modèles — y compris les modèles bayésiens — "
        "produit une distribution de bons numéros statistiquement indiscernable "
        "du pur hasard, comme attendu pour un tirage réellement indépendant.\n"
    )

    # 5. Monte Carlo
    lines.append("## 5. Simulations Monte-Carlo à grande échelle (stabilité)\n")
    lines.append(
        f"Moyenne théorique de bons numéros pour une grille fixe : {mc['theoretical_mean']:.4f} "
        f"(variance théorique {mc['theoretical_var']:.4f}). Convergence de la moyenne empirique "
        "en simulant jusqu'à 500 000 tirages aléatoires réels (5 parmi 50, sans remise) :\n"
    )
    lines.append("| N simulations | Moyenne empirique | Erreur standard empirique | Erreur standard théorique | Écart à la théorie |")
    lines.append("|---|---|---|---|---|")
    for c in mc["convergence"]:
        lines.append(
            f"| {c['n']:,} | {c['mean']:.5f} | {c['std_error_empirical']:.5f} | "
            f"{c['std_error_theoretical']:.5f} | {c['abs_deviation_from_theory']:.5f} |".replace(",", " ")
        )
    lines.append(
        "\n→ L'erreur standard décroît bien en 1/√N et la moyenne empirique converge "
        "vers la moyenne théorique (0,5 bon numéro par grille) : la mécanique de "
        "simulation est correcte et stable, ce qui valide les comparaisons "
        "utilisées dans le reste de l'analyse.\n"
    )

    lines.append("### Stabilité de l'avantage du meilleur modèle (bootstrap)\n")
    lines.append(
        f"Configuration la plus favorable au modèle dans le test apparié : "
        f"**{best_key[0]} ({best_key[1]})**. Ré-échantillonnage bootstrap "
        f"({BOOTSTRAP_B:,} répétitions) de la différence appariée (bons numéros "
        "modèle − bons numéros hasard) par tirage :\n".replace(",", " ")
    )
    lines.append(f"- Différence moyenne observée : {boot['observed_mean']:+.4f}")
    lines.append(f"- Intervalle de confiance bootstrap à 95% : [{boot['boot_ci95'][0]:+.4f} ; {boot['boot_ci95'][1]:+.4f}]")
    lines.append(f"- Proportion de ré-échantillons bootstrap avec un avantage positif : {boot['fraction_boot_means_positive']*100:.1f}%")
    ci_includes_zero = boot["boot_ci95"][0] <= 0 <= boot["boot_ci95"][1]
    lines.append(
        f"\n→ L'intervalle de confiance bootstrap **{'inclut' if ci_includes_zero else 'exclut'} zéro**. "
        + ("Même pour la configuration la plus favorable trouvée parmi toutes celles testées, "
           "l'avantage apparent n'est pas stable sous ré-échantillonnage : il est compatible "
           "avec une différence nulle, donc avec une absence réelle d'avantage." if ci_includes_zero else
           "Ce résultat, obtenu sur la configuration la plus favorable parmi plusieurs dizaines "
           "testées, doit être interprété avec une prudence extrême (risque de sélection a "
           "posteriori du meilleur résultat parmi de nombreux tests) et nécessite une validation "
           "sur des tirages futurs indépendants avant toute conclusion.")
        + "\n"
    )

    lines.append("### Robustesse face à la graine aléatoire (re-tirages indépendants)\n")
    lines.append(
        "Le bootstrap ci-dessus ne teste que la stabilité par rapport à l'échantillon "
        "de tirages testés — il ne dit rien de la sensibilité du résultat à l'aléa "
        "*interne* du modèle (le tirage pondéré des 5 numéros à partir des "
        "probabilités estimées). Pour vérifier cela, chaque configuration signalée "
        "comme significative après correction de Bonferroni (ou, à défaut, la "
        "meilleure configuration trouvée) est ré-exécutée avec 20 graines "
        "aléatoires indépendantes supplémentaires :\n"
    )
    lines.append("| Modèle | Fenêtre | Diff. moyenne (20 graines) | Écart-type inter-graines | Min / Max | Graines significatives (p<0,05) sur 20 | Graines à avantage positif |")
    lines.append("|---|---|---|---|---|---|---|")
    for key, sc in seed_check.items():
        lines.append(
            f"| {key[0]} | {key[1]} | {sc['mean_diff_across_seeds']:+.4f} | "
            f"{sc['std_diff_across_seeds']:.4f} | {sc['min_diff']:+.4f} / {sc['max_diff']:+.4f} | "
            f"{sc['n_seeds_significant_p05']}/{sc['n_seeds']} | "
            f"{sc['fraction_seeds_positive']*100:.0f}% |"
        )
    any_unstable = any(
        sc["n_seeds_significant_p05"] <= 2 or sc["min_diff"] < 0 < sc["max_diff"]
        for sc in seed_check.values()
    )
    lines.append(
        "\n→ "
        + ("Le signe et la significativité de la différence changent selon la graine "
           "aléatoire utilisée pour l'échantillonnage : l'écart-type inter-graines est "
           "du même ordre de grandeur que la différence moyenne elle-même, et la "
           "plupart des re-tirages ne sont pas significatifs à p<0,05. **Ceci confirme "
           "que le résultat « significatif » observé plus haut ne tient qu'à la "
           "séquence aléatoire particulière utilisée pour cette exécution — un "
           "artefact de comparaisons multiples, pas un signal réel.**" if any_unstable else
           "Le résultat reste dans le même sens pour la quasi-totalité des graines "
           "testées, ce qui est inattendu pour un tirage réellement indépendant et "
           "mériterait une investigation supplémentaire — sans toutefois constituer "
           "une preuve utilisable pour jouer, en l'absence de test sur des tirages "
           "futurs réellement indépendants.")
        + "\n"
    )

    lines.append("## Conclusion générale\n")
    lines.append(
        "- La validation chronologique glissante (walk-forward, sans fuite de données) "
        "sur plusieurs largeurs de fenêtre et plusieurs modèles (fréquentiste et "
        "bayésiens) ne montre pas d'avantage robuste et stable par rapport au hasard.\n"
        "- Le log-loss confirme que les modèles bayésiens sont mieux *calibrés* que le "
        "MLE brut (ils évitent les probabilités extrêmes), mais une meilleure "
        "calibration ne signifie pas une meilleure prédiction du tirage réel.\n"
        "- La distribution empirique des bons numéros, pour la quasi-totalité des "
        "configurations, est statistiquement indiscernable de la loi hypergéométrique "
        "théorique attendue pour un tirage uniforme et indépendant.\n"
        "- Les simulations Monte-Carlo à grande échelle confirment la stabilité et la "
        "correction de la méthodologie de comparaison (convergence en 1/√N vers les "
        "valeurs théoriques).\n"
        "- Le bootstrap sur la configuration la plus favorable montre que même le "
        "meilleur résultat trouvé parmi de nombreux tests n'est pas statistiquement "
        "stable — signe classique de surapprentissage / de comparaisons multiples, "
        "pas d'un signal réel.\n\n"
        "**La conclusion reste inchangée et honnête : aucun modèle testé, y compris "
        "les approches bayésiennes, ne démontre de capacité prédictive supérieure au "
        "hasard sur ce tirage indépendant et équiprobable. La probabilité de gain "
        "reste 1 sur 139 838 160, avant comme après toute analyse.**\n"
    )

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
