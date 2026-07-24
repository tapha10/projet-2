"""Steps 6-9: entry timing, exit/duration analysis, and "empty week" frequency,
computed directly from the detected rally-leg events (src/features/events.py)
and the underlying daily OHLCV series.

Entry-timing rules compared (Step 6). Note: "smart money accumulation" is
explicitly NOT available for free at this scale (would require a paid
on-chain/whale-tracking API such as Nansen/Arkham) -- flagged as a limitation,
not silently skipped.
  1. perfect_trough  : buy exactly at the detected trough (theoretical upper bound)
  2. confirm_10pct   : buy on the first close >= trough_price * 1.10 after the trough
  3. volume_breakout : buy on the first day volume >= 2x the trailing 30d average volume, after the trough
  4. ma_breakout     : buy on the first day price crosses above its 30-day moving average, after the trough

For each rule, we measure what fraction of the eventual trough->peak multiple
is still captured when entering late (Step 6 outcome), and separately compute
the fraction of eventual peak gain realised after 1d/2d/7d/14d/30d/90d holding
from the ACTUAL entry point used in the strategy (perfect_trough), which is
what Step 8 (optimal holding duration) asks for.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
HOLD_DAYS = [1, 2, 3, 7, 14, 30, 60, 90]


def load_price_series(conn, coin_id, source):
    if source == "coingecko_365d":
        df = pd.read_sql(
            "SELECT date, price_usd AS price, volume_usd AS volume FROM price_history WHERE coin_id=? ORDER BY date",
            conn, params=(coin_id,), parse_dates=["date"],
        )
    else:
        df = pd.read_sql(
            "SELECT date, close AS price, volume FROM cb_price_history WHERE coin_id=? ORDER BY date",
            conn, params=(coin_id,), parse_dates=["date"],
        )
    df["ma30"] = df["price"].rolling(30).mean()
    df["vol_avg30"] = df["volume"].rolling(30).mean().shift(1)
    return df


def entry_rules_for_event(df, trough_date):
    seg = df[df["date"] >= trough_date].reset_index(drop=True)
    if len(seg) < 2:
        return {}
    trough_price = seg["price"].iloc[0]
    out = {"perfect_trough": (seg["date"].iloc[0], trough_price)}

    confirm = seg[seg["price"] >= trough_price * 1.10]
    if len(confirm):
        out["confirm_10pct"] = (confirm["date"].iloc[0], confirm["price"].iloc[0])

    vb = seg[(seg["volume"] >= 2 * seg["vol_avg30"]) & (seg.index > 0)]
    if len(vb):
        out["volume_breakout"] = (vb["date"].iloc[0], vb["price"].iloc[0])

    mb = seg[(seg["price"] > seg["ma30"]) & (seg["ma30"].notna())]
    if len(mb):
        out["ma_breakout"] = (mb["date"].iloc[0], mb["price"].iloc[0])

    return out


def capture_rate_curve(df, trough_date, peak_price, trough_price):
    seg = df[df["date"] >= trough_date].reset_index(drop=True)
    if not len(seg):
        return {}
    total_gain = peak_price - trough_price
    out = {}
    for h in HOLD_DAYS:
        if h < len(seg):
            price_h = seg["price"].iloc[h]
            captured = (price_h - trough_price) / total_gain if total_gain > 0 else np.nan
            out[f"capture_{h}d"] = np.clip(captured, 0, 1.5)
    return out


def main(min_multiple=10):
    conn = get_conn()
    events = pd.read_sql(
        "SELECT * FROM events WHERE multiple >= ? ORDER BY source, coin_id, trough_date",
        conn, params=(min_multiple,), parse_dates=["trough_date", "peak_date"],
    )
    print(f"Analysing {len(events)} events with multiple >= {min_multiple}x")

    entry_rows, capture_rows = [], []
    cache = {}
    for row in events.itertuples():
        key = (row.coin_id, row.source)
        if key not in cache:
            cache[key] = load_price_series(conn, row.coin_id, row.source)
        df = cache[key]

        rules = entry_rules_for_event(df, row.trough_date)
        perfect_price = rules.get("perfect_trough", (None, None))[1]
        for rule_name, (edate, eprice) in rules.items():
            captured_multiple = row.peak_price / eprice if eprice else np.nan
            pct_of_full_move = (
                (captured_multiple - 1) / (row.multiple - 1) if row.multiple > 1 else np.nan
            )
            entry_rows.append(
                {
                    "coin_id": row.coin_id, "source": row.source, "trough_date": row.trough_date,
                    "rule": rule_name, "entry_date": edate, "entry_price": eprice,
                    "days_after_trough": (edate - row.trough_date).days,
                    "multiple_from_entry_to_peak": captured_multiple,
                    "pct_of_full_trough_to_peak_move_captured": pct_of_full_move,
                }
            )

        cap = capture_rate_curve(df, row.trough_date, row.peak_price, row.trough_price)
        cap.update({"coin_id": row.coin_id, "source": row.source, "trough_date": row.trough_date, "multiple": row.multiple})
        capture_rows.append(cap)

    entry_df = pd.DataFrame(entry_rows)
    capture_df = pd.DataFrame(capture_rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    entry_df.to_csv(REPORTS_DIR / "timing_entry_rules.csv", index=False)
    capture_df.to_csv(REPORTS_DIR / "timing_capture_rates.csv", index=False)

    print("\n--- Entry rule comparison (median % of full trough->peak move captured) ---")
    print(entry_df.groupby("rule")["pct_of_full_trough_to_peak_move_captured"].median().sort_values(ascending=False))
    print("\n--- Entry rule: median days after trough ---")
    print(entry_df.groupby("rule")["days_after_trough"].median())

    print("\n--- Duration / capture-rate curve (median fraction of eventual peak gain captured by day N) ---")
    for h in HOLD_DAYS:
        col = f"capture_{h}d"
        if col in capture_df:
            print(f"  {h:>3}d: median={capture_df[col].median():.2%}  mean={capture_df[col].mean():.2%}  n={capture_df[col].notna().sum()}")

    # weeks without opportunity
    print("\n--- Weeks without any qualifying (>=10x-eventual) trough, per source ---")
    for source in events["source"].unique():
        ev_s = events[events["source"] == source]
        min_d, max_d = ev_s["trough_date"].min(), ev_s["trough_date"].max()
        if pd.isna(min_d):
            continue
        all_weeks = pd.period_range(min_d, max_d, freq="W")
        weeks_with_event = set(ev_s["trough_date"].dt.to_period("W"))
        n_empty = sum(1 for w in all_weeks if w not in weeks_with_event)
        print(f"  {source}: {n_empty}/{len(all_weeks)} weeks ({n_empty/len(all_weeks):.1%}) had ZERO new >= {min_multiple}x-eventual troughs")

    conn.close()


if __name__ == "__main__":
    main()
