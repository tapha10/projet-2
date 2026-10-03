"""Rejeu historique (réseau) : VELVET, PUMP, COTI et les paliers.

1) Contrôle de cohérence avec le test manuel : stop 5 % / objectif +30 % (= 6 R),
   entrée à l'ouverture de chaque jour, sortie au bout de 10 jours, bougies 1 h,
   stop compté d'abord si stop et objectif tombent dans la même bougie.
   Attendu (VELVET, test manuel) : ~13 % d'objectifs, ~71 % de stops, R moyen ~ -0,5.
2) Paliers P1-P4 (ombre) et découpes 50/30/20, 30/30/40, 70/20/10, 100/0/0 sur les mêmes entrées.

python3 tests/replay_history_2ter.py [--days 120] > docs/replay_2ter.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import indicators, market, risk, simulate, tiers  # noqa: E402

DAY = 86400
PAIRS = ("VELVETUSDT", "PUMPUSDT", "COTIUSDT")


def manual_rule(pair, hourly, daily, start_ts, end_ts):
    params = {"stop": {"type": "fixed_pct", "pct": 0.05}, "tp": {"type": "fixed_pct", "pct": 0.30},
              "max_leverage": 3, "max_hold_days": 10, "breakeven_trigger_pct": None, "trailing": None}
    cfg = {"risk_pct": 0.01, "max_leverage": 3, "maintenance_margin_rate": 0.01, "liquidation_buffer_pct": 0.02}
    res = []
    for d in daily:
        if d["t"] < start_ts or d["t"] + 10 * DAY > end_ts:
            continue
        rows = [r for r in hourly if d["t"] <= r["t"] < d["t"] + 10 * DAY + 3600]
        if not rows:
            continue
        plan = risk.plan_position(params, d["o"], 1000.0, cfg)
        rep = simulate.replay(plan, rows, d["t"], 0.0005, 0.0001, 0.001, 3600)
        res.append(rep)
    n = len(res)
    if not n:
        return dict(n=0)
    by = {}
    for r in res:
        by[r["exit_reason"]] = by.get(r["exit_reason"], 0) + 1
    return dict(n=n, tp_rate=by.get("tp", 0) / n, sl_rate=by.get("sl", 0) / n, time_rate=by.get("time", 0) / n,
                avg_r=sum(r["r_multiple"] for r in res) / n, exits=by)


def tiers_and_splits(hourly, daily, start_ts, end_ts):
    out = {t: [] for t in tiers.TIERS}
    splits = {k: [] for k in tiers.SPLITS}
    complete_d = []
    for d in daily:
        complete_d.append(d)
        if d["t"] < start_ts or d["t"] + 30 * DAY > end_ts:
            continue
        atr = indicators.atr([x for x in complete_d[:-1]][-30:])
        rows = [r for r in hourly if d["t"] <= r["t"] < d["t"] + 31 * DAY]
        for t in tiers.TIERS:
            s = tiers.shadow_tier_trade(t, d["o"], atr, rows, d["t"])
            if s:
                out[t].append(s)
        for name, sp in tiers.SPLITS.items():
            splits[name].append(tiers.replay_split(d["o"], atr, rows, d["t"], sp)["r_multiple"])
    summ = {}
    for t, v in out.items():
        n = len(v)
        summ[t] = dict(n=n, win_rate=(sum(1 for x in v if x["win"]) / n) if n else None,
                       avg_r=(sum(x["r"] for x in v) / n) if n else None, breakeven=tiers.BREAKEVEN[t])
    sp = {k: dict(n=len(v), avg_r=(sum(v) / len(v)) if v else None) for k, v in splits.items()}
    return summ, sp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=150)
    a = ap.parse_args()
    now = time.time()
    start = now - a.days * DAY
    report = {}
    for pair in PAIRS:
        try:
            daily, src = market.candles(pair, "1d", start - 40 * DAY, now)
            hourly, _ = market.candles(pair, "1h", start, now)
        except Exception as e:
            report[pair] = dict(error=str(e)[:200])
            continue
        listed = daily[0]["t"]
        man = manual_rule(pair, hourly, daily, max(start, listed), now)
        tsum, ssum = tiers_and_splits(hourly, daily, max(start, listed + 15 * DAY), now)
        report[pair] = dict(source=src, first_daily=time.strftime("%Y-%m-%d", time.gmtime(daily[0]["t"])),
                            n_hourly=len(hourly), manual_rule_5_30=man, tiers=tsum, splits=ssum)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
