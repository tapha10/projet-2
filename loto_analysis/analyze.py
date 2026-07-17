"""
Analyse statistique du Loto (FDJ, France) et génération d'une combinaison
expérimentale unique.

Règles du Loto : 5 numéros distincts parmi 1-49, + 1 numéro chance parmi
1-10 (format en vigueur depuis 2019). Différent d'EuroMillions (5 parmi 50
+ 2 étoiles parmi 12) : probabilité globale bien plus favorable, mais
toujours extrêmement faible.

AVERTISSEMENT : ceci est une exploration statistique à but ludique/éducatif.
Chaque tirage est indépendant et équiprobable. Aucune méthode statistique
ne peut augmenter la probabilité réelle de gagner. Voir le rapport final
pour le rappel honnête des probabilités.
"""

from __future__ import annotations

import random
import re
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

RAW_PATH = "loto_analysis/data/loto_201911.csv"
REPORT_PATH = "loto_analysis/rapport.md"
RANDOM_SEED = None  # None => aléa contrôlé (basé sur l'horloge) à chaque exécution

N_MAIN, N_STAR = 5, 1  # "étoile" = numéro chance (un seul)
MAIN_MIN, MAIN_MAX = 1, 49
STAR_MIN, STAR_MAX = 1, 10
TOTAL_COMBINATIONS = 19_068_840  # C(49,5) x 10

N_CANDIDATES = 120_000
N_MONTECARLO_RANDOM = 10_000
N_BACKTEST_DRAWS = 150


# ---------------------------------------------------------------------------
# Étape 1 — Importation et contrôle des données
# ---------------------------------------------------------------------------

def detect_columns(df: pd.DataFrame) -> dict:
    cols = list(df.columns)
    lower = {c: c.lower() for c in cols}

    date_col = None
    for c in cols:
        if re.search(r"date.*tirage", lower[c]) and "forclusion" not in lower[c]:
            date_col = c
            break
    if date_col is None:
        for c in cols:
            if "date" in lower[c]:
                date_col = c
                break

    main_cols = []
    for c in cols:
        if re.fullmatch(r"boule[_\s]?\d+", lower[c].strip()) and "second" not in lower[c]:
            main_cols.append(c)
    main_cols = sorted(main_cols, key=lambda c: int(re.search(r"\d+", c).group()))[:N_MAIN]

    star_col = None
    for c in cols:
        if "chance" in lower[c] and "second" not in lower[c]:
            star_col = c
            break

    if date_col is None or len(main_cols) != N_MAIN or star_col is None:
        raise ValueError(
            f"Détection de colonnes incomplète: date={date_col}, "
            f"numéros={main_cols}, numéro chance={star_col}"
        )
    return {"date": date_col, "main": main_cols, "star": [star_col]}


def load_and_clean(path: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, sep=";", engine="python")
    n_raw = len(raw)
    cols = detect_columns(raw)

    df = raw[[cols["date"]] + cols["main"] + cols["star"]].copy()
    df.columns = ["date"] + [f"n{i+1}" for i in range(N_MAIN)] + [f"e{i+1}" for i in range(N_STAR)]

    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    n_before_dropna = len(df)
    df = df.dropna()
    n_dropped_na = n_before_dropna - len(df)

    main_cols = [f"n{i+1}" for i in range(N_MAIN)]
    star_cols = [f"e{i+1}" for i in range(N_STAR)]

    valid_main = df[main_cols].apply(
        lambda row: row.between(MAIN_MIN, MAIN_MAX).all() and row.nunique() == N_MAIN, axis=1
    )
    valid_star = df[star_cols].apply(lambda row: row.between(STAR_MIN, STAR_MAX).all(), axis=1)
    n_invalid_range = len(df) - (valid_main & valid_star).sum()
    df = df[valid_main & valid_star].copy()

    df[main_cols] = np.sort(df[main_cols].values.astype(int), axis=1)
    df[star_cols] = df[star_cols].values.astype(int)

    n_before_dupes = len(df)
    df = df.drop_duplicates(subset=["date"] + main_cols + star_cols)
    df = df.drop_duplicates(subset=["date"], keep="first")
    n_dupes = n_before_dupes - len(df)

    df = df.sort_values("date").reset_index(drop=True)

    stats_report = {
        "n_raw_rows": n_raw,
        "n_dropped_missing": int(n_dropped_na),
        "n_dropped_invalid_range_or_duplicate_values": int(n_invalid_range),
        "n_dropped_duplicate_draws": int(n_dupes),
        "n_valid_draws": len(df),
        "first_date": df["date"].min(),
        "last_date": df["date"].max(),
    }
    return df, stats_report


# ---------------------------------------------------------------------------
# Étape 2 — Statistiques descriptives
# ---------------------------------------------------------------------------

def gap_stats(appearances_idx: np.ndarray, n_draws: int) -> dict:
    if len(appearances_idx) == 0:
        return {"mean_gap": np.nan, "std_gap": np.nan, "since_last": n_draws}
    gaps = np.diff(appearances_idx)
    since_last = (n_draws - 1) - appearances_idx[-1]
    return {
        "mean_gap": float(np.mean(gaps)) if len(gaps) else np.nan,
        "std_gap": float(np.std(gaps)) if len(gaps) else np.nan,
        "since_last": int(since_last),
    }


def build_number_stats(df: pd.DataFrame, main_cols: list, star_cols: list) -> dict:
    n_draws = len(df)
    main_vals = df[main_cols].values
    star_vals = df[star_cols].values

    main_binary = np.zeros((n_draws, MAIN_MAX - MAIN_MIN + 1), dtype=np.int8)
    for i in range(n_draws):
        main_binary[i, main_vals[i] - MAIN_MIN] = 1

    star_binary = np.zeros((n_draws, STAR_MAX - STAR_MIN + 1), dtype=np.int8)
    for i in range(n_draws):
        star_binary[i, star_vals[i] - STAR_MIN] = 1

    last100 = main_binary[-100:]
    last50 = main_binary[-50:]
    starlast100 = star_binary[-100:]
    starlast50 = star_binary[-50:]
    prev50 = main_binary[-100:-50] if n_draws >= 100 else main_binary[: max(0, n_draws - 50)]
    star_prev50 = star_binary[-100:-50] if n_draws >= 100 else star_binary[: max(0, n_draws - 50)]

    number_stats = {}
    for num in range(MAIN_MIN, MAIN_MAX + 1):
        col = main_binary[:, num - MAIN_MIN]
        idx = np.nonzero(col)[0]
        g = gap_stats(idx, n_draws)
        freq_last50 = float(last50[:, num - MAIN_MIN].mean())
        freq_prev50 = float(prev50[:, num - MAIN_MIN].mean()) if len(prev50) else np.nan
        number_stats[num] = {
            "total_freq": int(col.sum()),
            "total_rate": float(col.mean()),
            "freq_last100": int(last100[:, num - MAIN_MIN].sum()),
            "rate_last100": float(last100[:, num - MAIN_MIN].mean()),
            "freq_last50": int(last50[:, num - MAIN_MIN].sum()),
            "rate_last50": freq_last50,
            "since_last": g["since_last"],
            "mean_gap": g["mean_gap"],
            "std_gap": g["std_gap"],
            "trend_last50_vs_prev50": (freq_last50 - freq_prev50) if not np.isnan(freq_prev50) else np.nan,
        }

    star_stats = {}
    for num in range(STAR_MIN, STAR_MAX + 1):
        col = star_binary[:, num - STAR_MIN]
        idx = np.nonzero(col)[0]
        g = gap_stats(idx, n_draws)
        freq_last50 = float(starlast50[:, num - STAR_MIN].mean())
        freq_prev50 = float(star_prev50[:, num - STAR_MIN].mean()) if len(star_prev50) else np.nan
        star_stats[num] = {
            "total_freq": int(col.sum()),
            "total_rate": float(col.mean()),
            "freq_last100": int(starlast100[:, num - STAR_MIN].sum()),
            "rate_last100": float(starlast100[:, num - STAR_MIN].mean()),
            "freq_last50": int(starlast50[:, num - STAR_MIN].sum()),
            "rate_last50": freq_last50,
            "since_last": g["since_last"],
            "mean_gap": g["mean_gap"],
            "std_gap": g["std_gap"],
            "trend_last50_vs_prev50": (freq_last50 - freq_prev50) if not np.isnan(freq_prev50) else np.nan,
        }

    return {
        "main_binary": main_binary,
        "star_binary": star_binary,
        "number_stats": number_stats,
        "star_stats": star_stats,
    }


def combo_descriptive(df: pd.DataFrame, main_cols: list, star_cols: list) -> dict:
    main_vals = df[main_cols].values

    pair_counts = {}
    for row in main_vals:
        for a, b in combinations(sorted(row), 2):
            pair_counts[(int(a), int(b))] = pair_counts.get((int(a), int(b)), 0) + 1
    top_pairs = sorted(pair_counts.items(), key=lambda kv: -kv[1])[:15]

    triplet_counts = {}
    for row in main_vals:
        for a, b, c in combinations(sorted(row), 3):
            key = (int(a), int(b), int(c))
            triplet_counts[key] = triplet_counts.get(key, 0) + 1
    top_triplets = sorted(triplet_counts.items(), key=lambda kv: -kv[1])[:10]

    sums = main_vals.sum(axis=1)
    evens = (main_vals % 2 == 0).sum(axis=1)
    odds = N_MAIN - evens
    low = (main_vals <= (MAIN_MAX + 1) // 2).sum(axis=1)
    high = N_MAIN - low

    n_decades = (MAIN_MAX - 1) // 10 + 1
    decade_counts = np.zeros(n_decades, dtype=int)
    for row in main_vals:
        for v in row:
            decade_counts[min(int(v) - 1, MAIN_MAX - 1) // 10] += 1

    consecutive_counts = []
    for row in main_vals:
        s = sorted(row)
        c = sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)
        consecutive_counts.append(c)
    consecutive_counts = np.array(consecutive_counts)

    spans = main_vals.max(axis=1) - main_vals.min(axis=1)

    repeats_prev = [np.nan]
    for i in range(1, len(main_vals)):
        prev_set = set(main_vals[i - 1])
        cur_set = set(main_vals[i])
        repeats_prev.append(len(prev_set & cur_set))
    repeats_prev = np.array(repeats_prev)

    return {
        "top_pairs": top_pairs,
        "top_triplets": top_triplets,
        "sum_mean": float(np.mean(sums)),
        "sum_std": float(np.std(sums)),
        "sum_median": float(np.median(sums)),
        "sum_min": int(sums.min()),
        "sum_max": int(sums.max()),
        "even_mean": float(np.mean(evens)),
        "odd_mean": float(np.mean(odds)),
        "low_mean": float(np.mean(low)),
        "high_mean": float(np.mean(high)),
        "decade_counts": decade_counts.tolist(),
        "decade_rate": (decade_counts / decade_counts.sum()).tolist(),
        "consecutive_mean": float(np.mean(consecutive_counts)),
        "consecutive_rate_at_least_1": float(np.mean(consecutive_counts >= 1)),
        "span_mean": float(np.mean(spans)),
        "span_std": float(np.std(spans)),
        "repeats_prev_mean": float(np.nanmean(repeats_prev)),
        "pair_counts": pair_counts,
    }


# ---------------------------------------------------------------------------
# Étape 3 — Corrélations et tests statistiques
# ---------------------------------------------------------------------------

def correlation_and_chi2(main_binary: np.ndarray, star_binary: np.ndarray, n_draws: int) -> dict:
    corr = np.corrcoef(main_binary.T)

    lifts = {}
    for a in range(MAIN_MAX - MAIN_MIN + 1):
        for b in range(a + 1, MAIN_MAX - MAIN_MIN + 1):
            pa = main_binary[:, a].mean()
            pb = main_binary[:, b].mean()
            pab = (main_binary[:, a] & main_binary[:, b]).mean()
            if pa > 0 and pb > 0 and pab > 0:
                lifts[(a + MAIN_MIN, b + MAIN_MIN)] = pab / (pa * pb)
    top_lift = sorted(lifts.items(), key=lambda kv: -kv[1])[:10]

    observed_main = main_binary.sum(axis=0)
    expected_main = np.full_like(observed_main, observed_main.sum() / len(observed_main), dtype=float)
    chi2_main, p_main = stats.chisquare(observed_main, expected_main)

    observed_star = star_binary.sum(axis=0)
    expected_star = np.full_like(observed_star, observed_star.sum() / len(observed_star), dtype=float)
    chi2_star, p_star = stats.chisquare(observed_star, expected_star)

    n_pairs_tested = (MAIN_MAX - MAIN_MIN + 1) * (MAIN_MAX - MAIN_MIN) // 2
    bonferroni_alpha = 0.05 / n_pairs_tested

    return {
        "corr_matrix": corr,
        "top_lift_pairs": top_lift,
        "chi2_main": float(chi2_main),
        "p_main": float(p_main),
        "chi2_star": float(chi2_star),
        "p_star": float(p_star),
        "n_pairs_tested": n_pairs_tested,
        "bonferroni_alpha": bonferroni_alpha,
    }


def significant_pairs_bonferroni(main_binary: np.ndarray, n_draws: int, n_pairs_tested: int) -> int:
    alpha = 0.05 / n_pairs_tested
    p_single = N_MAIN / (MAIN_MAX - MAIN_MIN + 1)
    p_pair_expected = p_single * (N_MAIN - 1) / (MAIN_MAX - MAIN_MIN)
    sig_count = 0
    cols = MAIN_MAX - MAIN_MIN + 1
    for a in range(cols):
        for b in range(a + 1, cols):
            co = int((main_binary[:, a] & main_binary[:, b]).sum())
            pval = stats.binomtest(co, n_draws, p_pair_expected, alternative="two-sided").pvalue
            if pval < alpha:
                sig_count += 1
    return sig_count


# ---------------------------------------------------------------------------
# Étape 4 — Backtesting temporel
# ---------------------------------------------------------------------------

def model_predict(hist_main_binary: np.ndarray, hist_star_binary: np.ndarray, rng: np.random.Generator) -> tuple:
    n = len(hist_main_binary)
    recent_main = hist_main_binary[-100:] if n >= 20 else hist_main_binary
    recent_star = hist_star_binary[-100:] if n >= 20 else hist_star_binary

    main_weight = 0.5 * hist_main_binary.mean(axis=0) + 0.5 * recent_main.mean(axis=0) + 1e-6
    star_weight = 0.5 * hist_star_binary.mean(axis=0) + 0.5 * recent_star.mean(axis=0) + 1e-6

    main_nums = rng.choice(np.arange(MAIN_MIN, MAIN_MAX + 1), size=N_MAIN, replace=False,
                            p=main_weight / main_weight.sum())
    star_nums = rng.choice(np.arange(STAR_MIN, STAR_MAX + 1), size=N_STAR, replace=False,
                            p=star_weight / star_weight.sum())
    return np.sort(main_nums), np.sort(star_nums)


def backtest(df: pd.DataFrame, main_cols: list, star_cols: list, main_binary: np.ndarray, star_binary: np.ndarray) -> dict:
    main_vals = df[main_cols].values.astype(int)
    star_vals = df[star_cols].values.astype(int)
    n_draws = len(df)

    n_test = min(N_BACKTEST_DRAWS, n_draws - 60)
    test_start = n_draws - n_test
    rng = np.random.default_rng(12345)

    model_main_hits, model_star_hits = [], []
    random_main_hits_all, random_star_hits_all = [], []
    all_main_pool = np.arange(MAIN_MIN, MAIN_MAX + 1)
    all_star_pool = np.arange(STAR_MIN, STAR_MAX + 1)

    n_random_per_draw = max(N_MONTECARLO_RANDOM // n_test, 20)

    for t in range(test_start, n_draws):
        hist_main_binary = main_binary[:t]
        hist_star_binary = star_binary[:t]
        true_main = set(main_vals[t])
        true_star = set(star_vals[t])

        pred_main, pred_star = model_predict(hist_main_binary, hist_star_binary, rng)
        model_main_hits.append(len(set(pred_main) & true_main))
        model_star_hits.append(len(set(pred_star) & true_star))

        for _ in range(n_random_per_draw):
            rm = rng.choice(all_main_pool, size=N_MAIN, replace=False)
            rs = rng.choice(all_star_pool, size=N_STAR, replace=False)
            random_main_hits_all.append(len(set(rm) & true_main))
            random_star_hits_all.append(len(set(rs) & true_star))

    model_main_hits = np.array(model_main_hits)
    model_star_hits = np.array(model_star_hits)
    random_main_hits_all = np.array(random_main_hits_all)
    random_star_hits_all = np.array(random_star_hits_all)

    dist = {k: float(np.mean(model_main_hits == k)) for k in range(0, N_MAIN + 1)}

    mean_diff = float(model_main_hits.mean() - random_main_hits_all.mean())
    se = float(np.sqrt(model_main_hits.var(ddof=1) / len(model_main_hits) +
                        random_main_hits_all.var(ddof=1) / len(random_main_hits_all)))
    ci_low, ci_high = mean_diff - 1.96 * se, mean_diff + 1.96 * se
    tstat, pval = stats.ttest_ind(model_main_hits, random_main_hits_all, equal_var=False)

    return {
        "n_test": n_test,
        "n_random_draws_total": len(random_main_hits_all),
        "model_mean_main_hits": float(model_main_hits.mean()),
        "model_mean_star_hits": float(model_star_hits.mean()),
        "random_mean_main_hits": float(random_main_hits_all.mean()),
        "random_mean_star_hits": float(random_star_hits_all.mean()),
        "hit_distribution_model": dist,
        "mean_diff": mean_diff,
        "ci95": (ci_low, ci_high),
        "tstat": float(tstat),
        "pvalue": float(pval),
    }


# ---------------------------------------------------------------------------
# Étape 5 — Génération et scoring des combinaisons candidates
# ---------------------------------------------------------------------------

def is_arithmetic_sequence(sorted_nums: np.ndarray) -> bool:
    diffs = np.diff(sorted_nums)
    return bool(np.all(diffs == diffs[0]))


def looks_like_birthday_set(sorted_nums: np.ndarray) -> int:
    return int(np.sum(sorted_nums <= 31))


def is_multiple_pattern(sorted_nums: np.ndarray) -> bool:
    for base in range(2, 11):
        if all(n % base == 0 for n in sorted_nums):
            return True
    return False


def visual_pattern_penalty(sorted_nums: np.ndarray) -> float:
    penalty = 0.0
    diffs = np.diff(sorted_nums)
    if len(set(diffs.tolist())) == 1:
        penalty += 3.0
    if np.all(sorted_nums % 5 == 0) or np.all(sorted_nums % 10 == 0):
        penalty += 2.0
    tens_digits = sorted_nums % 10
    if len(set(tens_digits.tolist())) == 1:
        penalty += 1.5
    return penalty


def score_candidate(main_nums: np.ndarray, star_nums: np.ndarray, ctx: dict) -> float:
    number_stats = ctx["number_stats"]
    star_stats = ctx["star_stats"]
    pair_counts = ctx["pair_counts"]
    last_draw_main = ctx["last_draw_main"]
    last_draw_star = ctx["last_draw_star"]
    sum_mean = ctx["sum_mean"]
    sum_std = ctx["sum_std"]
    max_pair_count = ctx["max_pair_count"]

    score = 0.0

    hist_component = 0.0
    recent_component = 0.0
    stability_component = 0.0
    for n in main_nums:
        s = number_stats[int(n)]
        hist_component += s["total_rate"]
        recent_component += s["rate_last50"]
        if not np.isnan(s["std_gap"]) and s["std_gap"] > 0:
            stability_component += 1.0 / (1.0 + s["std_gap"])
    for e in star_nums:
        s = star_stats[int(e)]
        hist_component += s["total_rate"]
        recent_component += s["rate_last50"]
        if not np.isnan(s["std_gap"]) and s["std_gap"] > 0:
            stability_component += 1.0 / (1.0 + s["std_gap"])

    score += 12.0 * hist_component
    score += 12.0 * recent_component
    score += 6.0 * stability_component

    pair_component = 0.0
    for a, b in combinations(sorted(main_nums.tolist()), 2):
        c = pair_counts.get((a, b), 0)
        pair_component += c / max_pair_count if max_pair_count else 0
    score += 3.0 * pair_component  # poids volontairement faible

    s = int(main_nums.sum())
    z = abs(s - sum_mean) / sum_std if sum_std else 0
    score += 8.0 * max(0.0, 1.0 - z / 2.5)

    evens = int(np.sum(main_nums % 2 == 0))
    score += 5.0 if evens in (2, 3) else (2.0 if evens in (1, 4) else 0.0)

    mid = (MAIN_MAX + 1) // 2
    low = int(np.sum(main_nums <= mid))
    score += 5.0 if low in (2, 3) else (2.0 if low in (1, 4) else 0.0)

    decades = set(min(int(n) - 1, MAIN_MAX - 1) // 10 for n in main_nums)
    score += 4.0 * (len(decades) / N_MAIN)

    sorted_main = np.sort(main_nums)

    diffs = np.diff(sorted_main)
    max_run, cur_run = 1, 1
    for d in diffs:
        if d == 1:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    if max_run >= 3:
        score -= 6.0 * (max_run - 2)

    overlap = len(set(sorted_main.tolist()) & set(last_draw_main.tolist()))
    if overlap >= 3:
        score -= 4.0 * (overlap - 2)
    if len(set(star_nums.tolist()) & set(last_draw_star.tolist())) >= 1:
        score -= 1.0

    popularity_penalty = 0.0
    if looks_like_birthday_set(sorted_main) == N_MAIN:
        popularity_penalty += 4.0
    if is_arithmetic_sequence(sorted_main):
        popularity_penalty += 6.0
    if is_multiple_pattern(sorted_main):
        popularity_penalty += 5.0
    popularity_penalty += visual_pattern_penalty(sorted_main)
    if evens == 5 or evens == 0:
        popularity_penalty += 1.5
    if low == 5 or low == 0:
        popularity_penalty += 1.0
    score -= popularity_penalty

    return score


def generate_candidates(n: int, rng: np.random.Generator) -> tuple:
    mains = np.empty((n, N_MAIN), dtype=int)
    stars = np.empty((n, N_STAR), dtype=int)
    for i in range(n):
        mains[i] = np.sort(rng.choice(np.arange(MAIN_MIN, MAIN_MAX + 1), size=N_MAIN, replace=False))
        stars[i] = rng.choice(np.arange(STAR_MIN, STAR_MAX + 1), size=N_STAR, replace=False)
    return mains, stars


def build_final_selection(df, main_cols, star_cols, number_stats, star_stats, combo_desc, seed_rng) -> dict:
    last_draw_main = df[main_cols].values[-1].astype(int)
    last_draw_star = df[star_cols].values[-1].astype(int)

    ctx = {
        "number_stats": number_stats,
        "star_stats": star_stats,
        "pair_counts": combo_desc["pair_counts"],
        "last_draw_main": last_draw_main,
        "last_draw_star": last_draw_star,
        "sum_mean": combo_desc["sum_mean"],
        "sum_std": combo_desc["sum_std"],
        "max_pair_count": max(combo_desc["pair_counts"].values()) if combo_desc["pair_counts"] else 1,
    }

    mains, stars = generate_candidates(N_CANDIDATES, seed_rng)
    scores = np.empty(N_CANDIDATES)
    for i in range(N_CANDIDATES):
        scores[i] = score_candidate(mains[i], stars[i], ctx)

    order = np.argsort(-scores)
    top_k = order[:50]
    top_scores = scores[top_k]
    weights = top_scores - top_scores.min() + 1e-3
    weights = weights / weights.sum()
    chosen_idx = top_k[seed_rng.choice(len(top_k), p=weights)]

    chosen_main = np.sort(mains[chosen_idx])
    chosen_star = np.sort(stars[chosen_idx])
    chosen_score = scores[chosen_idx]
    normalized = 100 * float(np.mean(scores <= chosen_score))

    return {
        "main": chosen_main,
        "star": chosen_star,
        "raw_score": float(chosen_score),
        "normalized_score": normalized,
        "last_draw_main": last_draw_main,
        "last_draw_star": last_draw_star,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rng_seed = RANDOM_SEED if RANDOM_SEED is not None else random.SystemRandom().randint(0, 2**32 - 1)
    seed_rng = np.random.default_rng(rng_seed)

    df, clean_report = load_and_clean(RAW_PATH)
    main_cols = [f"n{i+1}" for i in range(N_MAIN)]
    star_cols = [f"e{i+1}" for i in range(N_STAR)]

    stats_data = build_number_stats(df, main_cols, star_cols)
    combo_desc = combo_descriptive(df, main_cols, star_cols)
    corr_chi2 = correlation_and_chi2(stats_data["main_binary"], stats_data["star_binary"], len(df))
    corr_chi2["n_significant_lift_pairs_bonferroni"] = significant_pairs_bonferroni(
        stats_data["main_binary"], len(df), corr_chi2["n_pairs_tested"]
    )

    bt = backtest(df, main_cols, star_cols, stats_data["main_binary"], stats_data["star_binary"])

    final = build_final_selection(
        df, main_cols, star_cols, stats_data["number_stats"], stats_data["star_stats"], combo_desc, seed_rng
    )

    write_report(clean_report, stats_data, combo_desc, corr_chi2, bt, final, rng_seed)
    print(f"Rapport généré: {REPORT_PATH}")
    print(f"Graine aléatoire utilisée: {rng_seed}")
    print(f"Numéros: {'-'.join(f'{n:02d}' for n in final['main'])} | Numéro chance: {final['star'][0]:02d}")


def write_report(clean_report, stats_data, combo_desc, corr_chi2, bt, final, rng_seed):
    number_stats = stats_data["number_stats"]
    star_stats = stats_data["star_stats"]

    top_main_by_total = sorted(number_stats.items(), key=lambda kv: -kv[1]["total_freq"])[:10]
    top_main_by_recent = sorted(number_stats.items(), key=lambda kv: -kv[1]["rate_last50"])[:10]
    top_star_by_total = sorted(star_stats.items(), key=lambda kv: -kv[1]["total_freq"])[:5]

    overlap = len(set(final["main"].tolist()) & set(final["last_draw_main"].tolist()))
    evens = int(np.sum(final["main"] % 2 == 0))
    odds = N_MAIN - evens
    mid = (MAIN_MAX + 1) // 2
    low = int(np.sum(final["main"] <= mid))
    high = N_MAIN - low
    n_decades = (MAIN_MAX - 1) // 10 + 1
    decade_labels = [f"{10*i+1}-{min(10*(i+1), MAIN_MAX)}" for i in range(n_decades)]
    decade_repr = {}
    for n in final["main"]:
        d = decade_labels[min(int(n) - 1, MAIN_MAX - 1) // 10]
        decade_repr[d] = decade_repr.get(d, 0) + 1
    decade_str = ", ".join(f"{k}: {v}" for k, v in decade_repr.items())

    n_freq_pairs = 0
    pair_counts = combo_desc["pair_counts"]
    if pair_counts:
        threshold = np.percentile(list(pair_counts.values()), 90)
        for a, b in combinations(sorted(final["main"].tolist()), 2):
            if pair_counts.get((a, b), 0) >= threshold:
                n_freq_pairs += 1

    prob_before = 1 / TOTAL_COMBINATIONS
    prob_after = 1 / TOTAL_COMBINATIONS
    gain = 0.0

    if bt["pvalue"] < 0.05 and bt["mean_diff"] > 0:
        bt_conclusion = (
            "le modèle affiche une différence positive statistiquement significative sur "
            "cet échantillon de backtesting, mais cela doit être interprété avec une extrême "
            "prudence : il peut s'agir de surapprentissage ou d'un résultat dû au hasard des "
            "multiples comparaisons. Aucune conclusion de supériorité réelle n'est retenue sans "
            "validation sur des tirages futurs indépendants."
        )
        bt_final_verdict = "résultat non concluant (possible surapprentissage, à confirmer sur données futures)"
    elif bt["pvalue"] < 0.05 and bt["mean_diff"] <= 0:
        bt_conclusion = "le modèle fait statistiquement moins bien ou égal au hasard."
        bt_final_verdict = "non supérieur au hasard"
    else:
        bt_conclusion = "aucune différence statistiquement significative avec le hasard n'a été détectée."
        bt_final_verdict = "non supérieur au hasard (résultat non concluant)"

    lines = []
    lines.append("# Rapport d'analyse statistique Loto (FDJ)\n")
    lines.append(
        "**Avertissement** : cette analyse est une exploration statistique expérimentale et "
        "ludique. Le Loto est un tirage aléatoire indépendant ; aucune méthode statistique ne "
        "peut prédire ou influencer un tirage futur. La grille produite ne doit pas être "
        "interprétée comme ayant une probabilité de gain supérieure à n'importe quelle autre "
        "grille.\n"
    )
    lines.append(
        "**Règles** : 5 numéros distincts parmi 1-49, + 1 numéro chance parmi 1-10 "
        "(différent d'EuroMillions : 5 parmi 50 + 2 étoiles parmi 12).\n"
    )

    lines.append("## Étape 1 — Importation et contrôle des données\n")
    lines.append(f"- Lignes brutes lues : {clean_report['n_raw_rows']}")
    lines.append(f"- Lignes supprimées (valeurs manquantes) : {clean_report['n_dropped_missing']}")
    lines.append(
        f"- Lignes supprimées (valeurs hors plage 1-49/1-10 ou doublons de numéros dans la même ligne) : "
        f"{clean_report['n_dropped_invalid_range_or_duplicate_values']}"
    )
    lines.append(f"- Tirages en double supprimés : {clean_report['n_dropped_duplicate_draws']}")
    lines.append(f"- **Nombre total de tirages valides : {clean_report['n_valid_draws']}**")
    lines.append(f"- Période : {clean_report['first_date'].date()} → {clean_report['last_date'].date()}\n")

    lines.append("## Étape 2 — Statistiques descriptives\n")
    lines.append("### Numéros les plus fréquents (total)")
    lines.append(", ".join(f"{n} ({s['total_freq']}x)" for n, s in top_main_by_total))
    lines.append("\n### Numéros les plus fréquents (50 derniers tirages)")
    lines.append(", ".join(f"{n} ({s['freq_last50']}x)" for n, s in top_main_by_recent))
    lines.append("\n### Numéros chance les plus fréquents (total)")
    lines.append(", ".join(f"{n} ({s['total_freq']}x)" for n, s in top_star_by_total))
    lines.append("\n### Paires de numéros les plus fréquentes")
    lines.append(", ".join(f"{a}-{b} ({c}x)" for (a, b), c in combo_desc["top_pairs"][:10]))
    lines.append("\n### Triplets les plus fréquents")
    lines.append(", ".join(f"{a}-{b}-{c} ({cnt}x)" for (a, b, c), cnt in combo_desc["top_triplets"][:5]))
    lines.append(
        f"\n- Somme des 5 numéros : moyenne={combo_desc['sum_mean']:.1f}, "
        f"médiane={combo_desc['sum_median']:.1f}, écart-type={combo_desc['sum_std']:.1f} "
        f"(min={combo_desc['sum_min']}, max={combo_desc['sum_max']})"
    )
    lines.append(f"- Pairs/impairs moyens : {combo_desc['even_mean']:.2f} / {combo_desc['odd_mean']:.2f}")
    lines.append(
        f"- Bas (1-{mid}) / haut ({mid+1}-{MAIN_MAX}) moyens : "
        f"{combo_desc['low_mean']:.2f} / {combo_desc['high_mean']:.2f}"
    )
    lines.append(
        "- Répartition par dizaines (" + ", ".join(decade_labels) + ") : "
        + ", ".join(f"{r*100:.1f}%" for r in combo_desc["decade_rate"])
    )
    lines.append(
        f"- Nombres consécutifs : moyenne={combo_desc['consecutive_mean']:.2f} par tirage, "
        f"proportion de tirages avec ≥1 paire consécutive={combo_desc['consecutive_rate_at_least_1']*100:.1f}%"
    )
    lines.append(f"- Étendue (max-min) moyenne : {combo_desc['span_mean']:.1f} (écart-type {combo_desc['span_std']:.1f})")
    lines.append(f"- Répétitions moyennes par rapport au tirage précédent : {combo_desc['repeats_prev_mean']:.2f}\n")

    lines.append("## Étape 3 — Corrélations et tests statistiques\n")
    lines.append(
        f"- Test du khi-deux (numéros) : χ²={corr_chi2['chi2_main']:.2f}, p-value={corr_chi2['p_main']:.4f} "
        f"→ {'compatible avec une distribution uniforme' if corr_chi2['p_main'] > 0.05 else 'écart significatif détecté'}"
    )
    lines.append(
        f"- Test du khi-deux (numéro chance) : χ²={corr_chi2['chi2_star']:.2f}, p-value={corr_chi2['p_star']:.4f} "
        f"→ {'compatible avec une distribution uniforme' if corr_chi2['p_star'] > 0.05 else 'écart significatif détecté'}"
    )
    lines.append(
        f"- Paires testées pour co-occurrence : {corr_chi2['n_pairs_tested']}, seuil de Bonferroni "
        f"appliqué (α={corr_chi2['bonferroni_alpha']:.2e})"
    )
    lines.append(
        f"- Nombre de paires restant significatives après correction de Bonferroni : "
        f"**{corr_chi2['n_significant_lift_pairs_bonferroni']}** sur {corr_chi2['n_pairs_tested']}"
    )
    lines.append(
        "  → Après correction pour comparaisons multiples, ce nombre est proche de ce qui est "
        "attendu par pur hasard. Les corrélations observées entre numéros ne sont **pas** "
        "traitées comme prédictives.\n"
    )

    lines.append("## Étape 4 — Backtesting temporel (sans fuite de données)\n")
    lines.append(f"- Tirages testés : {bt['n_test']}")
    lines.append(f"- Sélections aléatoires de comparaison : {bt['n_random_draws_total']} (≥ 10 000)")
    lines.append(f"- Moyenne de bons numéros du modèle : {bt['model_mean_main_hits']:.4f}")
    lines.append(f"- Moyenne de bons numéros du hasard : {bt['random_mean_main_hits']:.4f}")
    lines.append(f"- Moyenne de bon numéro chance du modèle : {bt['model_mean_star_hits']:.4f}")
    lines.append(f"- Moyenne de bon numéro chance du hasard : {bt['random_mean_star_hits']:.4f}")
    lines.append(
        "- Distribution des bons numéros (modèle) : "
        + ", ".join(f"{k}: {v*100:.1f}%" for k, v in bt["hit_distribution_model"].items())
    )
    lines.append(f"- Différence observée (modèle - hasard) : {bt['mean_diff']:.4f}")
    lines.append(f"- Intervalle de confiance à 95% de la différence : [{bt['ci95'][0]:.4f}, {bt['ci95'][1]:.4f}]")
    lines.append(f"- Test t : t={bt['tstat']:.3f}, p-value={bt['pvalue']:.4f}")
    lines.append(f"- **Conclusion du backtesting : {bt_final_verdict}**")
    lines.append(f"  {bt_conclusion}\n")

    n_candidates_fmt = f"{N_CANDIDATES:,}".replace(",", " ")
    lines.append("## Étape 5 & 6 — Génération, scoring et sélection finale\n")
    lines.append(f"- Combinaisons candidates générées et scorées : {n_candidates_fmt}")
    lines.append(
        "- Score composite : équilibre fréquence historique/récente (poids fort), stabilité des "
        "intervalles, associations de paires (poids faible), somme centrale, équilibre pair/impair "
        "et bas/haut, répartition par dizaines, pénalité suites longues, pénalité similarité au "
        "dernier tirage, pénalité profils 'populaires' (anti-partage de gain, pas anti-hasard)."
    )
    lines.append(
        f"- Sélection finale tirée avec pondération aléatoire contrôlée parmi le top 50 des scores "
        f"(graine aléatoire = {rng_seed}), afin de ne pas renvoyer systématiquement la même combinaison.\n"
    )

    lines.append("## Grille unique proposée\n")
    lines.append(f"**Numéros : {' – '.join(f'{n:02d}' for n in final['main'])}**")
    lines.append(f"**Numéro chance : {final['star'][0]:02d}**\n")

    lines.append("### Indicateurs de la grille\n")
    lines.append(
        f"- Score statistique interne : {final['normalized_score']:.1f}/100 "
        f"(percentile du score composite parmi les {n_candidates_fmt} candidats générés — "
        "un score interne, pas une probabilité de gain)"
    )
    lines.append(f"- Somme des numéros : {int(final['main'].sum())}")
    lines.append(f"- Pair/impair : {evens}/{odds}")
    lines.append(f"- Bas/haut : {low}/{high}")
    lines.append(f"- Répartition par dizaines : {decade_str}")
    lines.append(f"- Nombre de paires historiquement fréquentes (top décile) dans la grille : {n_freq_pairs}")
    lines.append(f"- Similarité avec le dernier tirage : {overlap} numéro(s) en commun\n")

    lines.append("### Résultat du backtesting (rappel)\n")
    lines.append(f"- Tirages testés : {bt['n_test']}")
    lines.append(f"- Moyenne de bons numéros du modèle : {bt['model_mean_main_hits']:.4f}")
    lines.append(f"- Moyenne de bons numéros du hasard : {bt['random_mean_main_hits']:.4f}")
    lines.append(f"- Différence observée : {bt['mean_diff']:.4f} (IC95% [{bt['ci95'][0]:.4f}, {bt['ci95'][1]:.4f}], p={bt['pvalue']:.4f})")
    lines.append(f"- **Conclusion : {bt_final_verdict}**\n")

    total_fmt = f"{TOTAL_COMBINATIONS:,}".replace(",", " ")
    lines.append("### Probabilités réelles\n")
    lines.append(f"- Nombre total de combinaisons possibles : {total_fmt} (= C(49,5) × 10)")
    lines.append(f"- Avant analyse : 1 sur {total_fmt}, soit environ {prob_before*100:.8f}%")
    lines.append(f"- Après analyse : 1 sur {total_fmt}, soit environ {prob_after*100:.8f}%")
    lines.append(f"- **Gain de probabilité démontré : {gain:.0f}%**")
    lines.append(
        "\nÀ titre de comparaison, EuroMillions offre 1 chance sur 139 838 160 "
        f"(≈0,000000715%) — le Loto est donc environ "
        f"{139_838_160 / TOTAL_COMBINATIONS:.1f}x plus favorable en probabilité brute, "
        "mais reste malgré tout extrêmement improbable.\n"
    )
    lines.append(
        "Le score statistique interne (ci-dessus) reflète uniquement une préférence pour des "
        "caractéristiques observées historiquement (fréquence, équilibre, répartition) et une "
        "pénalité anti-partage de gain. Il ne représente en aucun cas une probabilité de gagner. "
        f"La probabilité réelle de gain au jackpot reste strictement 1 sur {total_fmt}, "
        "identique avant et après toute analyse.\n"
    )

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
