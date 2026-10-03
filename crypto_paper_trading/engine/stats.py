"""Statistiques de performance, bootstrap et découpage walk-forward."""
from __future__ import annotations

import random
from datetime import datetime


def parse_ts(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def metrics(trades, initial_capital=None):
    """trades : positions fermées (dict avec pnl_usd, r_multiple, opened_at, closed_at,
    mfe_pct, mae_pct). Renvoie un dict de métriques (None si vide)."""
    n = len(trades)
    if n == 0:
        return dict(n=0)
    rs = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    pnls = [float(t["pnl_usd"] or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    ordered = sorted(trades, key=lambda t: (parse_ts(t.get("closed_at")) or 0))
    eq = peak = float(initial_capital or 0)
    max_dd = 0.0
    for t in ordered:
        eq += float(t["pnl_usd"] or 0)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    durs = [(parse_ts(t["closed_at"]) - parse_ts(t["opened_at"])) / 86400
            for t in trades if t.get("closed_at") is not None and t.get("opened_at") is not None]
    mfe = [float(t["mfe_pct"]) for t in trades if t.get("mfe_pct") is not None]
    mae = [float(t["mae_pct"]) for t in trades if t.get("mae_pct") is not None]
    exits = {}
    for t in trades:
        exits[t.get("exit_reason")] = exits.get(t.get("exit_reason"), 0) + 1
    return dict(
        n=n,
        win_rate=len(wins) / n,
        avg_r=sum(rs) / len(rs) if rs else None,
        expectancy_usd=sum(pnls) / n,
        total_pnl_usd=sum(pnls),
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        max_drawdown_pct=max_dd if initial_capital else None,
        avg_duration_days=sum(durs) / len(durs) if durs else None,
        avg_mfe_pct=sum(mfe) / len(mfe) if mfe else None,
        avg_mae_pct=sum(mae) / len(mae) if mae else None,
        exits=exits,
    )


def bootstrap_mean_ci(values, n_boot=4000, alpha=0.05, seed=12345):
    """IC bootstrap (percentiles) de la moyenne. Graine fixe = résultat reproductible."""
    if len(values) < 2:
        return None
    rnd = random.Random(seed)
    n = len(values)
    means = sorted(sum(rnd.choice(values) for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(alpha / 2 * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot) - 1]
    return dict(mean=sum(values) / n, lo=lo, hi=hi, n=n)


def walk_forward_split(items, key, train_frac=0.70):
    items = sorted(items, key=key)
    cut = int(round(len(items) * train_frac))
    return items[:cut], items[cut:]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


SMALL_SAMPLE = 30


def sample_warning(n):
    if n < 10:
        return "échantillon minuscule : aucune conclusion possible"
    if n < SMALL_SAMPLE:
        return "échantillon trop petit pour conclure (< 30 trades)"
    if n < 100:
        return "échantillon encore faible : conclusions provisoires"
    return ""
