"""Veille des annonces officielles des exchanges (LECTURE SEULE, pages publiques).

Sources accessibles depuis l'environnement cloud (testé le 03/10/2026) :
  Binance (listings, delistings), OKX (nouveaux listings), KuCoin (nouveaux listings),
  Bitget (listings spot et futures), Bithumb (listings, mises sous surveillance,
  levées de surveillance, fins de cotation). Upbit, Gate et Bybit renvoient 403.

Chaque annonce : dict(exchange, title, url, published_at (s UTC), symbols [..], kind)
  kind ∈ listing | perp | warning_lifted | warning | delisting | other
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from .market import http_json

KST = timezone(timedelta(hours=9))
STOP = {"USD", "USDT", "USDC", "KRW", "BTC", "ETH", "EUR", "TRY", "BRL", "API", "NEW", "THE", "FOR", "AND",
        "UPDATE", "WILL", "SPOT", "LIST", "VIP", "APR", "CEO", "NFT", "AI", "UTC", "KYC", "P2P", "OTC", "BNB",
        "USDⓈ", "TRADING", "FUTURES", "PERPETUAL", "LAUNCH", "MARGIN", "BOTS", "EARN", "ROUND"}

_PATTERNS = (
    re.compile(r"\(([A-Z0-9]{2,15})\)"),                 # Concrete (CT)
    re.compile(r"\b([A-Z0-9]{2,15})USDT\b"),             # CTUSDT
    re.compile(r"\b([A-Z0-9]{2,15})/US[DT]+\b"),         # GRVT/USD, GRVT/USDT
    re.compile(r"\b([A-Z0-9]{2,15})-USDT\b"),
)


def extract_symbols(title):
    out = []
    for p in _PATTERNS:
        for m in p.findall(title or ""):
            s = m.upper().strip()
            if s not in STOP and not s.isdigit() and s not in out:
                out.append(s)
    return out


def classify(title, exchange="", hint=None):
    t = (title or "").lower()
    raw = title or ""
    if hint == "delisting" or "delist" in t or "거래지원 종료" in raw or "removal of spot" in t:
        return "delisting"
    if ("유의" in raw and "해제" in raw) or ("caution" in t and ("lift" in t or "remov" in t)):
        return "warning_lifted"
    if "유의" in raw or "investment warning" in t or "monitoring tag" in t or "caution" in t:
        return "warning"
    if "perpetual" in t or "futures" in t or "launched for futures" in t:
        return "perp"
    if ("list" in t or "launch" in t or "world premiere" in t or "마켓 추가" in raw
            or "거래지원 안내" in raw or "신규" in raw):
        return "listing"
    return "other"


def _ms(x):
    return int(x) / 1000.0


def fetch_binance():
    out = []
    for cat, hint in ((48, None), (161, "delisting")):
        d = http_json(f"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
                      f"?type=1&catalogId={cat}&pageNo=1&pageSize=20")
        for c in d["data"]["catalogs"]:
            for a in c["articles"]:
                out.append(dict(exchange="binance", title=a["title"], published_at=_ms(a["releaseDate"]),
                                url=f"https://www.binance.com/en/support/announcement/{a.get('code', '')}",
                                hint=hint))
    return out


def fetch_okx():
    d = http_json("https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings")
    return [dict(exchange="okx", title=x["title"], url=x["url"], published_at=_ms(x["pTime"]))
            for blk in d.get("data", []) for x in blk.get("details", [])]


def fetch_kucoin():
    d = http_json("https://api.kucoin.com/api/v3/announcements?annType=new-listings&pageSize=30")
    return [dict(exchange="kucoin", title=x["annTitle"], url=x.get("annUrl"), published_at=_ms(x["cTime"]))
            for x in d["data"]["items"]]


def fetch_bitget():
    d = http_json("https://api.bitget.com/api/v2/public/annoucements?language=en_US&annType=coin_listings")
    return [dict(exchange="bitget", title=x["annTitle"], url=x["annUrl"], published_at=_ms(x["cTime"]))
            for x in d.get("data", [])]


def fetch_bithumb():
    d = http_json("https://api.bithumb.com/v1/notices")
    out = []
    for x in d:
        ts = datetime.strptime(x["published_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).timestamp()
        out.append(dict(exchange="bithumb", title=x["title"], url=x.get("pc_url"), published_at=ts))
    return out


FETCHERS = {"binance": fetch_binance, "okx": fetch_okx, "kucoin": fetch_kucoin,
            "bitget": fetch_bitget, "bithumb": fetch_bithumb}


def recent(hours=48, now=None, fetchers=None):
    """Annonces des `hours` dernières heures, classées, avec symboles extraits.
    Renvoie (annonces, erreurs par source)."""
    now = now or time.time()
    items, errors = [], {}
    for name, fn in (fetchers or FETCHERS).items():
        try:
            for a in fn():
                if now - a["published_at"] > hours * 3600 or a["published_at"] > now + 600:
                    continue
                a["kind"] = classify(a["title"], name, a.pop("hint", None))
                a["symbols"] = extract_symbols(a["title"])
                items.append(a)
        except Exception as e:
            errors[name] = str(e)[:120]
    items.sort(key=lambda a: -a["published_at"])
    return items, errors


POSITIVE = {"listing", "perp", "warning_lifted"}
NEGATIVE = {"warning", "delisting"}


def by_pair(items, universe):
    """Regroupe par pair canonique (ABCUSDT) présent dans l'univers surveillé."""
    out = {}
    for a in items:
        for s in a["symbols"]:
            pair = s + "USDT"
            if pair in universe:
                out.setdefault(pair, []).append(a)
    return out


def to_news(a):
    """Format `news[]` de la routine 1 (date de publication exacte, source officielle)."""
    if a["kind"] in NEGATIVE:
        typ = "exchange_warning"          # gardée comme preuve datée, sans point de score
    else:
        typ = "listing_or_perp" if a["kind"] in ("listing", "perp") else "dated_announcement"
    return dict(type=typ, url=a.get("url"), titre=f"[{a['exchange']}] {a['title']}",
                date_publication=datetime.fromtimestamp(a["published_at"], tz=timezone.utc).isoformat(),
                source="annonce_exchange", kind=a["kind"])
