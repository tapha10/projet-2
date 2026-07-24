"""Step 1: build the universe of coins listed on Bybit (spot) via CoinGecko.

CoinGecko exposes exchange-level ticker data for the exchange id `bybit_spot`
(Bybit's spot order book). We paginate through all tickers, keep pairs quoted
against USDT/USD/USDC/BTC/ETH (majors), and resolve each base asset to its
CoinGecko coin_id (needed to pull historical market_chart data later).

Note: CoinGecko does not expose a reliable "date first listed on Bybit" field.
We approximate it later using the price history's first available date as a
lower bound and document this clearly as a limitation.
"""
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collectors.cg_client import cg_get
from src.db.db import get_conn, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_universe")

QUOTE_WHITELIST = {"USDT", "USD", "USDC"}


def fetch_all_tickers(exchange_id):
    all_tickers = []
    page = 1
    while True:
        data = cg_get(f"/exchanges/{exchange_id}/tickers", params={"page": page})
        if not data or not data.get("tickers"):
            break
        all_tickers.extend(data["tickers"])
        logger.info(f"{exchange_id}: page {page} -> {len(data['tickers'])} tickers (total {len(all_tickers)})")
        if len(data["tickers"]) < 100:
            break
        page += 1
        if page > 30:  # safety cap
            break
    return all_tickers


def main():
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    universe = {}  # coin_id -> {symbol, pairs: []}
    for exch in ["bybit_spot"]:
        tickers = fetch_all_tickers(exch)
        for t in tickers:
            coin_id = t.get("coin_id")
            target = (t.get("target") or "").upper()
            base = (t.get("base") or "").upper()
            if not coin_id:
                continue
            if target not in QUOTE_WHITELIST:
                continue
            pair_str = f"{base}/{target}"
            entry = universe.setdefault(coin_id, {"symbol": base, "pairs": set()})
            entry["pairs"].add(pair_str)

    logger.info(f"Universe size (unique coin_id with USDT/USD/USDC pair on Bybit spot): {len(universe)}")

    now = datetime.now(timezone.utc).isoformat()
    for coin_id, info in universe.items():
        cur.execute(
            """INSERT INTO coins (coin_id, symbol, bybit_pairs, fetched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(coin_id) DO UPDATE SET
                 symbol=excluded.symbol, bybit_pairs=excluded.bybit_pairs, fetched_at=excluded.fetched_at""",
            (coin_id, info["symbol"], json.dumps(sorted(info["pairs"])), now),
        )
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM coins")
    logger.info(f"coins table now has {cur.fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
