"""Canonical feature lists shared by the correlation, ML and scoring stages,
so all three analyse exactly the same point-in-time (no look-ahead) variables."""

FEATURE_COLS_COMMON = [
    "ret_1d", "ret_2d", "ret_3d", "ret_7d", "ret_14d", "ret_30d",
    "vol_7d", "vol_30d", "vol_rel_7d", "vol_rel_30d",
    "dist_from_high_30d", "dist_from_high_90d",
    "price_above_ma7", "price_above_ma30", "ma7_above_ma30",
    "universe_vol_chg_7d", "btc_ret_90d", "coin_age_days",
]

FEATURE_COLS_A_EXTRA = [
    "market_cap_usd", "tvl_growth_7d", "tvl_growth_30d", "tvl_to_mcap", "btc_dominance_proxy",
]

LABEL_THRESHOLDS = [5, 10, 20]
LABEL_HORIZONS = [14, 30, 90]
