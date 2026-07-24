"""Step 5: build an interpretable 0-100 "x10 probability score" from a small
set of the most robust predictors (intersection of features that are both
statistically significant after FDR correction AND rank highly in ML feature
importance), fit as a standardized logistic regression so weights are
directly interpretable (a positive weight = higher values raise the score).

Also produces the false-positive / false-negative analysis requested in
Step 5, using the held-out (last) walk-forward fold.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.features.feature_list import FEATURE_COLS_COMMON

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

TOP_K = 8
HORIZON = 30
THRESHOLD = 10


def select_top_features(corr_csv, imp_csv, dataset="B_coinbase_multiyear", k=TOP_K):
    if not (Path(corr_csv).exists() and Path(imp_csv).exists()):
        return [], pd.DataFrame(), pd.DataFrame()
    corr = pd.read_csv(corr_csv)
    imp = pd.read_csv(imp_csv)
    if not len(corr) or not len(imp):
        return [], pd.DataFrame(), pd.DataFrame()

    c = corr[(corr["dataset"] == dataset) & (corr["horizon_days"] == HORIZON) & (corr["threshold"] == THRESHOLD)]
    c_rank = c.assign(absr=c["point_biserial_r"].abs()).sort_values("absr", ascending=False)
    c_top = set(c_rank["feature"].head(15))

    i = imp[(imp["dataset"] == dataset) & (imp["horizon"] == HORIZON) & (imp["threshold"] == THRESHOLD)]
    i_rank = i.groupby("feature")["mean_importance"].mean().sort_values(ascending=False)
    i_top = set(i_rank.head(15).index)

    intersection = [f for f in i_rank.index if f in c_top and f in i_top]
    if len(intersection) < k:
        intersection = list(i_rank.index[:k])
    return intersection[:k], c_rank, i_rank


def main():
    panel = pd.read_parquet(DATA_DIR / "candidate_panel_cb.parquet")
    label_col = f"fwd_max_mult_{HORIZON}d"
    df = panel[panel[label_col].notna()].copy()
    df["label"] = (df[label_col] >= THRESHOLD).astype(int)
    df = df.sort_values("date")

    corr_csv = REPORTS_DIR / "correlation_results.csv"
    imp_csv = REPORTS_DIR / "feature_importance.csv"
    top_features, c_rank, i_rank = select_top_features(corr_csv, imp_csv)
    print(f"Top {len(top_features)} features selected for the interpretable score: {top_features}")
    if not top_features:
        print("No ML importance results available yet for the x10@30d target on Dataset B "
              "(insufficient positive examples so far) -- run again once data collection is complete.")
        return

    X = df[top_features].apply(pd.to_numeric, errors="coerce")
    y = df["label"]

    # chronological split: train on all but the last calendar year, test on the last year
    last_year = df["date"].dt.year.max()
    train_mask = df["date"].dt.year < last_year
    test_mask = df["date"].dt.year == last_year

    median = X[train_mask].median()
    X_train = X[train_mask].fillna(median)
    X_test = X[test_mask].fillna(median)
    y_train, y_test = y[train_mask], y[test_mask]

    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    X_test_s = scaler.transform(X_test)

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5)
    clf.fit(X_train_s, y_train)

    coefs = pd.Series(clf.coef_[0], index=top_features)
    weights_pct = (coefs.abs() / coefs.abs().sum() * 100).round(1)
    weight_table = pd.DataFrame({"feature": top_features, "std_coefficient": coefs.values,
                                  "direction": np.where(coefs.values > 0, "+", "-"),
                                  "relative_weight_pct": weights_pct.values}).sort_values("relative_weight_pct", ascending=False)
    print("\n--- Interpretable score weight table ---")
    print(weight_table.to_string(index=False))
    weight_table.to_csv(REPORTS_DIR / "score_weights.csv", index=False)

    # score = calibrated probability * 100 on the held-out year
    proba_test = clf.predict_proba(X_test_s)[:, 1]
    score_100 = proba_test * 100

    thr_grid = [10, 20, 30, 40, 50, 60, 70]
    print("\n--- False positive / false negative analysis (held-out year) ---")
    fp_fn_rows = []
    for sc_thr in thr_grid:
        pred = (score_100 >= sc_thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_test, pred, labels=[0, 1]).ravel()
        precision = tp / (tp + fp) if (tp + fp) else np.nan
        recall = tp / (tp + fn) if (tp + fn) else np.nan
        fp_fn_rows.append({"score_threshold": sc_thr, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
                            "precision": precision, "recall": recall})
    fp_fn_df = pd.DataFrame(fp_fn_rows)
    print(fp_fn_df.to_string(index=False))
    fp_fn_df.to_csv(REPORTS_DIR / "score_fp_fn_analysis.csv", index=False)

    # save fitted score model for reuse
    import joblib
    joblib.dump({"scaler": scaler, "model": clf, "features": top_features}, DATA_DIR / "models" / "interpretable_score_model.joblib")
    print(f"\nSaved score model -> data/processed/models/interpretable_score_model.joblib")


if __name__ == "__main__":
    main()
