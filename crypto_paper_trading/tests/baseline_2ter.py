"""Référence de non-régression des bras A, B, C (addendum 2ter).

`python3 tests/baseline_2ter.py --write` fige les résultats de rejeu des bras sur
des trajectoires synthétiques déterministes ; le test `test_2ter.TestNonRegression`
les recalcule et exige l'égalité exacte.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from engine import risk, simulate  # noqa: E402

PATH = os.path.join(HERE, "baseline_before_2ter.json")
ARMS = {
    "A": {"stop": {"type": "fixed_pct", "pct": 0.25}, "tp": {"type": "fixed_pct", "pct": 0.40},
          "max_leverage": 2, "max_hold_days": 10, "breakeven_trigger_pct": None, "trailing": None},
    "B": {"stop": {"type": "fixed_pct", "pct": 0.12}, "tp": {"type": "fixed_pct", "pct": 0.40},
          "max_leverage": 10, "max_hold_days": 10, "breakeven_trigger_pct": 0.15, "trailing": None},
    "C": {"stop": {"type": "atr", "mult": 1.5, "period": 14, "min_pct": 0.10, "max_pct": 0.25},
          "tp": {"type": "r_multiple", "r": 2.5}, "max_leverage": 10, "max_hold_days": 10,
          "breakeven_trigger_pct": None, "trailing": {"activate_pct": 0.20, "distance": "stop_distance"}},
}
CFG = {"risk_pct": 0.01, "max_leverage": 10, "maintenance_margin_rate": 0.01, "liquidation_buffer_pct": 0.02}


def paths(n=120, hours=11 * 24, seed=2026):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        p, rows = 100.0, []
        drift = rnd.uniform(-0.002, 0.004)
        vol = rnd.uniform(0.01, 0.05)
        for h in range(hours):
            o = p
            c = max(0.01, o * (1 + rnd.gauss(drift, vol)))
            hi = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
            lo = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
            rows.append(dict(t=h * 3600, o=o, h=hi, l=lo, c=c, vq=1.0))
            p = c
        out.append(dict(atr=rnd.uniform(3, 30), rows=rows))
    return out


def compute():
    res = {}
    for arm, params in ARMS.items():
        rs = []
        for p in paths():
            plan = risk.plan_position(params, 100.0, 1000.0, CFG, p["atr"])
            rep = simulate.replay(plan, p["rows"], 0, 0.0005, 0.0001, 0.001, 3600)
            rs.append([round(plan["size_usd"], 6), plan["leverage"], rep["exit_reason"],
                       round(rep["r_multiple"], 6), round(rep["pnl_usd"], 6)])
        res[arm] = rs
    return res


if __name__ == "__main__":
    if "--write" in sys.argv:
        with open(PATH, "w") as f:
            json.dump(compute(), f)
        print("baseline écrite :", PATH)
    else:
        print(json.dumps({k: v[:3] for k, v in compute().items()}, indent=1))
