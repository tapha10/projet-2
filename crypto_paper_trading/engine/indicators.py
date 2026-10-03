"""Indicateurs simples sur bougies journalières (dict t,o,h,l,c,vq)."""
from __future__ import annotations


def atr(daily, period=14):
    """ATR de Wilder sur bougies journalières complètes. None si historique insuffisant."""
    if len(daily) < 6:
        return None
    period = min(period, len(daily) - 1)  # historique court : ATR sur moins de jours
    trs = []
    for prev, cur in zip(daily, daily[1:]):
        trs.append(max(cur["h"] - cur["l"], abs(cur["h"] - prev["c"]), abs(cur["l"] - prev["c"])))
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:period], closes[1:period + 1]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / period, losses / period
    for a, b in zip(closes[period:], closes[period + 1:]):
        d = b - a
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + max(-d, 0)) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def volume_ratio(daily, current_quote_vol=None, lookback=14):
    """Volume (24 h courant ou dernière bougie) / moyenne des `lookback` jours complets précédents."""
    if len(daily) < 3:
        return None
    hist = daily[:-1][-lookback:]
    avg = sum(d["vq"] for d in hist) / len(hist) if hist else 0
    cur = current_quote_vol if current_quote_vol is not None else daily[-1]["vq"]
    return cur / avg if avg > 0 else None


def volume_doubling(daily, days=2):
    """Vrai si le volume a au moins doublé chaque jour sur les `days` derniers jours."""
    if len(daily) < days + 1:
        return False
    seq = [d["vq"] for d in daily[-(days + 1):]]
    return all(b >= 2 * a > 0 for a, b in zip(seq, seq[1:]))
