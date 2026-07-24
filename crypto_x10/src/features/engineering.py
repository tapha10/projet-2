"""Feature engineering (Step 3/5): for weekly-sampled candidate entry points,
compute point-in-time features (no look-ahead) and forward-looking labels.

Design choices (documented for reproducibility / auditability):
  - Only the CoinGecko 365-day daily panel is used here (uniform coverage of
    the full 421-coin Bybit universe). The Coinbase long-history panel is used
    separately for the multi-year historical-frequency context, not for ML,
    because it only covers a 209-coin subset (survivorship towards
    larger/older coins) and would bias the learned model.
  - Momentum/volatility/volume features are computed strictly from data at or
    before the candidate date t (no look-ahead).
  - Dev-activity / social / FDV / supply are CURRENT-SNAPSHOT ONLY in the free
    CoinGecko API (no historical time series available for free). Using them
    "as of" a past t would leak future information, so they are EXCLUDED from
    this point-in-time feature set and from the backtest. They are analysed
    separately, explicitly labelled as a same-day cross-sectional exploratory
    signal, not a backtestable predictor.
  - Labels: forward maximum multiple over H in {14, 30, 90} days, i.e.
    max(price[t+1 .. t+H]) / price[t]. This mirrors the rally-leg definition
    used for the historical event counts, but sampled at regular weekly
    intervals to build a proper (mostly) balanced classification dataset
    instead of only the already-successful legs.
  - Weekly sampling (every 7 days per coin) avoids the extreme
    autocorrelation of daily-sampled overlapping windows while giving ~35
    candidate dates per coin over the available 365-day history.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

LOOKBACKS = [1, 2, 3, 7, 14, 30]   # days = 24h/48h/72h/7d/14d/30d
LABEL_HORIZONS = [14, 30, 90]
MIN_LOOKBACK = 30
STEP_DAYS = 7


def load_panel(conn):
    price = pd.read_sql(
        "SELECT coin_id, date, price_usd, market_cap_usd, volume_usd FROM price_history ORDER BY coin_id, date",
        conn,
        parse_dates=["date"],
    )
    tvl = pd.read_sql(
        """SELECT ptm.coin_id, t.date, t.tvl_usd
           FROM tvl_history t JOIN protocol_token_map ptm ON t.protocol_slug = ptm.protocol_slug
           ORDER BY ptm.coin_id, t.date""",
        conn,
        parse_dates=["date"],
    )
    # a coin can map to multiple protocols (rare); sum tvl across its protocols per day
    if len(tvl):
        tvl = tvl.groupby(["coin_id", "date"], as_index=False)["tvl_usd"].sum()

    regime = pd.read_sql(
        "SELECT date, regime, btc_ret_90d FROM market_regime WHERE source='coingecko_365d' ORDER BY date",
        conn,
        parse_dates=["date"],
    )
    coins = pd.read_sql("SELECT coin_id, symbol, categories, genesis_date, market_cap_rank_current FROM coins", conn)
    return price, tvl, regime, coins


def build_universe_daily_stats(price):
    """Point-in-time market-cap sum across our observed universe per day, used
    as a BTC-dominance proxy and as an 'altseason breadth' signal."""
    daily = price.groupby("date").agg(universe_mcap=("market_cap_usd", "sum"), universe_vol=("volume_usd", "sum"))
    btc = price[price["coin_id"] == "bitcoin"].set_index("date")["market_cap_usd"]
    daily["btc_dominance_proxy"] = btc / daily["universe_mcap"]
    daily["universe_vol_chg_7d"] = daily["universe_vol"].pct_change(7)
    return daily.reset_index()


def compute_coin_features(df, tvl_df, daily_stats, regime):
    """df: single coin's price rows sorted by date, full daily series (no gaps assumed
    to be filled; CoinGecko market_chart already returns one point per day)."""
    df = df.sort_values("date").reset_index(drop=True)
    price = df["price_usd"].values
    vol = df["volume_usd"].values
    n = len(df)

    feat = pd.DataFrame({"date": df["date"], "price": price, "volume": vol})

    for lb in LOOKBACKS:
        ret = np.full(n, np.nan)
        ret[lb:] = price[lb:] / price[:-lb] - 1
        feat[f"ret_{lb}d"] = ret

    # realized volatility of daily log returns
    log_ret = np.diff(np.log(np.clip(price, 1e-12, None)), prepend=np.nan)
    feat["daily_log_ret"] = log_ret
    feat["vol_7d"] = feat["daily_log_ret"].rolling(7).std()
    feat["vol_30d"] = feat["daily_log_ret"].rolling(30).std()

    # relative volume: today's volume vs trailing 30d average (shifted so "today" is included but window is trailing)
    feat["vol_rel_7d"] = feat["volume"] / feat["volume"].rolling(7).mean().shift(1)
    feat["vol_rel_30d"] = feat["volume"] / feat["volume"].rolling(30).mean().shift(1)

    # distance from recent high / accumulation proxy
    feat["dist_from_high_30d"] = feat["price"] / feat["price"].rolling(30).max() - 1
    feat["dist_from_high_90d"] = feat["price"] / feat["price"].rolling(min(90, n)).max() - 1

    # trend indicators
    feat["ma7"] = feat["price"].rolling(7).mean()
    feat["ma30"] = feat["price"].rolling(30).mean()
    feat["price_above_ma7"] = (feat["price"] / feat["ma7"] - 1)
    feat["price_above_ma30"] = (feat["price"] / feat["ma30"] - 1)
    feat["ma7_above_ma30"] = (feat["ma7"] / feat["ma30"] - 1)

    # market cap (point-in-time)
    feat["market_cap_usd"] = df["market_cap_usd"].values

    # merge tvl (point-in-time) if present for this coin
    if tvl_df is not None and len(tvl_df):
        feat = feat.merge(tvl_df[["date", "tvl_usd"]], on="date", how="left")
        feat["tvl_growth_30d"] = feat["tvl_usd"] / feat["tvl_usd"].shift(30) - 1
        feat["tvl_growth_7d"] = feat["tvl_usd"] / feat["tvl_usd"].shift(7) - 1
        feat["tvl_to_mcap"] = feat["tvl_usd"] / feat["market_cap_usd"]
    else:
        feat["tvl_usd"] = np.nan
        feat["tvl_growth_30d"] = np.nan
        feat["tvl_growth_7d"] = np.nan
        feat["tvl_to_mcap"] = np.nan

    # market context (point-in-time, universe-level)
    feat = feat.merge(daily_stats, on="date", how="left")
    feat = feat.merge(regime, on="date", how="left")

    # forward-looking labels (max multiple over next H days) — used ONLY as label, never as feature
    for h in LABEL_HORIZONS:
        fwd_max = pd.Series(price).iloc[::-1].rolling(h, min_periods=1).max().iloc[::-1].values
        # fwd_max computed on reversed series gives, at index i, max of price[i:i+h]; we want strictly future (i+1..i+h)
        fwd_max_future = np.full(n, np.nan)
        for i in range(n - 1):
            end = min(i + 1 + h, n)
            fwd_max_future[i] = price[i + 1:end].max() if end > i + 1 else np.nan
        feat[f"fwd_max_mult_{h}d"] = fwd_max_future / price

    return feat


def build_candidates(feat, coin_id, coin_static):
    n = len(feat)
    idxs = list(range(MIN_LOOKBACK, n, STEP_DAYS))
    rows = []
    for i in idxs:
        row = feat.iloc[i].to_dict()
        row["coin_id"] = coin_id
        row.update(coin_static)
        # require at least the 90d forward window OR keep with NaN labels if near end (dropped later per-horizon)
        rows.append(row)
    return pd.DataFrame(rows)


def coin_age_days(genesis_date, t):
    if not genesis_date:
        return np.nan
    try:
        g = pd.Timestamp(genesis_date)
    except Exception:
        return np.nan
    return (t - g).days


def main():
    conn = get_conn()
    price, tvl, regime, coins = load_panel(conn)
    daily_stats = build_universe_daily_stats(price)

    all_candidates = []
    for coin_id, df in price.groupby("coin_id"):
        if len(df) < MIN_LOOKBACK + 7:
            continue
        tvl_df = tvl[tvl["coin_id"] == coin_id] if len(tvl) else None
        feat = compute_coin_features(df, tvl_df, daily_stats, regime)

        crow = coins[coins["coin_id"] == coin_id]
        categories = crow["categories"].iloc[0] if len(crow) else "[]"
        genesis = crow["genesis_date"].iloc[0] if len(crow) else None
        rank = crow["market_cap_rank_current"].iloc[0] if len(crow) else np.nan
        coin_static = {"categories": categories, "genesis_date": genesis, "market_cap_rank_current": rank}

        cand = build_candidates(feat, coin_id, coin_static)
        cand["coin_age_days"] = cand["date"].apply(lambda t: coin_age_days(genesis, t))
        all_candidates.append(cand)

    panel = pd.concat(all_candidates, ignore_index=True)
    print(f"Candidate rows: {len(panel)} across {panel['coin_id'].nunique()} coins")

    # persist to parquet for downstream stages (keeps sqlite lean)
    out_dir = Path(__file__).resolve().parents[2] / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_dir / "candidate_panel.parquet", index=False)
    print(f"Saved {out_dir / 'candidate_panel.parquet'}")

    for h in LABEL_HORIZONS:
        col = f"fwd_max_mult_{h}d"
        valid = panel[col].notna()
        pos_rate = (panel.loc[valid, col] >= 10).mean()
        print(f"H={h}d: {valid.sum()} labeled rows, x10+ positive rate = {pos_rate:.3%}")

    conn.close()


if __name__ == "__main__":
    main()
