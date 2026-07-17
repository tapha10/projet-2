"""
Test de facteurs calendaires et astronomiques sur les tirages EuroMillions.

Génère automatiquement 19 colonnes (14 calendaires + 5 astronomiques) à
partir de la seule date de tirage, puis teste leur association avec chacun
des 50 numéros et 12 étoiles, avec correction des comparaisons multiples,
validation hors échantillon, bootstrap et permutations multi-graines.

AVERTISSEMENT : un tirage EuroMillions est mécanique et indépendant de la
date du calendrier ou de la position de la Lune. Cette analyse est un
exercice de rigueur statistique (recherche exhaustive + garde-fous contre
les faux positifs), pas une hypothèse que de tels facteurs devraient avoir
un effet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ephem
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

REPORT_PATH = "euromillions_analysis/rapport_calendaire_astro.md"
ENRICHED_CSV_PATH = "euromillions_analysis/data/euromillions_with_calendar_astro_features.csv"

DRAW_HOUR_UTC = 20  # heure nominale approximative du tirage (20h Paris ~ 18-19h UTC ; simplification documentée)

N_PERMUTATIONS = 5_000
N_PERMUTATION_SEEDS = 4
N_BOOTSTRAP = 3_000
N_SHORTLIST = 6  # nb max de candidats validés en détail (out-of-sample + bootstrap + permutations)

AU_KM = 149_597_870.7
SYNODIC_MONTH = 29.530588853

MOON_PHASE_NAMES = [
    "Nouvelle Lune", "Premier Croissant", "Premier Quartier", "Lune Gibbeuse Croissante",
    "Pleine Lune", "Lune Gibbeuse Décroissante", "Dernier Quartier", "Dernier Croissant",
]


# ---------------------------------------------------------------------------
# Génération des colonnes calendaires
# ---------------------------------------------------------------------------

def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df["date"]
    df["cal_day_of_week"] = d.dt.dayofweek  # 0=lundi
    df["cal_day_of_month"] = d.dt.day
    df["cal_day_of_year"] = d.dt.dayofyear
    df["cal_iso_week"] = d.dt.isocalendar().week.astype(int)
    df["cal_month"] = d.dt.month
    df["cal_quarter"] = d.dt.quarter
    df["cal_year"] = d.dt.year

    season_map = {12: "Hiver", 1: "Hiver", 2: "Hiver",
                  3: "Printemps", 4: "Printemps", 5: "Printemps",
                  6: "Été", 7: "Été", 8: "Été",
                  9: "Automne", 10: "Automne", 11: "Automne"}
    df["cal_season"] = df["cal_month"].map(season_map)

    df["cal_day_even"] = (df["cal_day_of_month"] % 2 == 0)
    df["cal_month_even"] = (df["cal_month"] % 2 == 0)

    df["cal_month_period"] = pd.cut(
        df["cal_day_of_month"], bins=[0, 10, 20, 31], labels=["Début", "Milieu", "Fin"]
    ).astype(str)

    days_in_year = d.dt.is_leap_year.map({True: 366, False: 365})
    year_frac = df["cal_day_of_year"] / days_in_year
    df["cal_year_period"] = pd.cut(
        year_frac, bins=[0, 1 / 3, 2 / 3, 1.0], labels=["Début", "Milieu", "Fin"]
    ).astype(str)

    df["cal_days_since_jan1"] = df["cal_day_of_year"] - 1
    df["cal_days_until_dec31"] = days_in_year - df["cal_day_of_year"]

    return df


# ---------------------------------------------------------------------------
# Génération des colonnes astronomiques (ephem : algorithmes autonomes,
# aucune donnée externe téléchargée)
# ---------------------------------------------------------------------------

def moon_phase_name(age_days: float) -> str:
    idx = int(((age_days / SYNODIC_MONTH) * 8) % 8)
    return MOON_PHASE_NAMES[idx]


def add_astro_features(df: pd.DataFrame) -> pd.DataFrame:
    ages, illum, moon_dist, sun_dist, phase_names = [], [], [], [], []
    for dt in df["date"]:
        ephem_date = ephem.Date(dt.to_pydatetime().replace(
            hour=DRAW_HOUR_UTC, minute=0, second=0, microsecond=0
        ))
        moon = ephem.Moon(ephem_date)
        sun = ephem.Sun(ephem_date)
        moon.compute(ephem_date)
        sun.compute(ephem_date)

        age = float(ephem_date - ephem.previous_new_moon(ephem_date))
        ages.append(age)
        illum.append(float(moon.phase))
        moon_dist.append(float(moon.earth_distance) * AU_KM)
        sun_dist.append(float(sun.earth_distance) * AU_KM)
        phase_names.append(moon_phase_name(age))

    df["astro_moon_age_days"] = ages
    df["astro_moon_illumination_pct"] = illum
    df["astro_moon_phase"] = phase_names
    df["astro_earth_moon_distance_km"] = moon_dist
    df["astro_earth_sun_distance_km"] = sun_dist
    return df


FACTORS = [
    ("cal_day_of_week", "categorical"),
    ("cal_day_of_month", "continuous"),
    ("cal_day_of_year", "continuous"),
    ("cal_iso_week", "continuous"),
    ("cal_month", "categorical"),
    ("cal_quarter", "categorical"),
    ("cal_season", "categorical"),
    ("cal_year", "categorical"),
    ("cal_day_even", "categorical"),
    ("cal_month_even", "categorical"),
    ("cal_month_period", "categorical"),
    ("cal_year_period", "categorical"),
    ("cal_days_since_jan1", "continuous"),
    ("cal_days_until_dec31", "continuous"),
    ("astro_moon_phase", "categorical"),
    ("astro_moon_age_days", "continuous"),
    ("astro_moon_illumination_pct", "continuous"),
    ("astro_earth_moon_distance_km", "continuous"),
    ("astro_earth_sun_distance_km", "continuous"),
]


# ---------------------------------------------------------------------------
# Tests statistiques factor x outcome
# ---------------------------------------------------------------------------

def cramers_v(chi2: float, n: int, r: int, c: int) -> float:
    k = min(r, c)
    if k <= 1 or n <= 0:
        return 0.0
    return float(np.sqrt((chi2 / n) / (k - 1)))


def test_categorical(factor_vals: np.ndarray, outcome: np.ndarray) -> dict:
    levels = np.unique(factor_vals)
    table = np.array([
        [int(np.sum((factor_vals == lv) & (outcome == 0))), int(np.sum((factor_vals == lv) & (outcome == 1)))]
        for lv in levels
    ])
    table = table[table.sum(axis=1) > 0]
    if table.shape[0] < 2:
        return {"stat": 0.0, "p": 1.0, "effect": 0.0, "test": "chi2", "n_levels": table.shape[0]}
    chi2, p, dof, expected = stats.chi2_contingency(table)
    v = cramers_v(chi2, table.sum(), table.shape[0], 2)
    return {"stat": float(chi2), "p": float(p), "effect": v, "test": "chi2", "n_levels": table.shape[0]}


def test_continuous(factor_vals: np.ndarray, outcome: np.ndarray) -> dict:
    a = factor_vals[outcome == 1]
    b = factor_vals[outcome == 0]
    if len(a) < 3 or len(b) < 3:
        return {"stat": 0.0, "p": 1.0, "effect": 0.0, "test": "mannwhitney"}
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    r = 1 - (2 * u) / (len(a) * len(b))  # corrélation rang-biserial
    return {"stat": float(u), "p": float(p), "effect": float(r), "test": "mannwhitney"}


def run_all_tests(df: pd.DataFrame, main_binary: np.ndarray, star_binary: np.ndarray) -> pd.DataFrame:
    rows = []
    outcomes = {}
    for i in range(MAIN_MAX - MAIN_MIN + 1):
        outcomes[("numéro", MAIN_MIN + i)] = main_binary[:, i]
    for i in range(STAR_MAX - STAR_MIN + 1):
        outcomes[("étoile", STAR_MIN + i)] = star_binary[:, i]

    for factor, ftype in FACTORS:
        fv = df[factor].values
        for (kind, num), outcome in outcomes.items():
            if ftype == "categorical":
                r = test_categorical(fv, outcome)
            else:
                r = test_continuous(fv.astype(float), outcome)
            rows.append({
                "factor": factor, "factor_type": ftype, "outcome_kind": kind, "outcome_value": num,
                "test": r["test"], "stat": r["stat"], "p": r["p"], "effect": r["effect"],
            })
    return pd.DataFrame(rows)


def apply_multiple_testing_correction(results: pd.DataFrame) -> pd.DataFrame:
    results = results.copy()
    n_tests = len(results)
    results["p_bonferroni"] = np.minimum(results["p"] * n_tests, 1.0)

    order = np.argsort(results["p"].values)
    sorted_p = results["p"].values[order]
    ranks = np.arange(1, n_tests + 1)
    bh = sorted_p * n_tests / ranks
    bh_adj = np.minimum.accumulate(bh[::-1])[::-1]
    bh_adj = np.clip(bh_adj, 0, 1)
    p_fdr = np.empty(n_tests)
    p_fdr[order] = bh_adj
    results["p_fdr_bh"] = p_fdr
    return results


# ---------------------------------------------------------------------------
# Validation des candidats retenus après correction
# ---------------------------------------------------------------------------

def factor_array_for_test(df, factor):
    return df[factor].values


def recompute_test(factor_vals, ftype, outcome):
    if ftype == "categorical":
        r = test_categorical(factor_vals, outcome)
    else:
        r = test_continuous(factor_vals.astype(float), outcome)
    return r


def out_of_sample_validation(df, main_binary, star_binary, candidate, train_frac=0.7):
    n = len(df)
    split = int(n * train_frac)
    factor = candidate["factor"]
    ftype = candidate["factor_type"]
    kind, num = candidate["outcome_kind"], candidate["outcome_value"]
    outcome_full = main_binary[:, num - MAIN_MIN] if kind == "numéro" else star_binary[:, num - STAR_MIN]
    fv = factor_array_for_test(df, factor)

    r_train = recompute_test(fv[:split], ftype, outcome_full[:split])
    r_test = recompute_test(fv[split:], ftype, outcome_full[split:])

    same_direction = np.sign(r_train["effect"]) == np.sign(r_test["effect"]) if ftype != "categorical" else True
    return {
        "n_train": split, "n_test": n - split,
        "p_train": r_train["p"], "effect_train": r_train["effect"],
        "p_test": r_test["p"], "effect_test": r_test["effect"],
        "confirmed_out_of_sample": bool(r_test["p"] < 0.05 and same_direction),
    }


def bootstrap_validation(df, main_binary, star_binary, candidate, rng, B=N_BOOTSTRAP):
    n = len(df)
    factor = candidate["factor"]
    ftype = candidate["factor_type"]
    kind, num = candidate["outcome_kind"], candidate["outcome_value"]
    outcome_full = main_binary[:, num - MAIN_MIN] if kind == "numéro" else star_binary[:, num - STAR_MIN]
    fv = factor_array_for_test(df, factor)

    effects = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        r = recompute_test(fv[idx], ftype, outcome_full[idx])
        effects[b] = r["effect"]
    ci_low, ci_high = np.percentile(effects, [2.5, 97.5])
    return {
        "boot_mean_effect": float(effects.mean()),
        "boot_ci95": (float(ci_low), float(ci_high)),
        "ci_excludes_zero": bool(ci_low > 0 or ci_high < 0),
    }


def permutation_validation(df, main_binary, star_binary, candidate, n_perm=N_PERMUTATIONS, n_seeds=N_PERMUTATION_SEEDS):
    factor = candidate["factor"]
    ftype = candidate["factor_type"]
    kind, num = candidate["outcome_kind"], candidate["outcome_value"]
    outcome_full = main_binary[:, num - MAIN_MIN] if kind == "numéro" else star_binary[:, num - STAR_MIN]
    fv = factor_array_for_test(df, factor)
    observed = recompute_test(fv, ftype, outcome_full)
    observed_abs = abs(observed["effect"])

    seed_p_values = []
    for s in range(n_seeds):
        rng = np.random.default_rng(700_000 + s)
        count_extreme = 0
        for _ in range(n_perm):
            shuffled = rng.permutation(outcome_full)
            r = recompute_test(fv, ftype, shuffled)
            if abs(r["effect"]) >= observed_abs:
                count_extreme += 1
        p_perm = (count_extreme + 1) / (n_perm + 1)
        seed_p_values.append(p_perm)

    seed_p_values = np.array(seed_p_values)
    return {
        "observed_effect": float(observed["effect"]),
        "n_perm_per_seed": n_perm,
        "n_seeds": n_seeds,
        "p_perm_mean": float(seed_p_values.mean()),
        "p_perm_std": float(seed_p_values.std(ddof=1)),
        "p_perm_min": float(seed_p_values.min()),
        "p_perm_max": float(seed_p_values.max()),
        "stable_across_seeds": bool(seed_p_values.std(ddof=1) < 0.02),
    }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def main():
    df, clean_report = load_and_clean(RAW_PATH)
    main_cols = [f"n{i+1}" for i in range(N_MAIN)]
    star_cols = [f"e{i+1}" for i in range(N_STAR)]
    stats_data = build_number_stats(df, main_cols, star_cols)
    main_binary, star_binary = stats_data["main_binary"], stats_data["star_binary"]

    df = add_calendar_features(df)
    df = add_astro_features(df)
    df.to_csv(ENRICHED_CSV_PATH, index=False)

    results = run_all_tests(df, main_binary, star_binary)
    results = apply_multiple_testing_correction(results)

    n_tests = len(results)
    alpha_bonf = 0.05 / n_tests

    fdr_candidates = results[results["p_fdr_bh"] < 0.05].sort_values("p")
    bonf_candidates = results[results["p_bonferroni"] < 0.05].sort_values("p")

    shortlist = results.sort_values("p").head(N_SHORTLIST)

    rng = np.random.default_rng(20260717)
    validations = []
    for _, cand in shortlist.iterrows():
        cand_d = cand.to_dict()
        oos = out_of_sample_validation(df, main_binary, star_binary, cand_d)
        boot = bootstrap_validation(df, main_binary, star_binary, cand_d, rng)
        perm = permutation_validation(df, main_binary, star_binary, cand_d)
        validations.append({"candidate": cand_d, "oos": oos, "boot": boot, "perm": perm})

    n_factors = len(FACTORS)
    factor_best = results.loc[results.groupby("factor")["p"].idxmin()].copy()
    factor_best["p_bonferroni_within_factor"] = np.minimum(
        factor_best["p"] * results.groupby("factor")["p"].transform("count").loc[factor_best.index], 1.0
    )
    factor_best["p_bonferroni_across_factors"] = np.minimum(factor_best["p_bonferroni_within_factor"] * n_factors, 1.0)

    write_report(clean_report, results, n_tests, alpha_bonf, fdr_candidates, bonf_candidates,
                 shortlist, validations, factor_best)
    print(f"Rapport généré : {REPORT_PATH}")
    print(f"Jeu de données enrichi : {ENRICHED_CSV_PATH}")


def write_report(clean_report, results, n_tests, alpha_bonf, fdr_candidates, bonf_candidates,
                  shortlist, validations, factor_best):
    lines = []
    lines.append("# Facteurs calendaires et astronomiques — EuroMillions\n")
    lines.append(
        "**Avertissement** : un tirage EuroMillions est un processus mécanique indépendant "
        "de la date calendaire ou de la position de la Lune. Cette analyse ne part pas de "
        "l'hypothèse que ces facteurs devraient avoir un effet — elle applique une recherche "
        "exhaustive avec des garde-fous stricts contre les faux positifs, pour vérifier "
        "rigoureusement s'il existe un signal quelconque.\n"
    )
    lines.append(
        f"Données : {clean_report['n_valid_draws']} tirages valides "
        f"({clean_report['first_date'].date()} → {clean_report['last_date'].date()}).\n"
    )

    lines.append("## 1. Facteurs testés\n")
    lines.append("### Facteurs calendaires (14)\n")
    lines.append(
        "Jour de la semaine, jour du mois, numéro du jour dans l'année, semaine ISO, mois, "
        "trimestre, saison (météorologique : hiver=DJF, printemps=MAM, été=JJA, automne=SON), "
        "année, jour pair/impair, mois pair/impair, période du mois (début/milieu/fin en "
        "tiers de 10 jours), période de l'année (tiers de l'année), distance en jours depuis "
        "le 1er janvier, distance en jours jusqu'au 31 décembre.\n"
    )
    lines.append("### Facteurs astronomiques (5)\n")
    lines.append(
        "Calculés avec la bibliothèque `ephem` (algorithmes orbitaux autonomes, aucune donnée "
        "externe téléchargée), à une heure nominale fixe de tirage (20h UTC, approximation "
        "documentée — sans impact matériel sur des facteurs qui évoluent à l'échelle de la "
        "journée) : phase de la Lune (8 catégories), âge de la Lune en jours depuis la "
        "dernière nouvelle lune, pourcentage d'illumination lunaire, distance Terre-Lune (km), "
        "distance Terre-Soleil (km).\n"
    )
    lines.append(
        f"Le jeu de données enrichi (19 colonnes ajoutées) est sauvegardé dans "
        f"`{ENRICHED_CSV_PATH.split('/')[-1]}`.\n"
    )

    lines.append("## 2. Méthode\n")
    n_bootstrap_fmt = f"{N_BOOTSTRAP:,}".replace(",", " ")
    n_perm_fmt = f"{N_PERMUTATIONS:,}".replace(",", " ")
    lines.append(
        "Pour chacun des 19 facteurs, un test est effectué contre chacune des 62 variables "
        "cibles (présence/absence de chacun des 50 numéros et 12 étoiles à chaque tirage), "
        f"soit **{n_tests} tests** au total :\n"
        "- facteur catégoriel → test du khi-deux d'indépendance (table facteur × présence), "
        "taille d'effet = V de Cramér ;\n"
        "- facteur continu → test de Mann-Whitney (valeurs du facteur les jours où le numéro "
        "sort vs les jours où il ne sort pas), taille d'effet = corrélation rang-biserial.\n\n"
        "Corrections de comparaisons multiples appliquées sur l'ensemble des "
        f"{n_tests} tests : correction de Bonferroni (stricte, α ajusté = {alpha_bonf:.2e}) et "
        "correction de Benjamini-Hochberg (FDR, taux de faux positifs attendu ≤5% parmi les "
        "résultats retenus, moins conservatrice et standard en exploration à grande échelle).\n\n"
        f"Les {N_SHORTLIST} associations les plus significatives (plus petite p-value brute) "
        "sont ensuite validées individuellement par :\n"
        "- **validation hors échantillon** : test recalculé séparément sur les 70% de "
        "tirages les plus anciens (entraînement) et les 30% les plus récents (test), en "
        "exigeant un effet dans le même sens et p<0,05 sur la portion de test ;\n"
        f"- **bootstrap** ({n_bootstrap_fmt} ré-échantillonnages) pour obtenir un intervalle de "
        "confiance à 95% de la taille d'effet ;\n"
        f"- **test de permutation multi-graines** ({n_perm_fmt} permutations × "
        f"{N_PERMUTATION_SEEDS} graines indépendantes) : p-value empirique ne reposant sur "
        "aucune approximation asymptotique, répétée avec des graines différentes pour "
        "vérifier sa stabilité.\n"
    )

    lines.append("## 3. Résultats globaux\n")
    lines.append(
        f"- **{len(bonf_candidates)} test(s) sur {n_tests}** significatif(s) après correction "
        f"de Bonferroni (seuil très strict, α={alpha_bonf:.2e})."
    )
    lines.append(
        f"- **{len(fdr_candidates)} test(s) sur {n_tests}** significatif(s) après correction "
        "FDR de Benjamini-Hochberg (seuil moins strict, q=0,05)."
    )
    n_expected_by_chance = int(round(0.05 * n_tests))
    lines.append(
        f"- Pour rappel, sous hypothèse nulle pure (aucun effet réel), on attend en moyenne "
        f"**{n_expected_by_chance} faux positifs** avec un seuil brut à 5% sur {n_tests} tests "
        "non corrigés — d'où la nécessité des corrections ci-dessus.\n"
    )

    lines.append("### Meilleur résultat par facteur (avant validation)\n")
    lines.append(
        "Pour chaque facteur, l'association la plus forte trouvée parmi les 62 variables "
        "cibles testées, avec correction de Bonferroni intra-facteur (×62) puis inter-facteurs "
        "(×19) :\n"
    )
    lines.append("| Facteur | Meilleure cible | p brute | Effet | p corrigée (intra+inter-facteurs) |")
    lines.append("|---|---|---|---|---|")
    for _, row in factor_best.sort_values("p").iterrows():
        target = f"{row['outcome_kind']} {int(row['outcome_value'])}"
        lines.append(
            f"| {row['factor']} | {target} | {row['p']:.4f} | {row['effect']:.4f} | "
            f"{row['p_bonferroni_across_factors']:.4f} |"
        )
    lines.append("")

    lines.append("## 4. Validation détaillée des meilleurs candidats\n")
    lines.append(
        f"Les {N_SHORTLIST} associations avec la p-value brute la plus faible (toutes cibles "
        "confondues), indépendamment de leur significativité après correction — pour vérifier "
        "que même le meilleur résultat trouvé ne résiste pas à une validation indépendante :\n"
    )
    for v in validations:
        c, oos, boot, perm = v["candidate"], v["oos"], v["boot"], v["perm"]
        target = f"{c['outcome_kind']} {int(c['outcome_value'])}"
        lines.append(f"### {c['factor']} → {target}\n")
        lines.append(
            f"- Test complet (n={clean_report['n_valid_draws']}) : {c['test']}, "
            f"p={c['p']:.5f}, effet={c['effect']:.4f}, "
            f"p_Bonferroni_global={c['p_bonferroni']:.4f}, p_FDR={c['p_fdr_bh']:.4f}"
        )
        lines.append(
            f"- Hors échantillon : entraînement (n={oos['n_train']}) p={oos['p_train']:.4f}, "
            f"effet={oos['effect_train']:.4f} → test (n={oos['n_test']}) p={oos['p_test']:.4f}, "
            f"effet={oos['effect_test']:.4f} → **{'confirmé' if oos['confirmed_out_of_sample'] else 'non confirmé'}**"
        )
        lines.append(
            f"- Bootstrap : effet moyen={boot['boot_mean_effect']:.4f}, IC95%="
            f"[{boot['boot_ci95'][0]:.4f} ; {boot['boot_ci95'][1]:.4f}] → "
            f"IC {'exclut' if boot['ci_excludes_zero'] else 'inclut'} zéro"
        )
        n_perm_per_seed_fmt = f"{perm['n_perm_per_seed']:,}".replace(",", " ")
        lines.append(
            f"- Permutations ({n_perm_per_seed_fmt} × {perm['n_seeds']} graines) : "
            f"p empirique moyenne={perm['p_perm_mean']:.4f} (min={perm['p_perm_min']:.4f}, "
            f"max={perm['p_perm_max']:.4f}) → "
            f"{'stable' if perm['stable_across_seeds'] else 'instable'} entre graines\n"
        )

    n_fully_validated = sum(
        1 for v in validations
        if v["oos"]["confirmed_out_of_sample"] and v["boot"]["ci_excludes_zero"] and v["perm"]["p_perm_mean"] < 0.05
    )

    lines.append("## 5. Conclusion\n")
    if n_fully_validated == 0:
        lines.append(
            f"**Aucun des {N_SHORTLIST} meilleurs candidats ne résiste simultanément aux trois "
            "validations (hors échantillon, bootstrap, permutations multi-graines).** "
            + (f"{len(fdr_candidates)} test(s) passaient la correction FDR sur l'ensemble brut, "
               "mais aucun ne se confirme sous validation indépendante — signe classique d'un "
               "faux positif issu du grand nombre de comparaisons effectuées."
               if len(fdr_candidates) > 0 else
               "Aucun test ne passait même la correction FDR, moins stricte que Bonferroni.") + "\n\n"
            "**Tous les facteurs calendaires et astronomiques testés sont statistiquement "
            "compatibles avec le hasard.** Aucun ne présente de signal reproductible. Ce "
            "résultat est cohérent avec la nature mécanique et indépendante du tirage : ni la "
            "date, ni la Lune, ni la distance Terre-Soleil n'ont de lien physique avec la "
            "sélection des boules.\n"
        )
    else:
        lines.append(
            f"**{n_fully_validated} candidat(s) sur {N_SHORTLIST} résiste(nt) aux trois "
            "validations.** Ce résultat est suffisamment inhabituel pour mériter d'être "
            "signalé explicitement, mais reste à confirmer sur des tirages futurs "
            "réellement indépendants avant toute conclusion causale — corrélation n'est pas "
            "causalité, et rien ne justifie physiquement un tel lien.\n"
        )

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
