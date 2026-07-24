"""Canonical feature lists shared by the correlation, ML and scoring stages,
so all three analyse exactly the same point-in-time (no look-ahead) variables."""
import json

# Narrative / category keyword buckets (CoinGecko `categories` field -> our
# canonical narrative tags). These are STATIC per coin (a coin's narrative
# doesn't change day to day within our observation window), so using them at
# any candidate date t is safe (no look-ahead).
NARRATIVE_KEYWORDS = {
    "narr_ai": ["ai", "artificial intelligence", "agi"],
    "narr_rwa": ["real world assets", "rwa"],
    "narr_defi": ["decentralized finance", "defi", "lending", "dex"],
    "narr_gaming": ["gaming", "gamefi", "metaverse", "play to earn"],
    "narr_memecoin": ["meme"],
    "narr_l1": ["layer 1", "smart contract platform"],
    "narr_l2": ["layer 2", "scaling"],
    "narr_infra": ["infrastructure", "oracle", "interoperability"],
    "narr_depin": ["depin"],
}
NARRATIVE_COLS = list(NARRATIVE_KEYWORDS.keys())


def compute_narrative_dummies(categories_json):
    try:
        if isinstance(categories_json, str):
            cats = json.loads(categories_json)
        elif isinstance(categories_json, (list, tuple)):
            cats = categories_json
        else:
            cats = []
    except (json.JSONDecodeError, TypeError):
        cats = []
    if not isinstance(cats, (list, tuple)):
        cats = []
    cats_lower = " | ".join(str(c).lower() for c in cats)
    return {col: int(any(kw in cats_lower for kw in kws)) for col, kws in NARRATIVE_KEYWORDS.items()}


FEATURE_COLS_COMMON = [
    "ret_1d", "ret_2d", "ret_3d", "ret_7d", "ret_14d", "ret_30d",
    "vol_7d", "vol_30d", "vol_rel_7d", "vol_rel_30d",
    "dist_from_high_30d", "dist_from_high_90d",
    "price_above_ma7", "price_above_ma30", "ma7_above_ma30",
    "universe_vol_chg_7d", "btc_ret_90d", "coin_age_days",
] + NARRATIVE_COLS

FEATURE_COLS_A_EXTRA = [
    "market_cap_usd", "tvl_growth_7d", "tvl_growth_30d", "tvl_to_mcap", "btc_dominance_proxy",
]

LABEL_THRESHOLDS = [5, 10, 20]
LABEL_HORIZONS = [14, 30, 90]
