"""Step 3 / Step 6 (statistical part): robust correlation analysis between
point-in-time features and the forward x10 (and x5/x20) label, with multiple
hypothesis testing correction to guard against false positives given the
large number of features x horizons tested.

Method:
  - Point-biserial / Spearman correlation between each numeric feature and the
    binary label (label = 1 if forward max multiple over horizon H >= threshold).
  - Benjamini-Hochberg FDR correction across all (feature x horizon x
    threshold) tests, at q=0.10.
  - Reported for both Dataset A (CoinGecko, rich features, 1y) and Dataset B
    (Coinbase, price/volume only, multi-year) where applicable.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.features.feature_list import (
    FEATURE_COLS_COMMON, FEATURE_COLS_A_EXTRA, LABEL_THRESHOLDS, LABEL_HORIZONS,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def run_correlations(panel, feature_cols, dataset_name):
    results = []
    for h in LABEL_HORIZONS:
        col = f"fwd_max_mult_{h}d"
        if col not in panel.columns:
            continue
        valid = panel[panel[col].notna()]
        for thr in LABEL_THRESHOLDS:
            y = (valid[col] >= thr).astype(int)
            if y.sum() < 5:
                continue  # too few positives for a meaningful test
            for feat in feature_cols:
                if feat not in valid.columns:
                    continue
                x = valid[feat]
                mask = x.notna()
                if mask.sum() < 30:
                    continue
                xv, yv = x[mask], y[mask]
                if yv.nunique() < 2 or xv.nunique() < 2:
                    continue
                try:
                    rho, p = stats.pointbiserialr(yv, xv)
                except Exception:
                    continue
                results.append(
                    {
                        "dataset": dataset_name,
                        "horizon_days": h,
                        "threshold": thr,
                        "feature": feat,
                        "n": int(mask.sum()),
                        "n_pos": int(yv.sum()),
                        "point_biserial_r": rho,
                        "p_value": p,
                    }
                )
    return pd.DataFrame(results)


def apply_fdr(df, alpha=0.10):
    if not len(df):
        return df
    reject, p_adj, _, _ = multipletests(df["p_value"].values, alpha=alpha, method="fdr_bh")
    df = df.copy()
    df["p_adj_fdr"] = p_adj
    df["significant_fdr_10pct"] = reject
    return df


def main():
    all_results = []

    pa_path = DATA_DIR / "candidate_panel.parquet"
    if pa_path.exists():
        panel_a = pd.read_parquet(pa_path)
        res_a = run_correlations(panel_a, FEATURE_COLS_COMMON + FEATURE_COLS_A_EXTRA, "A_coingecko_365d")
        all_results.append(res_a)

    pb_path = DATA_DIR / "candidate_panel_cb.parquet"
    if pb_path.exists():
        panel_b = pd.read_parquet(pb_path)
        res_b = run_correlations(panel_b, FEATURE_COLS_COMMON, "B_coinbase_multiyear")
        all_results.append(res_b)

    combined = pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()
    if not len(combined):
        print("No data available yet.")
        return

    combined = apply_fdr(combined, alpha=0.10)
    combined = combined.sort_values(["dataset", "horizon_days", "threshold", "p_adj_fdr"])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "correlation_results.csv"
    combined.to_csv(out_path, index=False)
    print(f"Saved {out_path} ({len(combined)} tests)")

    sig = combined[combined["significant_fdr_10pct"]]
    print(f"\n{len(sig)} / {len(combined)} tests significant after FDR correction (q=0.10)")
    print("\nTop significant features by |r|, x10 threshold, 30d horizon:")
    top = sig[(sig["threshold"] == 10) & (sig["horizon_days"] == 30)].reindex(
        sig[(sig["threshold"] == 10) & (sig["horizon_days"] == 30)]["point_biserial_r"].abs().sort_values(ascending=False).index
    )
    print(top.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
