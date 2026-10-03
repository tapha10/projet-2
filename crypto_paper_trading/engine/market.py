"""Données de marché publiques en LECTURE SEULE (aucune clé, aucun ordre).

Plusieurs sources sont essayées dans l'ordre : certaines sont bloquées selon
la région (Binance renvoie 451 et Bybit 403 depuis l'environnement cloud).
Chaque fonction renvoie aussi le nom de la source réellement utilisée.

Format canonique d'un pair : "ABCUSDT" (contrat perpétuel linéaire USDT).
Format d'une bougie : dict(t=début en secondes UTC, o, h, l, c, vq=volume en USDT).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (paper-trading-research; read-only)"}
DEFAULT_SOURCES = ("gate", "okx", "mexc", "kucoin")
INTERVAL_SECONDS = {"1m": 60, "15m": 900, "1h": 3600, "1d": 86400}


class DataError(RuntimeError):
    pass


def http_json(url: str, retries: int = 3, timeout: int = 20):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:  # 4xx : inutile d'insister (sauf 429)
            last = e
            if e.code != 429 and 400 <= e.code < 500:
                break
        except Exception as e:  # réseau
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise DataError(f"{url}: {last}")


def base_of(pair: str) -> str:
    pair = pair.upper().replace("-", "").replace("_", "").replace("/", "")
    if pair.endswith("USDTM"):
        pair = pair[:-1]
    if not pair.endswith("USDT"):
        raise ValueError(f"pair non USDT : {pair}")
    return pair[:-4]


def canonical(pair: str) -> str:
    return base_of(pair) + "USDT"


# ------------------------------------------------------------------ bougies
def _gate_candles(base, interval, start, end):
    step = INTERVAL_SECONDS[interval]
    out, cur = [], start
    while cur < end:
        stop = min(end, cur + step * 1900)
        q = urllib.parse.urlencode({"contract": f"{base}_USDT", "interval": interval,
                                    "from": int(cur), "to": int(stop)})
        data = http_json(f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?{q}")
        for k in data:
            out.append(dict(t=int(k["t"]), o=float(k["o"]), h=float(k["h"]), l=float(k["l"]),
                            c=float(k["c"]), vq=float(k.get("sum") or 0)))
        cur = stop + 1
    return out


def _okx_candles(base, interval, start, end):
    bar = {"1m": "1m", "15m": "15m", "1h": "1H", "1d": "1Dutc"}[interval]
    out, after = [], int(end * 1000) + 1
    for _ in range(60):
        q = urllib.parse.urlencode({"instId": f"{base}-USDT-SWAP", "bar": bar,
                                    "after": after, "limit": 100})
        data = http_json(f"https://www.okx.com/api/v5/market/history-candles?{q}")
        rows = data.get("data") or []
        if data.get("code") not in ("0", 0) or not rows:
            break
        for k in rows:
            out.append(dict(t=int(k[0]) // 1000, o=float(k[1]), h=float(k[2]), l=float(k[3]),
                            c=float(k[4]), vq=float(k[7]) if len(k) > 7 else 0.0))
        after = int(rows[-1][0])
        if after / 1000 <= start:
            break
    return out


def _mexc_candles(base, interval, start, end):
    iv = {"1m": "Min1", "15m": "Min15", "1h": "Min60", "1d": "Day1"}[interval]
    q = urllib.parse.urlencode({"interval": iv, "start": int(start), "end": int(end)})
    data = http_json(f"https://contract.mexc.com/api/v1/contract/kline/{base}_USDT?{q}")
    d = data.get("data") or {}
    return [dict(t=int(t), o=float(o), h=float(h), l=float(l), c=float(c), vq=float(a))
            for t, o, h, l, c, a in zip(d.get("time", []), d.get("open", []), d.get("high", []),
                                        d.get("low", []), d.get("close", []), d.get("amount", []))]


def _kucoin_candles(base, interval, start, end):
    gran = {"1m": 1, "15m": 15, "1h": 60, "1d": 1440}[interval]
    sym = ("XBT" if base == "BTC" else base) + "USDTM"
    q = urllib.parse.urlencode({"symbol": sym, "granularity": gran,
                                "from": int(start * 1000), "to": int(end * 1000)})
    data = http_json(f"https://api-futures.kucoin.com/api/v1/kline/query?{q}")
    return [dict(t=int(k[0]) // 1000, o=float(k[1]), h=float(k[2]), l=float(k[3]),
                 c=float(k[4]), vq=float(k[6]) if len(k) > 6 else 0.0)
            for k in (data.get("data") or [])]


_CANDLES = {"gate": _gate_candles, "okx": _okx_candles,
            "mexc": _mexc_candles, "kucoin": _kucoin_candles}


def candles(pair, interval, start, end=None, sources=DEFAULT_SOURCES):
    """Bougies [start, end] triées, sans doublon. Renvoie (bougies, source)."""
    end = end or time.time()
    base = base_of(pair)
    errors = []
    for src in sources:
        try:
            rows = _CANDLES[src](base, interval, start, end)
        except Exception as e:  # source bloquée ou pair absent : on passe à la suivante
            errors.append(f"{src}: {e}")
            continue
        uniq = {r["t"]: r for r in rows if start - INTERVAL_SECONDS[interval] < r["t"] <= end}
        if uniq:
            return [uniq[t] for t in sorted(uniq)], src
        errors.append(f"{src}: aucune bougie")
    raise DataError(f"{pair} {interval}: " + " | ".join(errors))


def fine_candles(pair, start, end, sources=DEFAULT_SOURCES):
    """Bougies 1 min de [start, end) pour trancher l'ordre stop / objectif (Gate garde
    environ 6 jours de 1 min, OKX prend le relais au-delà). Renvoie (bougies, source)."""
    rows, src = candles(pair, "1m", start, end - 1, sources)
    return [r for r in rows if start <= r["t"] < end], src


def funding_history(pair, start, end):
    """Taux de funding réellement réglés entre start et end (Gate) : [(t, taux)].
    Positif = les longs paient. Gate et Bybit ont des taux proches mais pas identiques."""
    q = urllib.parse.urlencode({"contract": f"{base_of(pair)}_USDT", "limit": 1000,
                                "from": int(start), "to": int(end)})
    data = http_json(f"https://api.gateio.ws/api/v4/futures/usdt/funding_rate?{q}")
    return sorted((int(d["t"]), float(d["r"])) for d in data if start < int(d["t"]) <= end), "gate"


# ------------------------------------------------------------------ tickers
def tickers(sources=("gate", "mexc")):
    """Tous les perps USDT : last, change_24h (fraction), quote_vol_24h, funding."""
    errors = []
    for src in sources:
        try:
            if src == "gate":
                data = http_json("https://api.gateio.ws/api/v4/futures/usdt/tickers")
                out = [dict(pair=canonical(t["contract"]), last=float(t["last"] or 0),
                            change_24h=float(t["change_percentage"] or 0) / 100,
                            quote_vol_24h=float(t.get("volume_24h_quote") or 0),
                            funding_rate=float(t.get("funding_rate") or 0))
                       for t in data if t["contract"].endswith("_USDT")]
            elif src == "mexc":
                data = http_json("https://contract.mexc.com/api/v1/contract/ticker")["data"]
                out = [dict(pair=canonical(t["symbol"]), last=float(t["lastPrice"]),
                            change_24h=float(t["riseFallRate"]),
                            quote_vol_24h=float(t.get("amount24") or 0),
                            funding_rate=float(t.get("fundingRate") or 0))
                       for t in data if t["symbol"].endswith("_USDT")]
            else:
                continue
            return [t for t in out if t["last"] > 0], src
        except Exception as e:
            errors.append(f"{src}: {e}")
    raise DataError("tickers: " + " | ".join(errors))


def crypto_contracts():
    """Perps USDT crypto de Gate (exclut actions, indices, métaux, forex, pré-marché).
    Renvoie {pair: date de lancement (s)}."""
    data = http_json("https://api.gateio.ws/api/v4/futures/usdt/contracts")
    return {canonical(c["name"]): int(c.get("launch_time") or c.get("create_time") or 0)
            for c in data if c["name"].endswith("_USDT") and not c.get("contract_type")
            and not c.get("is_pre_market") and not c.get("in_delisting")}


def new_listings(days=7, contracts=None):
    """Perps crypto listés depuis moins de `days` jours (date de lancement datée)."""
    contracts = contracts if contracts is not None else crypto_contracts()
    now = time.time()
    return [dict(pair=p, launched_at=lt) for p, lt in contracts.items()
            if lt and now - lt < days * 86400], "gate"


def open_interest_usd(pair, days=7):
    """Série journalière de l'open interest en USD (Gate). Liste de (t, oi_usd)."""
    q = urllib.parse.urlencode({"contract": f"{base_of(pair)}_USDT", "interval": "1d",
                                "limit": days})
    data = http_json(f"https://api.gateio.ws/api/v4/futures/usdt/contract_stats?{q}")
    return [(int(d["time"]), float(d.get("open_interest_usd") or 0)) for d in data], "gate"


def last_price(pair, sources=DEFAULT_SOURCES):
    now = time.time()
    rows, src = candles(pair, "15m", now - 3 * 3600, now, sources)
    return rows[-1]["c"], src
