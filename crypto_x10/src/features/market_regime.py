"""Classify each day as bull / bear / neutral market regime using BTC's
trailing 90-day return, computed separately on each data source (CoinGecko
365d panel and the Coinbase long-history panel for BTC).

Thresholds: bull if 90d return > +20%, bear if < -20%, else neutral.
These are simple, transparent, and commonly used breakpoints for crypto cycle
regime labelling; they are a deliberate simplification documented in the
report (no claim of being the "true" cycle turning points).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

BULL_THRESH = 0.20
BEAR_THRESH = -0.20


def classify(df):
    df = df.sort_values("date").copy()
    df["btc_ret_90d"] = df["btc_price"].pct_change(90)

    def label(r):
        if pd.isna(r):
            return None
        if r > BULL_THRESH:
            return "bull"
        if r < BEAR_THRESH:
            return "bear"
        return "neutral"

    df["regime"] = df["btc_ret_90d"].apply(label)
    return df


def main():
    conn = get_conn()

    cg = pd.read_sql(
        "SELECT date, price_usd AS btc_price FROM price_history WHERE coin_id='bitcoin' ORDER BY date",
        conn,
    )
    if len(cg):
        cg = classify(cg)
        cg["source"] = "coingecko_365d"

    cb = pd.read_sql(
        "SELECT date, close AS btc_price FROM cb_price_history WHERE coin_id='bitcoin' ORDER BY date",
        conn,
    )
    if len(cb):
        cb = classify(cb)
        cb["source"] = "coinbase_full"

    cur = conn.cursor()
    cur.execute("DELETE FROM market_regime")
    for df in (cg, cb):
        if df is None or not len(df):
            continue
        rows = [
            (row.source, row.date, row.btc_price, row.btc_ret_90d, row.regime)
            for row in df.itertuples()
        ]
        cur.executemany(
            "INSERT OR REPLACE INTO market_regime (source, date, btc_price, btc_ret_90d, regime) VALUES (?,?,?,?,?)",
            rows,
        )
    conn.commit()

    for name, df in [("coingecko_365d", cg), ("coinbase_full", cb)]:
        if df is not None and len(df):
            print(name, df["regime"].value_counts(dropna=True).to_dict())
    conn.close()


if __name__ == "__main__":
    main()
