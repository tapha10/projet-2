"""Step 4: train & compare ML models (walk-forward, no look-ahead) to predict
whether a coin's forward max multiple over horizon H will reach a given
threshold (5x / 10x / 20x), and rank feature importance.

Walk-forward protocol (chosen specifically to avoid look-ahead bias):
  - Candidates are sorted by date.
  - Dataset B (multi-year): expanding-window walk-forward, N folds by
    calendar year -- train on all data up to year Y, test on year Y+1.
  - Dataset A (single year): one chronological 70/30 split (too short a span
    for multi-fold walk-forward), used as a secondary confirmation, not the
    headline result.
  - Feature values are NEVER computed using information after the candidate
    date; this was already enforced in the feature engineering step. The
    walk-forward split additionally ensures the MODEL never trains on data
    that is chronologically after what it's tested on.

Class imbalance (x10 events are rare) is handled via class-weighting /
scale_pos_weight rather than resampling, to keep predicted probabilities
interpretable for the scoring step.
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score, precision_score, recall_score, f1_score
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostClassifier
import joblib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.features.feature_list import FEATURE_COLS_COMMON, FEATURE_COLS_A_EXTRA

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
MODELS_DIR = DATA_DIR / "models"


def make_models(pos_weight):
    return {
        "logreg": LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5),
        "random_forest": RandomForestClassifier(
            n_estimators=400, max_depth=6, min_samples_leaf=10, class_weight="balanced_subsample",
            random_state=42, n_jobs=-1,
        ),
        "xgboost": xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=pos_weight, eval_metric="logloss", random_state=42, n_jobs=-1,
        ),
        "lightgbm": lgb.LGBMClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            class_weight="balanced", random_state=42, n_jobs=-1, verbosity=-1,
        ),
        "catboost": CatBoostClassifier(
            iterations=300, depth=4, learning_rate=0.05, auto_class_weights="Balanced",
            random_seed=42, verbose=False,
        ),
    }


def eval_fold(model, X_train, y_train, X_test, y_test, feature_cols):
    if y_train.sum() < 2 or y_test.sum() < 1 or y_train.nunique() < 2:
        return None
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)

    metrics = {
        "n_test": len(y_test),
        "n_pos_test": int(y_test.sum()),
        "roc_auc": roc_auc_score(y_test, proba) if y_test.nunique() > 1 else np.nan,
        "pr_auc": average_precision_score(y_test, proba),
        "precision_at_0.5": precision_score(y_test, pred, zero_division=0),
        "recall_at_0.5": recall_score(y_test, pred, zero_division=0),
        "f1_at_0.5": f1_score(y_test, pred, zero_division=0),
    }

    # precision within the top-decile of predicted scores (realistic trading filter)
    k = max(1, int(len(proba) * 0.10))
    top_idx = np.argsort(-proba)[:k]
    metrics["precision_top10pct"] = y_test.values[top_idx].mean()
    metrics["base_rate"] = y_test.mean()
    return metrics, model


def get_feature_importance(model_name, model, feature_cols):
    if model_name == "logreg":
        coefs = model.coef_[0]
        return dict(zip(feature_cols, np.abs(coefs)))
    if hasattr(model, "feature_importances_"):
        return dict(zip(feature_cols, model.feature_importances_))
    return {}


def run(panel, feature_cols, dataset_name, horizon, threshold, fold_mode="expanding_year"):
    label_col = f"fwd_max_mult_{horizon}d"
    df = panel[panel[label_col].notna()].copy()
    df["label"] = (df[label_col] >= threshold).astype(int)
    df = df.sort_values("date")

    X_all = df[feature_cols].copy()
    for c in feature_cols:
        X_all[c] = pd.to_numeric(X_all[c], errors="coerce")

    n_pos = df["label"].sum()
    print(f"\n=== {dataset_name} | H={horizon}d | x{threshold} | n={len(df)} pos={n_pos} ({n_pos/len(df):.3%}) ===")
    if n_pos < 8:
        print("Too few positive examples for reliable walk-forward evaluation -- skipping ML, "
              "will be reported as a data-availability limitation instead.")
        return pd.DataFrame(), {}

    if fold_mode == "expanding_year" and df["date"].dt.year.nunique() >= 3:
        years = sorted(df["date"].dt.year.unique())
        folds = [(years[0], y, y) for y in years[2:]]  # train up to y-1, test on year y
        splits = []
        for train_end_year, test_year, _ in folds:
            train_mask = df["date"].dt.year < test_year
            test_mask = df["date"].dt.year == test_year
            splits.append((train_mask, test_mask, f"test_year={test_year}"))
    else:
        cut = df["date"].quantile(0.7)
        train_mask = df["date"] <= cut
        test_mask = df["date"] > cut
        splits = [(train_mask, test_mask, "holdout_30pct")]

    results = []
    fitted_models = {}
    imp_accum = {}
    for train_mask, test_mask, label in splits:
        X_train, y_train = X_all[train_mask], df.loc[train_mask, "label"]
        X_test, y_test = X_all[test_mask], df.loc[test_mask, "label"]
        if len(X_train) < 50 or len(X_test) < 10:
            continue
        median = X_train.median()
        X_train_f = X_train.fillna(median)
        X_test_f = X_test.fillna(median)

        pos_weight = max(1.0, (y_train == 0).sum() / max(1, (y_train == 1).sum()))
        models = make_models(pos_weight)

        scaler = StandardScaler().fit(X_train_f)
        X_train_s = pd.DataFrame(scaler.transform(X_train_f), columns=feature_cols, index=X_train_f.index)
        X_test_s = pd.DataFrame(scaler.transform(X_test_f), columns=feature_cols, index=X_test_f.index)

        for name, model in models.items():
            Xtr = X_train_s if name == "logreg" else X_train_f
            Xte = X_test_s if name == "logreg" else X_test_f
            out = eval_fold(model, Xtr, y_train, Xte, y_test, feature_cols)
            if out is None:
                continue
            metrics, fitted = out
            metrics.update({"model": name, "fold": label, "dataset": dataset_name, "horizon": horizon, "threshold": threshold})
            results.append(metrics)
            fitted_models[(name, label)] = fitted
            imp = get_feature_importance(name, fitted, feature_cols)
            for f, v in imp.items():
                imp_accum.setdefault((name, f), []).append(v)

    res_df = pd.DataFrame(results)
    imp_rows = [
        {"model": k[0], "feature": k[1], "mean_importance": np.mean(v), "dataset": dataset_name,
         "horizon": horizon, "threshold": threshold}
        for k, v in imp_accum.items()
    ]
    imp_df = pd.DataFrame(imp_rows)

    if len(res_df):
        summary = res_df.groupby("model")[["roc_auc", "pr_auc", "precision_top10pct", "f1_at_0.5"]].mean()
        print(summary.sort_values("pr_auc", ascending=False).to_string())

    return res_df, imp_df, fitted_models


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    all_res, all_imp = [], []

    pb = DATA_DIR / "candidate_panel_cb.parquet"
    if pb.exists():
        panel_b = pd.read_parquet(pb)
        for thr in [5, 10]:
            res, imp, fitted = run(panel_b, FEATURE_COLS_COMMON, "B_coinbase_multiyear", 30, thr)
            if len(res):
                all_res.append(res)
                all_imp.append(imp)
                # persist last-fold model of the best-PR-AUC type for the scoring step
                if thr == 10:
                    best_model_name = res.groupby("model")["pr_auc"].mean().idxmax()
                    last_fold_label = res["fold"].iloc[-1]
                    joblib.dump(fitted.get((best_model_name, last_fold_label)),
                                MODELS_DIR / f"best_model_B_h30_x{thr}.joblib")
                    with open(MODELS_DIR / f"best_model_B_h30_x{thr}.json", "w") as f:
                        json.dump({"model_name": best_model_name, "features": FEATURE_COLS_COMMON}, f)

    pa = DATA_DIR / "candidate_panel.parquet"
    if pa.exists():
        panel_a = pd.read_parquet(pa)
        for thr in [5, 10]:
            res, imp, fitted = run(panel_a, FEATURE_COLS_COMMON + FEATURE_COLS_A_EXTRA, "A_coingecko_365d", 30, thr)
            if len(res):
                all_res.append(res)
                all_imp.append(imp)

    if all_res:
        res_all = pd.concat(all_res, ignore_index=True)
        imp_all = pd.concat(all_imp, ignore_index=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        res_all.to_csv(REPORTS_DIR / "ml_results.csv", index=False)
        imp_all.to_csv(REPORTS_DIR / "feature_importance.csv", index=False)
        print(f"\nSaved {REPORTS_DIR / 'ml_results.csv'} and feature_importance.csv")
    else:
        print("No ML results produced (insufficient positive examples in available data).")


if __name__ == "__main__":
    main()
