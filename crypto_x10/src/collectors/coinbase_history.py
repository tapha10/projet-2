"""Step 2b (robustness dataset): pull full daily OHLCV history from Coinbase
Exchange's public API (no key needed, not geo-blocked) for every Bybit-universe
coin that is also listed on Coinbase against USD or USDC.

This is used to (a) cross-check the CoinGecko 365-day panel and (b) detect
x5/x10/... events further back in time (years) for the subset of coins that
are cross-listed, since Bybit's own API and Binance's API are geo-blocked from
this environment and CoinGecko's free tier caps history at 365 days.
"""
import logging
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parents[2] / "logs" / "coinbase_history.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("coinbase_history")

BASE = "https://api.exchange.coinbase.com"
HEADERS = {"User-Agent": "crypto-x10-research/1.0"}
GRANULARITY = 86400  # daily
MAX_CANDLES_PER_CALL = 300


def get_json(path, params=None, retries=6):
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
        except requests.RequestException as e:
            logger.warning(f"{path} network error: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue
        logger.warning(f"{path} -> {r.status_code}: {r.text[:150]}")
        time.sleep(2)
    return None


def list_products():
    data = get_json("/products")
    if not data:
        return []
    return [p for p in data if p.get("quote_currency") in ("USD", "USDC") and p.get("status") == "online"]


def get_product_candles_full_history(product_id, start_date="2015-01-01"):
    """Paginate backwards is unreliable; instead paginate forward in chunks of
    MAX_CANDLES_PER_CALL days from the product's listing (approximated by walking
    forward from start_date until data appears) to now."""
    end = datetime.now(timezone.utc)
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    all_rows = []
    cur_start = start
    chunk = timedelta(days=MAX_CANDLES_PER_CALL - 1)
    empty_streak = 0
    while cur_start < end:
        cur_end = min(cur_start + chunk, end)
        params = {
            "granularity": GRANULARITY,
            "start": cur_start.isoformat(),
            "end": cur_end.isoformat(),
        }
        data = get_json(f"/products/{product_id}/candles", params=params)
        time.sleep(0.35)
        if data:
            all_rows.extend(data)
            empty_streak = 0
        else:
            empty_streak += 1
        cur_start = cur_end + timedelta(days=1)
    return all_rows


def main(limit=None):
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT coin_id, symbol FROM coins")
    universe = {sym.upper(): cid for cid, sym in cur.fetchall()}

    products = list_products()
    logger.info(f"{len(products)} USD/USDC products live on Coinbase")

    matched = []
    for p in products:
        base = p["base_currency"].upper()
        if base in universe:
            matched.append((universe[base], p["id"]))
    # dedupe: prefer USD pair over USDC if both present
    best = {}
    for coin_id, product_id in matched:
        if coin_id not in best:
            best[coin_id] = product_id
        elif product_id.endswith("-USD") and best[coin_id].endswith("-USDC"):
            best[coin_id] = product_id
    logger.info(f"{len(best)} Bybit-universe coins also listed on Coinbase")

    items = list(best.items())
    if limit:
        items = items[:limit]

    cur.execute("SELECT DISTINCT coin_id FROM cb_price_history")
    already = {r[0] for r in cur.fetchall()}

    for i, (coin_id, product_id) in enumerate(items, 1):
        if coin_id in already:
            logger.info(f"[{i}/{len(items)}] {coin_id} ({product_id}): already collected, skipping")
            continue
        try:
            candles = get_product_candles_full_history(product_id)
            rows = []
            for c in candles:
                # [time, low, high, open, close, volume]
                ts, low, high, openp, close, vol = c
                date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                rows.append((coin_id, product_id, date, openp, high, low, close, vol))
            cur.executemany(
                """INSERT INTO cb_price_history (coin_id, product_id, date, open, high, low, close, volume)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(coin_id, date) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume""",
                rows,
            )
            conn.commit()
            logger.info(f"[{i}/{len(items)}] {coin_id} ({product_id}): {len(rows)} daily candles")
        except Exception as e:
            logger.exception(f"[{i}/{len(items)}] {coin_id}: ERROR {e}")

    conn.close()
    logger.info("Coinbase history collection complete")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=lim)
