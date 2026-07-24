"""Step 10: walk-forward backtest with no look-ahead bias.

No-look-ahead guarantees:
  - Trading signal (oos_score) for date t comes from a model trained only on
    data strictly before t's calendar year (see src/ml/score_oos.py).
  - Entry execution price is the NEXT day's OPEN after the signal date (t+1),
    never the signal day's own close.
  - Exit rules only use information available at or before the exit day
    (stop-loss / take-profit / trailing-stop / max-holding-period), evaluated
    walking forward day by day on realised OHLC data.

Position sizing / portfolio simulation (explicitly a simplification, documented):
  - Fixed-fractional sizing: each trade risks `bet_fraction` of the running
    bankroll, compounded sequentially in order of trade EXIT date. This is a
    standard simplification for strategy studies; it does not model exact
    concurrent capital lock-up across overlapping open positions.
  - One open position per coin at a time (a new signal on a coin already held
    is ignored until the current position closes).

Exit rule (documented, applied uniformly -- see reports/timing_* for the
analysis that motivated these parameters):
  - Hard stop-loss at -25% from entry.
  - Take-profit ladder: sell 25% of the position at 2x, 25% at 5x, 25% at 10x.
  - The remaining runner (25%) is protected by a trailing stop of 30% below
    the running peak price, only ARMED once the position is up >= 2x.
  - Forced exit (mark remaining at close) after `max_hold_days` (default 90).
"""
import sys
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

STOP_LOSS = 0.25
TP_LADDER = [(2.0, 0.25), (5.0, 0.25), (10.0, 0.25)]  # (multiple, fraction of ORIGINAL position to sell)
TRAILING_ARM_MULT = 2.0
TRAILING_DRAWDOWN = 0.30
# The timing analysis (src/analysis/timing.py) found that x10+ rallies only have
# ~33% of their eventual gain captured by day 90 (median) -- most of the move
# happens later. MAX_HOLD_DAYS is set well beyond the ML label horizon (90d) so
# the backtest doesn't systematically truncate winners before they've played out.
MAX_HOLD_DAYS = 180


def load_ohlc(conn):
    df = pd.read_sql(
        "SELECT coin_id, date, open, high, low, close FROM cb_price_history ORDER BY coin_id, date",
        conn, parse_dates=["date"],
    )
    return {cid: g.reset_index(drop=True) for cid, g in df.groupby("coin_id")}


def simulate_trade(series, entry_idx):
    """series: this coin's OHLC dataframe. entry_idx: row index of the entry (T+1 open)."""
    if entry_idx >= len(series):
        return None
    entry_price = series["open"].iloc[entry_idx]
    if pd.isna(entry_price) or entry_price <= 0:
        return None

    remaining_frac = 1.0
    realized = 0.0  # weighted sum of (fraction_sold * exit_multiple)
    running_peak = entry_price
    trailing_armed = False
    tp_hit = {m: False for m, _ in TP_LADDER}
    exit_date = None
    exit_reason = None

    for offset in range(0, MAX_HOLD_DAYS):
        idx = entry_idx + offset
        if idx >= len(series):
            exit_date = series["date"].iloc[-1]
            exit_reason = "data_end"
            realized += remaining_frac * (series["close"].iloc[-1] / entry_price)
            remaining_frac = 0
            break
        row = series.iloc[idx]
        low, high, close = row["low"], row["high"], row["close"]
        running_peak = max(running_peak, high)

        # stop-loss check first (conservative: worst-case ordering within the day)
        if low <= entry_price * (1 - STOP_LOSS):
            realized += remaining_frac * (1 - STOP_LOSS)
            remaining_frac = 0
            exit_date, exit_reason = row["date"], "stop_loss"
            break

        # take-profit ladder
        for mult, frac in TP_LADDER:
            if not tp_hit[mult] and high >= entry_price * mult and remaining_frac > 0:
                sell_frac = min(frac, remaining_frac)
                realized += sell_frac * mult
                remaining_frac -= sell_frac
                tp_hit[mult] = True

        if running_peak / entry_price >= TRAILING_ARM_MULT:
            trailing_armed = True

        if trailing_armed and remaining_frac > 0:
            trail_stop_price = running_peak * (1 - TRAILING_DRAWDOWN)
            if low <= trail_stop_price:
                realized += remaining_frac * (trail_stop_price / entry_price)
                remaining_frac = 0
                exit_date, exit_reason = row["date"], "trailing_stop"
                break

        if remaining_frac <= 1e-9:
            exit_date, exit_reason = row["date"], "fully_sold_tp_ladder"
            break

    if exit_date is None:
        idx = min(entry_idx + MAX_HOLD_DAYS - 1, len(series) - 1)
        realized += remaining_frac * (series["close"].iloc[idx] / entry_price)
        exit_date = series["date"].iloc[idx]
        exit_reason = "max_hold"

    hold_days = (exit_date - series["date"].iloc[entry_idx]).days
    return {
        "entry_date": series["date"].iloc[entry_idx],
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_reason": exit_reason,
        "realized_multiple": realized,
        "trade_return_pct": realized - 1,
        "hold_days": hold_days,
    }


def run_backtest(score_threshold, bet_fraction=0.05):
    conn = get_conn()
    ohlc = load_ohlc(conn)
    scored = pd.read_parquet(DATA_DIR / "oos_scored_panel_B.parquet")
    scored = scored.sort_values("date")

    signals = scored[scored["oos_score"] >= score_threshold]
    trades = []
    open_coins = {}  # coin_id -> exit_date of currently open position

    for row in signals.itertuples():
        coin_id, sig_date = row.coin_id, row.date
        if coin_id in open_coins and open_coins[coin_id] > sig_date:
            continue
        series = ohlc.get(coin_id)
        if series is None:
            continue
        idx_arr = series.index[series["date"] > sig_date]
        if not len(idx_arr):
            continue
        entry_idx = idx_arr[0]  # first trading day strictly after the signal date -> T+1 open
        trade = simulate_trade(series, entry_idx)
        if trade is None:
            continue
        trade["coin_id"] = coin_id
        trade["signal_date"] = sig_date
        trade["signal_score"] = row.oos_score
        trades.append(trade)
        open_coins[coin_id] = trade["exit_date"]

    conn.close()
    if not trades:
        return pd.DataFrame(columns=["coin_id", "signal_date", "signal_score", "entry_date", "entry_price",
                                      "exit_date", "exit_reason", "realized_multiple", "trade_return_pct", "hold_days"])
    trades_df = pd.DataFrame(trades).sort_values("exit_date").reset_index(drop=True)
    return trades_df


EMPTY_METRICS = {
    "n_trades": 0, "win_rate": np.nan, "mean_return_pct": np.nan, "median_return_pct": np.nan,
    "max_drawdown_pct": np.nan, "profit_factor": np.nan, "sharpe_annualized": np.nan,
    "expectancy_pct_per_trade": np.nan, "trades_per_week": np.nan, "cagr_pct": np.nan,
    "final_equity_multiple": np.nan,
}


def compute_metrics(trades_df, bet_fraction=0.05):
    if not len(trades_df):
        return dict(EMPTY_METRICS)
    r = trades_df["trade_return_pct"]
    equity = [1.0]
    for ret in r:
        equity.append(equity[-1] * (1 + bet_fraction * ret))
    equity = np.array(equity[1:])
    trades_df = trades_df.copy()
    trades_df["equity_after"] = equity

    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()

    wins = r[r > 0]
    losses = r[r <= 0]
    win_rate = (r > 0).mean()
    profit_factor = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
    expectancy = r.mean()

    span_days = (trades_df["exit_date"].max() - trades_df["signal_date"].min()).days
    span_weeks = max(span_days / 7, 1)
    trades_per_week = len(trades_df) / span_weeks

    eq_series = pd.Series(equity, index=pd.to_datetime(trades_df["exit_date"]))
    eq_weekly = eq_series.resample("W").last().ffill()
    weekly_returns = eq_weekly.pct_change().dropna()
    sharpe = (weekly_returns.mean() / weekly_returns.std() * np.sqrt(52)) if weekly_returns.std() > 0 else np.nan

    total_years = span_days / 365.25 if span_days > 0 else np.nan
    cagr = equity[-1] ** (1 / total_years) - 1 if total_years and total_years > 0 else np.nan

    return {
        "n_trades": len(trades_df),
        "win_rate": win_rate,
        "mean_return_pct": r.mean(),
        "median_return_pct": r.median(),
        "max_drawdown_pct": max_dd,
        "profit_factor": profit_factor,
        "sharpe_annualized": sharpe,
        "expectancy_pct_per_trade": expectancy,
        "trades_per_week": trades_per_week,
        "cagr_pct": cagr,
        "final_equity_multiple": equity[-1],
    }


def main():
    # thresholds chosen from the empirical OOS score distribution (base rate
    # ~0.13% x10@90d -> most probability mass is far below 0.5; a fixed
    # 0.3/0.5/... grid as one might use for a balanced classifier would select
    # almost no trades here)
    grid = [0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3]
    rows = []
    all_trades = {}
    for thr in grid:
        trades_df = run_backtest(thr)
        m = compute_metrics(trades_df)
        m["score_threshold"] = thr
        rows.append(m)
        all_trades[thr] = trades_df
        print(f"threshold={thr}: {m}")

    grid_df = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    grid_df.to_csv(REPORTS_DIR / "backtest_grid.csv", index=False)

    # save trade log for the threshold with the best Sharpe among those with >=20 trades
    valid = grid_df[grid_df["n_trades"] >= 20]
    if len(valid):
        best_thr = valid.loc[valid["sharpe_annualized"].idxmax(), "score_threshold"]
    else:
        best_thr = grid_df.loc[grid_df["n_trades"].idxmax(), "score_threshold"]
    all_trades[best_thr].to_csv(REPORTS_DIR / "backtest_trades_best.csv", index=False)
    print(f"\nBest threshold by Sharpe (with >=20 trades): {best_thr}")
    print(grid_df.to_string(index=False))


if __name__ == "__main__":
    main()
