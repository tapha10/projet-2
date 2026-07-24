"""Feature engineering on the Coinbase long-history panel (Dataset B).

Rationale: the CoinGecko panel (Dataset A, engineering.py) covers the full
421-coin Bybit universe but only 365 days -- in the current bear/neutral BTC
regime that window contains almost no realised x10 events, which is too
sparse to train or evaluate a classifier responsibly (near-zero positives).

Dataset B trades breadth for depth: 209 Bybit coins that are also listed on
Coinbase (survivorship/quality-biased towards larger, older, more "legit"
projects -- documented explicitly as a bias), but with daily history back to
each coin's Coinbase listing (years, spanning the 2020-21 and 2023-24 bull
phases). This is the primary dataset used for ML training and backtesting the
price/volume-momentum signal; it lacks market-cap, TVL and dominance features
(no historical circulating-supply data for free), so only price/volume-derived
features are computed here.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn
from src.features.engineering import LOOKBACKS, LABEL_HORIZONS, MIN_LOOKBACK, STEP_DAYS, coin_age_days


def build_universe_daily_stats_cb(price):
    daily = price.groupby("date").agg(universe_vol=("volume", "sum"))
    daily["universe_vol_chg_7d"] = daily["universe_vol"].pct_change(7)
    btc = price[price["coin_id"] == "bitcoin"].set_index("date")["close"]
    daily = daily.join(btc.rename("btc_price"), how="left")
    return daily.reset_index()


def compute_coin_features_cb(df):
    df = df.sort_values("date").reset_index(drop=True)
    price = df["close"].values
    vol = df["volume"].values
    n = len(df)

    feat = pd.DataFrame({"date": df["date"], "price": price, "volume": vol})

    for lb in LOOKBACKS:
        ret = np.full(n, np.nan)
        ret[lb:] = price[lb:] / price[:-lb] - 1
        feat[f"ret_{lb}d"] = ret

    log_ret = np.diff(np.log(np.clip(price, 1e-12, None)), prepend=np.nan)
    feat["daily_log_ret"] = log_ret
    feat["vol_7d"] = feat["daily_log_ret"].rolling(7).std()
    feat["vol_30d"] = feat["daily_log_ret"].rolling(30).std()

    feat["vol_rel_7d"] = feat["volume"] / feat["volume"].rolling(7).mean().shift(1)
    feat["vol_rel_30d"] = feat["volume"] / feat["volume"].rolling(30).mean().shift(1)

    feat["dist_from_high_30d"] = feat["price"] / feat["price"].rolling(30).max() - 1
    feat["dist_from_high_90d"] = feat["price"] / feat["price"].rolling(min(90, n)).max() - 1

    feat["ma7"] = feat["price"].rolling(7).mean()
    feat["ma30"] = feat["price"].rolling(30).mean()
    feat["price_above_ma7"] = feat["price"] / feat["ma7"] - 1
    feat["price_above_ma30"] = feat["price"] / feat["ma30"] - 1
    feat["ma7_above_ma30"] = feat["ma7"] / feat["ma30"] - 1

    for h in LABEL_HORIZONS:
        fwd_max_future = np.full(n, np.nan)
        for i in range(n - 1):
            end = min(i + 1 + h, n)
            fwd_max_future[i] = price[i + 1:end].max() if end > i + 1 else np.nan
        feat[f"fwd_max_mult_{h}d"] = fwd_max_future / price

    return feat


def main():
    conn = get_conn()
    price = pd.read_sql(
        "SELECT coin_id, date, close, volume FROM cb_price_history ORDER BY coin_id, date",
        conn,
        parse_dates=["date"],
    )
    price = price.dropna(subset=["close"])
    price = price[price["close"] > 0]

    regime = pd.read_sql(
        "SELECT date, regime, btc_ret_90d FROM market_regime WHERE source='coinbase_full' ORDER BY date",
        conn,
        parse_dates=["date"],
    )
    coins = pd.read_sql("SELECT coin_id, symbol, categories, genesis_date, market_cap_rank_current FROM coins", conn)
    daily_stats = build_universe_daily_stats_cb(price)

    all_candidates = []
    for coin_id, df in price.groupby("coin_id"):
        if len(df) < MIN_LOOKBACK + 7:
            continue
        feat = compute_coin_features_cb(df)
        feat = feat.merge(daily_stats.drop(columns=["btc_price"]), on="date", how="left")
        feat = feat.merge(regime, on="date", how="left")

        crow = coins[coins["coin_id"] == coin_id]
        categories = crow["categories"].iloc[0] if len(crow) else "[]"
        genesis = crow["genesis_date"].iloc[0] if len(crow) else None
        rank = crow["market_cap_rank_current"].iloc[0] if len(crow) else np.nan

        n = len(feat)
        idxs = list(range(MIN_LOOKBACK, n, STEP_DAYS))
        rows = []
        for i in idxs:
            row = feat.iloc[i].to_dict()
            row["coin_id"] = coin_id
            row["categories"] = categories
            row["genesis_date"] = genesis
            row["market_cap_rank_current"] = rank
            rows.append(row)
        cand = pd.DataFrame(rows)
        if len(cand):
            cand["coin_age_days"] = cand["date"].apply(lambda t: coin_age_days(genesis, t))
            all_candidates.append(cand)

    panel = pd.concat(all_candidates, ignore_index=True)
    print(f"[Dataset B / Coinbase] Candidate rows: {len(panel)} across {panel['coin_id'].nunique()} coins")
    print(f"Date range: {panel['date'].min()} -> {panel['date'].max()}")

    out_dir = Path(__file__).resolve().parents[2] / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_dir / "candidate_panel_cb.parquet", index=False)
    print(f"Saved {out_dir / 'candidate_panel_cb.parquet'}")

    for h in LABEL_HORIZONS:
        col = f"fwd_max_mult_{h}d"
        valid = panel[col].notna()
        pos_rate = (panel.loc[valid, col] >= 10).mean()
        print(f"H={h}d: {valid.sum()} labeled rows, x10+ positive rate = {pos_rate:.3%}")

    conn.close()


if __name__ == "__main__":
    main()
