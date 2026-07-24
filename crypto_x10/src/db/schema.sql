-- Schema for the Bybit x10-prediction study database

CREATE TABLE IF NOT EXISTS coins (
    coin_id TEXT PRIMARY KEY,          -- coingecko id
    symbol TEXT,
    name TEXT,
    market_cap_rank_current INTEGER,
    genesis_date TEXT,
    categories TEXT,                   -- JSON list, narrative tags (AI, RWA, DeFi, Gaming, Memecoin, ...)
    platforms TEXT,                    -- JSON dict of chain -> contract address
    bybit_pairs TEXT,                  -- JSON list of Bybit spot pairs quoting this coin (e.g. ["BTC/USDT"])
    is_stablecoin INTEGER DEFAULT 0,
    first_listed_on_bybit_approx TEXT, -- best-effort proxy (see methodology notes), NOT a guaranteed listing date
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    coin_id TEXT,
    date TEXT,                         -- YYYY-MM-DD (UTC, daily close snapshot from CoinGecko market_chart)
    price_usd REAL,
    market_cap_usd REAL,
    volume_usd REAL,
    PRIMARY KEY (coin_id, date)
);

CREATE TABLE IF NOT EXISTS coin_snapshot (
    -- current-snapshot-only metrics (CoinGecko free tier does not expose historical
    -- time series for dev/social/derivatives data -> these are single point-in-time
    -- observations, documented explicitly as a limitation in the final report)
    coin_id TEXT PRIMARY KEY,
    fetched_at TEXT,
    fdv_usd REAL,
    circulating_supply REAL,
    total_supply REAL,
    max_supply REAL,
    ath_usd REAL,
    ath_date TEXT,
    ath_change_pct REAL,
    atl_usd REAL,
    atl_date TEXT,
    github_url TEXT,
    gh_stars INTEGER,
    gh_forks INTEGER,
    gh_subscribers INTEGER,
    gh_total_issues INTEGER,
    gh_closed_issues INTEGER,
    gh_pr_merged INTEGER,
    gh_pr_contributors INTEGER,
    gh_commit_count_4w INTEGER,
    twitter_followers INTEGER,
    reddit_subscribers INTEGER,
    telegram_user_count INTEGER,
    sentiment_up_pct REAL,
    sentiment_down_pct REAL
);

CREATE TABLE IF NOT EXISTS cb_price_history (
    -- Long-history daily OHLCV from Coinbase Exchange (public API, no key needed,
    -- full history back to listing). Used as a robustness / multi-year cross-check
    -- for the subset of Bybit coins that are also listed on Coinbase, since
    -- CoinGecko's free tier caps history at 365 days for the full 421-coin universe.
    coin_id TEXT,
    product_id TEXT,
    date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    PRIMARY KEY (coin_id, date)
);

CREATE TABLE IF NOT EXISTS tvl_history (
    protocol_slug TEXT,
    date TEXT,
    tvl_usd REAL,
    PRIMARY KEY (protocol_slug, date)
);

CREATE TABLE IF NOT EXISTS protocol_token_map (
    protocol_slug TEXT PRIMARY KEY,
    coin_id TEXT,
    protocol_name TEXT
);

CREATE TABLE IF NOT EXISTS global_market (
    date TEXT PRIMARY KEY,
    btc_dominance_pct REAL,
    total_mcap_usd REAL,
    total_volume_usd REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id TEXT,
    source TEXT,                 -- 'coingecko_365d' or 'coinbase_full'
    trough_date TEXT,
    trough_price REAL,
    peak_date TEXT,
    peak_price REAL,
    multiple REAL,
    days_to_peak INTEGER,
    hit_x5 INTEGER,
    hit_x10 INTEGER,
    hit_x20 INTEGER,
    hit_x50 INTEGER,
    hit_x100 INTEGER,
    market_regime_at_trough TEXT
);

CREATE TABLE IF NOT EXISTS market_regime (
    source TEXT,
    date TEXT,
    btc_price REAL,
    btc_ret_90d REAL,
    regime TEXT,                 -- 'bull' | 'bear' | 'neutral'
    PRIMARY KEY (source, date)
);

CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    step TEXT,
    coin_id TEXT,
    status TEXT,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_date ON price_history(date);
CREATE INDEX IF NOT EXISTS idx_tvl_date ON tvl_history(date);
