"""Generate the figures referenced in the final report."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
FIG_DIR = REPORTS_DIR / "figures"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})


def fig_events_per_year():
    conn = get_conn()
    events = pd.read_sql("SELECT * FROM events", conn, parse_dates=["trough_date"])
    conn.close()
    if not len(events):
        return
    events["year"] = events["trough_date"].dt.year
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, source in zip(axes, ["coingecko_365d", "coinbase_full"]):
        sub = events[events["source"] == source]
        if not len(sub):
            continue
        counts = pd.DataFrame({
            "x5-x10": ((sub["multiple"] >= 5) & (sub["multiple"] < 10)).groupby(sub["year"]).sum(),
            "x10-x20": ((sub["multiple"] >= 10) & (sub["multiple"] < 20)).groupby(sub["year"]).sum(),
            "x20-x50": ((sub["multiple"] >= 20) & (sub["multiple"] < 50)).groupby(sub["year"]).sum(),
            "x50+": (sub["multiple"] >= 50).groupby(sub["year"]).sum(),
        }).fillna(0)
        counts.plot(kind="bar", stacked=True, ax=ax, colormap="viridis")
        ax.set_title(f"Rally events by year -- {source}")
        ax.set_xlabel("")
        ax.set_ylabel("# events")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "events_per_year.png")
    plt.close()


def fig_regime_breakdown():
    conn = get_conn()
    events = pd.read_sql("SELECT * FROM events WHERE market_regime_at_trough IS NOT NULL", conn)
    conn.close()
    if not len(events):
        return
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, source in zip(axes, ["coingecko_365d", "coinbase_full"]):
        sub = events[events["source"] == source]
        if not len(sub):
            continue
        sub.groupby("market_regime_at_trough").size().reindex(["bull", "neutral", "bear"]).plot(
            kind="bar", ax=ax, color=["#2ca02c", "#7f7f7f", "#d62728"]
        )
        ax.set_title(f"Events (>=5x) by regime -- {source}")
        ax.set_ylabel("# events")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "events_by_regime.png")
    plt.close()


def fig_capture_curve():
    path = REPORTS_DIR / "timing_capture_rates.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    hold_days = [1, 2, 3, 7, 14, 30, 60, 90]
    medians = [df[f"capture_{h}d"].median() for h in hold_days if f"capture_{h}d" in df]
    means = [df[f"capture_{h}d"].mean() for h in hold_days if f"capture_{h}d" in df]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(hold_days, medians, marker="o", label="median")
    ax.plot(hold_days, means, marker="s", label="mean")
    ax.set_xlabel("Holding period since trough (days)")
    ax.set_ylabel("Fraction of eventual peak gain captured")
    ax.set_title("How fast is the x10+ move captured?")
    ax.axhline(1.0, color="gray", linestyle=":", linewidth=1)
    ax.legend()
    plt.tight_layout()
    plt.savefig(FIG_DIR / "capture_rate_curve.png")
    plt.close()


def fig_entry_rules():
    path = REPORTS_DIR / "timing_entry_rules.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    df.groupby("rule")["pct_of_full_trough_to_peak_move_captured"].median().sort_values().plot(
        kind="barh", ax=axes[0], color="#1f77b4"
    )
    axes[0].set_title("Median % of full move captured, by entry rule")
    df.groupby("rule")["days_after_trough"].median().sort_values().plot(
        kind="barh", ax=axes[1], color="#ff7f0e"
    )
    axes[1].set_title("Median delay after trough, by entry rule (days)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "entry_rules_comparison.png")
    plt.close()


def fig_feature_importance():
    path = REPORTS_DIR / "feature_importance.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    sub = df[(df["dataset"] == "B_coinbase_multiyear") & (df["threshold"] == 10)]
    if not len(sub):
        sub = df
    top = sub.groupby("feature")["mean_importance"].mean().sort_values(ascending=False).head(15)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    top.sort_values().plot(kind="barh", ax=ax, color="#2ca02c")
    ax.set_title("Top 15 features by mean ML importance (x10 @ 30d, Dataset B)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "feature_importance.png")
    plt.close()


def fig_ml_comparison():
    path = REPORTS_DIR / "ml_results.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    sub = df[(df["dataset"] == "B_coinbase_multiyear") & (df["threshold"] == 10)]
    if not len(sub):
        return
    summary = sub.groupby("model")[["roc_auc", "pr_auc", "precision_top10pct"]].mean().sort_values("pr_auc", ascending=False)
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    summary.plot(kind="bar", ax=ax)
    ax.set_title("Model comparison -- x10 @ 30d (Dataset B, walk-forward)")
    ax.set_ylabel("score")
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "ml_model_comparison.png")
    plt.close()


def fig_backtest_equity():
    path = REPORTS_DIR / "backtest_trades_best.csv"
    if not path.exists():
        return
    df = pd.read_csv(path, parse_dates=["exit_date"]).sort_values("exit_date")
    if not len(df):
        return
    bet_fraction = 0.05
    equity = [1.0]
    for ret in df["trade_return_pct"]:
        equity.append(equity[-1] * (1 + bet_fraction * ret))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(df["exit_date"], equity[1:])
    ax.set_yscale("log")
    ax.set_title("Backtest equity curve (fixed-fractional 5% sizing, log scale)")
    ax.set_ylabel("Equity multiple")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "backtest_equity_curve.png")
    plt.close()


def fig_backtest_grid():
    path = REPORTS_DIR / "backtest_grid.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    df.plot(x="score_threshold", y="win_rate", ax=axes[0], marker="o", legend=False)
    axes[0].set_title("Win rate vs score threshold")
    df.plot(x="score_threshold", y="sharpe_annualized", ax=axes[1], marker="o", legend=False, color="#d62728")
    axes[1].set_title("Sharpe vs score threshold")
    df.plot(x="score_threshold", y="n_trades", ax=axes[2], marker="o", legend=False, color="#2ca02c")
    axes[2].set_title("# trades vs score threshold")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "backtest_threshold_grid.png")
    plt.close()


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for fn in [fig_events_per_year, fig_regime_breakdown, fig_capture_curve, fig_entry_rules,
               fig_feature_importance, fig_ml_comparison, fig_backtest_equity, fig_backtest_grid]:
        try:
            fn()
            print(f"OK: {fn.__name__}")
        except Exception as e:
            print(f"SKIPPED {fn.__name__}: {e}")


if __name__ == "__main__":
    main()
