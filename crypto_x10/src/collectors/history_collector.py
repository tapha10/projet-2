"""Step 2: pull, for every coin in the Bybit universe:
  - daily price / market_cap / volume history (CoinGecko market_chart, days=365 -
    the maximum allowed by the free public API tier)
  - a current snapshot of dev activity / social / supply / FDV / ATH-ATL

Resumable: skips coins already fully collected (checked via collection_log).
Designed to run for a long time (hundreds of coins x ~2.2s throttle) so it is
meant to be launched in the background with nohup.
"""
import json
import logging
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collectors.cg_client import cg_get
from src.db.db import get_conn, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parents[2] / "logs" / "history_collector.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("history_collector")


def already_done(cur, coin_id):
    cur.execute(
        "SELECT 1 FROM collection_log WHERE coin_id=? AND step='full_history' AND status='ok'",
        (coin_id,),
    )
    return cur.fetchone() is not None


def log_status(cur, conn, step, coin_id, status, message=""):
    cur.execute(
        "INSERT INTO collection_log (ts, step, coin_id, status, message) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), step, coin_id, status, message[:300]),
    )
    conn.commit()


def collect_price_history(cur, conn, coin_id):
    data = cg_get(f"/coins/{coin_id}/market_chart", params={"vs_currency": "usd", "days": 365, "interval": "daily"})
    if not data or "prices" not in data:
        return False
    prices = data.get("prices", [])
    mcaps = dict((round(m[0] / 1000) , m[1]) for m in data.get("market_caps", []))
    vols = dict((round(v[0] / 1000), v[1]) for v in data.get("total_volumes", []))
    rows = []
    for ts_ms, price in prices:
        date = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        key = round(ts_ms / 1000)
        mcap = mcaps.get(key)
        vol = vols.get(key)
        rows.append((coin_id, date, price, mcap, vol))
    cur.executemany(
        """INSERT INTO price_history (coin_id, date, price_usd, market_cap_usd, volume_usd)
           VALUES (?,?,?,?,?)
           ON CONFLICT(coin_id, date) DO UPDATE SET
             price_usd=excluded.price_usd, market_cap_usd=excluded.market_cap_usd, volume_usd=excluded.volume_usd""",
        rows,
    )
    conn.commit()
    return len(rows) > 0


def collect_snapshot(cur, conn, coin_id):
    data = cg_get(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "true",
            "sparkline": "false",
        },
    )
    if not data:
        return False

    market_data = data.get("market_data") or {}
    dev = data.get("developer_data") or {}
    community = data.get("community_data") or {}
    sentiment_up = data.get("sentiment_votes_up_percentage")
    sentiment_down = data.get("sentiment_votes_down_percentage")
    links = data.get("links") or {}
    github_urls = (links.get("repos_url") or {}).get("github") or []

    def g(d, k):
        v = d.get(k) if d else None
        return v

    row = (
        coin_id,
        datetime.now(timezone.utc).isoformat(),
        g(market_data, "fully_diluted_valuation", ).get("usd") if isinstance(g(market_data, "fully_diluted_valuation"), dict) else None,
        g(market_data, "circulating_supply"),
        g(market_data, "total_supply"),
        g(market_data, "max_supply"),
        (market_data.get("ath") or {}).get("usd"),
        (market_data.get("ath_date") or {}).get("usd"),
        (market_data.get("ath_change_percentage") or {}).get("usd"),
        (market_data.get("atl") or {}).get("usd"),
        (market_data.get("atl_date") or {}).get("usd"),
        github_urls[0] if github_urls else None,
        dev.get("stars"),
        dev.get("forks"),
        dev.get("subscribers"),
        dev.get("total_issues"),
        dev.get("closed_issues"),
        dev.get("pull_requests_merged"),
        dev.get("pull_request_contributors"),
        dev.get("commit_count_4_weeks"),
        community.get("twitter_followers"),
        community.get("reddit_subscribers"),
        community.get("telegram_channel_user_count"),
        sentiment_up,
        sentiment_down,
    )
    cur.execute(
        """INSERT INTO coin_snapshot (
            coin_id, fetched_at, fdv_usd, circulating_supply, total_supply, max_supply,
            ath_usd, ath_date, ath_change_pct, atl_usd, atl_date, github_url,
            gh_stars, gh_forks, gh_subscribers, gh_total_issues, gh_closed_issues,
            gh_pr_merged, gh_pr_contributors, gh_commit_count_4w,
            twitter_followers, reddit_subscribers, telegram_user_count,
            sentiment_up_pct, sentiment_down_pct
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(coin_id) DO UPDATE SET
            fetched_at=excluded.fetched_at, fdv_usd=excluded.fdv_usd,
            circulating_supply=excluded.circulating_supply, total_supply=excluded.total_supply,
            max_supply=excluded.max_supply, ath_usd=excluded.ath_usd, ath_date=excluded.ath_date,
            ath_change_pct=excluded.ath_change_pct, atl_usd=excluded.atl_usd, atl_date=excluded.atl_date,
            github_url=excluded.github_url, gh_stars=excluded.gh_stars, gh_forks=excluded.gh_forks,
            gh_subscribers=excluded.gh_subscribers, gh_total_issues=excluded.gh_total_issues,
            gh_closed_issues=excluded.gh_closed_issues, gh_pr_merged=excluded.gh_pr_merged,
            gh_pr_contributors=excluded.gh_pr_contributors, gh_commit_count_4w=excluded.gh_commit_count_4w,
            twitter_followers=excluded.twitter_followers, reddit_subscribers=excluded.reddit_subscribers,
            telegram_user_count=excluded.telegram_user_count, sentiment_up_pct=excluded.sentiment_up_pct,
            sentiment_down_pct=excluded.sentiment_down_pct
        """,
        row,
    )

    # also update coins table with categories / platforms / genesis / rank
    cur.execute(
        """UPDATE coins SET market_cap_rank_current=?, genesis_date=?, categories=?, platforms=?, name=?
           WHERE coin_id=?""",
        (
            market_data.get("market_cap_rank"),
            data.get("genesis_date"),
            json.dumps(data.get("categories") or []),
            json.dumps(data.get("platforms") or {}),
            data.get("name"),
            coin_id,
        ),
    )
    conn.commit()
    return True


def main(limit=None):
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT coin_id FROM coins ORDER BY coin_id")
    coin_ids = [r[0] for r in cur.fetchall()]
    if limit:
        coin_ids = coin_ids[:limit]

    total = len(coin_ids)
    logger.info(f"Starting collection for {total} coins")

    for i, coin_id in enumerate(coin_ids, 1):
        if already_done(cur, coin_id):
            logger.info(f"[{i}/{total}] {coin_id}: already collected, skipping")
            continue
        try:
            ok_price = collect_price_history(cur, conn, coin_id)
            ok_snap = collect_snapshot(cur, conn, coin_id)
            if ok_price and ok_snap:
                log_status(cur, conn, "full_history", coin_id, "ok")
                logger.info(f"[{i}/{total}] {coin_id}: OK")
            else:
                log_status(cur, conn, "full_history", coin_id, "partial", f"price={ok_price} snap={ok_snap}")
                logger.warning(f"[{i}/{total}] {coin_id}: PARTIAL price={ok_price} snap={ok_snap}")
        except Exception as e:
            log_status(cur, conn, "full_history", coin_id, "error", str(e))
            logger.exception(f"[{i}/{total}] {coin_id}: ERROR {e}")

    conn.close()
    logger.info("Collection run complete")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=lim)
