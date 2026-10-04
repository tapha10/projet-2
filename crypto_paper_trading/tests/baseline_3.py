"""Référence de non-régression avant le prompt 3 (routine 7, chaînes de victoires).

`python3 tests/baseline_3.py --write` fige les résultats actuels :
- rejeu des bras A, B, C sur trajectoires synthétiques (baseline_2ter) ;
- rejeu des découpes du portefeuille T (paliers) sur les mêmes trajectoires ;
- cycle sec de 14 jours des routines 1 à 6 (engine.dryrun) : positions, journal, état des paliers.
Le test `test_chains.TestNonRegression3` recalcule tout et exige l'égalité exacte.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import baseline_2ter  # noqa: E402
from engine import dryrun, tiers  # noqa: E402

PATH = os.path.join(HERE, "baseline_before_3.json")


def r6(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: r6(v) for k, v in sorted(x.items())}
    if isinstance(x, (list, tuple)):
        return [r6(v) for v in x]
    return x


def compute():
    out = {"abc": baseline_2ter.compute()}
    splits = {}
    for i, p in enumerate(baseline_2ter.paths()[:40]):
        for split in ((0.5, 0.3, 0.2), (1.0, 0.0, 0.0)):
            res = tiers.replay_split(100.0, p["atr"], p["rows"], 0, split, candle_seconds=3600)
            splits.setdefault("/".join(str(s) for s in split), []).append(r6(res))
    out["tiers_splits"] = splits
    db, order = dryrun.run(days=14)
    out["dryrun"] = dict(
        order=[list(o) for o in order],
        positions=[r6({k: p.get(k) for k in ("pair", "status", "pnl_usd", "r_multiple", "opened_ts")})
                   for p in db.positions],
        log=[[row["routine"], json.dumps(row["change"], sort_keys=True)] for row in db.log],
        tier_state=r6(db.config.get("tier_state")),
        n_signals=len(db.signals), n_shadow=len(db.shadow))
    return out


if __name__ == "__main__":
    if "--write" in sys.argv:
        with open(PATH, "w") as f:
            json.dump(compute(), f)
        print("référence écrite :", PATH)
    else:
        c = compute()
        print({k: (len(v) if hasattr(v, "__len__") else v) for k, v in c.items()})
