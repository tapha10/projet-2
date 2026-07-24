"""Step 3: pull TVL history from DeFiLlama (free, no key, no rate-limit issues
observed, full multi-year history available) and map protocols to CoinGecko
coin_ids via the `gecko_id` field so we can join TVL growth to our price panel.
"""
import logging
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parents[2] / "logs" / "defillama_collector.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("defillama")

BASE = "https://api.llama.fi"


def get(path, retries=5):
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", timeout=30)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"{path} -> {r.status_code}")
        except requests.RequestException as e:
            logger.warning(f"{path} network error: {e}")
        time.sleep(3 * (attempt + 1))
    return None


def main():
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT coin_id FROM coins")
    our_coin_ids = {r[0] for r in cur.fetchall()}

    protocols = get("/protocols")
    if not protocols:
        logger.error("could not fetch protocol list")
        return
    logger.info(f"{len(protocols)} protocols listed on DeFiLlama")

    relevant = [p for p in protocols if p.get("gecko_id") in our_coin_ids]
    logger.info(f"{len(relevant)} protocols map to a coin in our Bybit universe")

    for i, p in enumerate(relevant, 1):
        slug = p["slug"]
        coin_id = p["gecko_id"]
        cur.execute(
            "INSERT OR REPLACE INTO protocol_token_map (protocol_slug, coin_id, protocol_name) VALUES (?,?,?)",
            (slug, coin_id, p.get("name")),
        )
        detail = get(f"/protocol/{slug}")
        if not detail:
            continue
        tvl_points = detail.get("tvl", [])
        rows = []
        for pt in tvl_points:
            date = datetime.utcfromtimestamp(pt["date"]).strftime("%Y-%m-%d")
            rows.append((slug, date, pt.get("totalLiquidityUSD")))
        cur.executemany(
            """INSERT INTO tvl_history (protocol_slug, date, tvl_usd) VALUES (?,?,?)
               ON CONFLICT(protocol_slug, date) DO UPDATE SET tvl_usd=excluded.tvl_usd""",
            rows,
        )
        conn.commit()
        logger.info(f"[{i}/{len(relevant)}] {slug} ({coin_id}): {len(rows)} TVL points")
        time.sleep(0.3)

    conn.close()
    logger.info("DeFiLlama collection complete")


if __name__ == "__main__":
    main()
