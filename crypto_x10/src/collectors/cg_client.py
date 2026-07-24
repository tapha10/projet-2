"""Minimal, polite CoinGecko public API client (no API key required).

Handles rate limiting (free public tier) with adaptive backoff and retries.
"""
import time
import logging
import requests

BASE_URL = "https://api.coingecko.com/api/v3"
logger = logging.getLogger("cg_client")

# Free public API without a key is limited to roughly 5-15 req/min in practice.
# We stay conservative to avoid getting temporarily banned mid-collection.
MIN_INTERVAL_SEC = 2.2
_last_call = [0.0]


def _throttle():
    elapsed = time.time() - _last_call[0]
    if elapsed < MIN_INTERVAL_SEC:
        time.sleep(MIN_INTERVAL_SEC - elapsed)
    _last_call[0] = time.time()


def cg_get(path, params=None, max_retries=8, timeout=30):
    """GET a CoinGecko endpoint with retry/backoff on 429 and transient errors."""
    url = f"{BASE_URL}{path}"
    backoff = 5.0
    for attempt in range(1, max_retries + 1):
        _throttle()
        try:
            r = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            logger.warning(f"network error on {path}: {e} (attempt {attempt})")
            time.sleep(backoff)
            backoff = min(backoff * 1.7, 90)
            continue

        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            wait = backoff
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    pass
            logger.info(f"429 rate-limited on {path}, sleeping {wait:.0f}s (attempt {attempt})")
            time.sleep(wait)
            backoff = min(backoff * 1.7, 120)
            continue
        if r.status_code in (404,):
            return None
        if r.status_code >= 500:
            logger.warning(f"{r.status_code} on {path}, retrying in {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 1.7, 90)
            continue
        # other 4xx: log and give up
        logger.warning(f"unexpected status {r.status_code} on {path}: {r.text[:200]}")
        return None
    logger.error(f"giving up on {path} after {max_retries} attempts")
    return None
