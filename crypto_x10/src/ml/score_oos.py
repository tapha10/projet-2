"""Generate an out-of-sample (walk-forward) probability score for every
Dataset B candidate: for each test year Y, the score is produced by a model
trained ONLY on years < Y, so scores used in the backtest are never
contaminated by future information (necessary to satisfy Step 10's no
look-ahead requirement).

Uses the best-performing model type found in train.py (by mean PR-AUC across
folds) for the x10 @ 30d target, refit per-fold.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.features.feature_list import FEATURE_COLS_COMMON

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

HORIZON = 30
THRESHOLD = 10


def main():
    panel = pd.read_parquet(DATA_DIR / "candidate_panel_cb.parquet")
    label_col = f"fwd_max_mult_{HORIZON}d"
    df = panel[panel[label_col].notna()].copy()
    df["label"] = (df[label_col] >= THRESHOLD).astype(int)
    df = df.sort_values("date").reset_index(drop=True)

    X_all = df[FEATURE_COLS_COMMON].apply(pd.to_numeric, errors="coerce")
    years = sorted(df["date"].dt.year.unique())
    test_years = years[2:]  # need >=2 years of history to train first fold

    df["oos_score"] = np.nan
    for test_year in test_years:
        train_mask = df["date"].dt.year < test_year
        test_mask = df["date"].dt.year == test_year
        y_train = df.loc[train_mask, "label"]
        if y_train.sum() < 5:
            continue
        X_train = X_all[train_mask]
        X_test = X_all[test_mask]
        median = X_train.median()
        X_train_f = X_train.fillna(median)
        X_test_f = X_test.fillna(median)

        pos_weight = max(1.0, (y_train == 0).sum() / max(1, y_train.sum()))
        model = lgb.LGBMClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            class_weight="balanced", random_state=42, n_jobs=-1, verbosity=-1,
        )
        model.fit(X_train_f, y_train)
        proba = model.predict_proba(X_test_f)[:, 1]
        df.loc[test_mask, "oos_score"] = proba
        print(f"test_year={test_year}: train_n={len(X_train)} (pos={y_train.sum()}), test_n={len(X_test)}, "
              f"mean_score={proba.mean():.4f}")

    scored = df[df["oos_score"].notna()][["coin_id", "date", "price", "oos_score", "label", label_col]]
    scored.to_parquet(DATA_DIR / "oos_scored_panel_B.parquet", index=False)
    print(f"\nSaved {len(scored)} out-of-sample scored candidates -> data/processed/oos_scored_panel_B.parquet")
    print(f"Score distribution:\n{scored['oos_score'].describe()}")


if __name__ == "__main__":
    main()
