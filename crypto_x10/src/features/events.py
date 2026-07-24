"""x5 / x10 / x20 / x50 / x100 event detection.

Algorithm ("rally-leg" detection):
  - Walk the daily price series once (O(n)).
  - Track a running trough (lowest price since the last leg reset) and, once
    price starts rising, a running peak (highest price reached since that
    trough).
  - A leg "closes" (and a new trough starts) when price pulls back more than
    RESET_DRAWDOWN (default 30%) from the running peak. At that point we
    record trough->peak as one rally event if its multiple >= 5x.
  - The last open leg at the end of the series is also flushed.

This yields non-overlapping, objectively-defined rally events per coin,
usable for both the historical frequency counts (Step 2) and as prediction
targets (Step 3-4): "features observed before trough_date should predict
whether this leg will reach >=10x".

Caveat documented in the report: any purely mechanical peak/trough detector
is a simplification. RESET_DRAWDOWN is a free parameter; we run a sensitivity
check (20% / 30% / 40%) to confirm conclusions are not an artifact of one
specific choice.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

THRESHOLDS = [5, 10, 20, 50, 100]
RESET_DRAWDOWN = 0.30


def detect_legs(dates, prices, reset_drawdown=RESET_DRAWDOWN, min_multiple=5.0):
    """dates: list of str (sorted ascending), prices: list of float (>0, no NaN)."""
    events = []
    if len(prices) < 3:
        return events

    trough_i = 0
    trough_p = prices[0]
    peak_i = 0
    peak_p = prices[0]

    def flush(trough_i, trough_p, peak_i, peak_p):
        if peak_p <= 0 or trough_p <= 0:
            return
        multiple = peak_p / trough_p
        if multiple >= min_multiple and peak_i > trough_i:
            events.append(
                {
                    "trough_date": dates[trough_i],
                    "trough_price": trough_p,
                    "peak_date": dates[peak_i],
                    "peak_price": peak_p,
                    "multiple": multiple,
                    "days_to_peak": _days_between(dates[trough_i], dates[peak_i]),
                }
            )

    for i in range(1, len(prices)):
        p = prices[i]
        still_probing_bottom = peak_p <= trough_p
        if still_probing_bottom and p < trough_p:
            # haven't started a rally yet (peak hasn't risen above trough) -> push trough down
            trough_p = p
            trough_i = i
            peak_p = p
            peak_i = i
            continue

        if p >= peak_p:
            peak_p = p
            peak_i = i
            continue

        # price pulled back from peak_p; check reset condition
        drawdown = (peak_p - p) / peak_p if peak_p > 0 else 0
        if drawdown >= reset_drawdown:
            flush(trough_i, trough_p, peak_i, peak_p)
            # new leg starts at current point
            trough_i, trough_p = i, p
            peak_i, peak_p = i, p

    # flush any open leg at the end of the series
    flush(trough_i, trough_p, peak_i, peak_p)
    return events


def _days_between(d1, d2):
    a = pd.Timestamp(d1)
    b = pd.Timestamp(d2)
    return int((b - a).days)


def regime_at(regime_df, date):
    if regime_df is None or not len(regime_df):
        return None
    idx = regime_df["date"].searchsorted(date, side="right") - 1
    if idx < 0:
        return None
    return regime_df["regime"].iloc[idx]


def run_detection_for_source(conn, source_table, price_col, source_label):
    cur = conn.cursor()
    coin_ids = pd.read_sql(f"SELECT DISTINCT coin_id FROM {source_table}", conn)["coin_id"].tolist()

    regime_df = pd.read_sql(
        "SELECT date, regime FROM market_regime WHERE source=? ORDER BY date",
        conn,
        params=(source_label,),
    )

    cur.execute("DELETE FROM events WHERE source=?", (source_label,))
    conn.commit()

    total_events = 0
    for coin_id in coin_ids:
        df = pd.read_sql(
            f"SELECT date, {price_col} AS price FROM {source_table} WHERE coin_id=? ORDER BY date",
            conn,
            params=(coin_id,),
        )
        df = df.dropna(subset=["price"])
        df = df[df["price"] > 0]
        if len(df) < 3:
            continue
        dates = df["date"].tolist()
        prices = df["price"].tolist()
        legs = detect_legs(dates, prices)
        rows = []
        for leg in legs:
            reg = regime_at(regime_df, leg["trough_date"])
            m = leg["multiple"]
            rows.append(
                (
                    coin_id,
                    source_label,
                    leg["trough_date"],
                    leg["trough_price"],
                    leg["peak_date"],
                    leg["peak_price"],
                    m,
                    leg["days_to_peak"],
                    int(m >= 5),
                    int(m >= 10),
                    int(m >= 20),
                    int(m >= 50),
                    int(m >= 100),
                    reg,
                )
            )
        if rows:
            cur.executemany(
                """INSERT INTO events (coin_id, source, trough_date, trough_price, peak_date, peak_price,
                    multiple, days_to_peak, hit_x5, hit_x10, hit_x20, hit_x50, hit_x100, market_regime_at_trough)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            total_events += len(rows)
    conn.commit()
    print(f"{source_label}: {total_events} rally events (>=5x) across {len(coin_ids)} coins")


def reset_drawdown_sensitivity(conn, source_table, price_col, source_label):
    """Robustness check: how sensitive is the event count to the RESET_DRAWDOWN
    parameter? Reported in the final report rather than assumed."""
    coin_ids = pd.read_sql(f"SELECT DISTINCT coin_id FROM {source_table}", conn)["coin_id"].tolist()
    rows = []
    for reset in [0.20, 0.30, 0.40]:
        n5 = n10 = n20 = 0
        for coin_id in coin_ids:
            df = pd.read_sql(
                f"SELECT date, {price_col} AS price FROM {source_table} WHERE coin_id=? ORDER BY date",
                conn, params=(coin_id,),
            )
            df = df.dropna(subset=["price"])
            df = df[df["price"] > 0]
            if len(df) < 3:
                continue
            legs = detect_legs(df["date"].tolist(), df["price"].tolist(), reset_drawdown=reset)
            for leg in legs:
                if leg["multiple"] >= 5:
                    n5 += 1
                if leg["multiple"] >= 10:
                    n10 += 1
                if leg["multiple"] >= 20:
                    n20 += 1
        rows.append({"source": source_label, "reset_drawdown": reset, "n_events_x5": n5, "n_events_x10": n10, "n_events_x20": n20})
    return pd.DataFrame(rows)


def main():
    conn = get_conn()
    run_detection_for_source(conn, "price_history", "price_usd", "coingecko_365d")
    run_detection_for_source(conn, "cb_price_history", "close", "coinbase_full")

    sens_a = reset_drawdown_sensitivity(conn, "price_history", "price_usd", "coingecko_365d")
    sens_b = reset_drawdown_sensitivity(conn, "cb_price_history", "close", "coinbase_full")
    sens = pd.concat([sens_a, sens_b], ignore_index=True)
    out_path = Path(__file__).resolve().parents[2] / "reports" / "event_detection_sensitivity.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sens.to_csv(out_path, index=False)
    print(f"\nSaved sensitivity check -> {out_path}")
    print(sens.to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()
