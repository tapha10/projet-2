"""Addendum 2ter — cycle complet en MODE SEC (aucune écriture en production).

Rejoue N jours de routines dans l'ordre horaire réel (Europe/Paris) avec un marché
synthétique déterministe et une « base » en mémoire qui imite les tables utiles
(signals, signal_features, shadow_trades, positions T, iteration_log, config + verrous).
Le calcul passe par les MÊMES fonctions que la production (cli2ter, tiers, discovery).

  python -m engine.dryrun --days 14
"""
from __future__ import annotations

import argparse
import json
import math
import random
import zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import cli2ter, stats, tiers

PARIS = ZoneInfo("Europe/Paris")
HOUR, DAY = 3600, 86400
IV = {"15m": 900, "1h": 3600, "1d": 86400}


class FakeMarket:
    """Trajectoires horaires déterministes ; 15 min et 1 j dérivés des heures."""

    def __init__(self, seed=11, start_ts=0.0):
        self.rnd = random.Random(seed)
        self.paths = {}
        self.start = start_ts - 90 * DAY
        self.now = start_ts

    def _path(self, pair):
        if pair not in self.paths:
            r = random.Random(zlib.crc32(pair.encode()) % 10_000 + 17)  # déterministe d'un processus à l'autre
            p, rows = 1.0 + r.random(), []
            drift, vol = r.uniform(-0.0005, 0.0012), r.uniform(0.008, 0.03)
            t = self.start
            for _ in range(int(130 * 24)):
                o = p
                c = max(1e-6, o * (1 + r.gauss(drift, vol)))
                rows.append(dict(t=t, o=o, h=max(o, c) * (1 + abs(r.gauss(0, vol / 3))),
                                 l=min(o, c) * (1 - abs(r.gauss(0, vol / 3))), c=c, vq=r.uniform(1e5, 1e6)))
                p, t = c, t + HOUR
            self.paths[pair] = rows
        return self.paths[pair]

    def fetch(self, pair, interval, start, end):
        end = min(end, self.now)
        hourly = [r for r in self._path(pair) if r["t"] <= end]
        if interval == "1h":
            return [r for r in hourly if r["t"] > start - HOUR]
        if interval == "15m":
            out = []
            for r in hourly:
                if r["t"] <= start - HOUR:
                    continue
                for i in range(4):
                    t = r["t"] + i * 900
                    if t <= end:
                        out.append(dict(t=t, o=r["o"], h=r["h"], l=r["l"], c=r["c"], vq=r["vq"] / 4))
            return out
        days = {}
        for r in hourly:
            d0 = int(r["t"] // DAY * DAY)
            x = days.setdefault(d0, dict(t=d0, o=r["o"], h=r["h"], l=r["l"], c=r["c"], vq=0.0))
            x["h"], x["l"], x["c"] = max(x["h"], r["h"]), min(x["l"], r["l"]), r["c"]
            x["vq"] += r["vq"]
        return [v for k, v in sorted(days.items()) if k > start - DAY]


class Store:
    def __init__(self):
        self.signals, self.features, self.shadow, self.positions = [], {}, {}, []
        self.log, self.entry_filters, self.decisions = [], {}, []
        self.config = {"tier_state": {"P1": {"status": "unlocked", "risk_pct": 0.01},
                                      "P2": {"status": "shadow", "risk_pct": 0},
                                      "P3": {"status": "shadow", "risk_pct": 0},
                                      "P4": {"status": "shadow", "risk_pct": 0}},
                       "tranche_split": {"name": "50/30/20", "split": [0.5, 0.3, 0.2]},
                       "r6_readonly_until": None}
        self.locks = {}
        self.lock_events = []

    def acquire(self, name, holder, now, ttl=45 * 60):
        cur = self.locks.get(name)
        if cur and cur["expires"] > now and cur["holder"] != holder:
            self.lock_events.append(("conflict", name, holder, cur["holder"]))
            return False
        self.locks[name] = dict(holder=holder, expires=now + ttl)
        return True

    def release(self, name, holder):
        if (self.locks.get(name) or {}).get("holder") == holder:
            self.locks[name] = dict(holder=None, expires=0)

    def add_log(self, routine, now, change, rationale="", evidence=None):
        self.log.append(dict(id=len(self.log) + 1, routine=routine, created_at=datetime.fromtimestamp(now, PARIS).isoformat(),
                             change=change, rationale=rationale, evidence=evidence or {}))

    def last(self, routine):
        for row in reversed(self.log):
            if row["routine"] == routine:
                return row
        return None

    def tier_data(self):
        return dict(config=self.config, tier_versions=[dict(id=10 + i, tier=t, status="shadow") for i, t in enumerate(tiers.TIERS)],
                    signals=self.signals, features=list(self.features.values()), shadow_trades=list(self.shadow.values()),
                    tier_positions=self.positions, entry_filters=list(self.entry_filters.values()),
                    last_r5=self.last("routine5"), last_r6=self.last("routine6"))


def run(days=14, start=None, seed=11, r5_fail_day=None, verbose=False):
    start = start or datetime(2026, 9, 1, tzinfo=PARIS).timestamp()
    mk = FakeMarket(seed, start)
    db = Store()
    db.config["r6_readonly_until"] = datetime.fromtimestamp(start + 7 * DAY, PARIS).isoformat()
    rnd = random.Random(seed)
    order = []
    for day in range(days):
        d0 = datetime.fromtimestamp(start, PARIS) + timedelta(days=day)
        sched = [(4, 0, "R5", "daily"), (5, 30, "R6", "daily"), (8, 0, "R2", ""), (12, 30, "R3", ""),
                 (14, 0, "R1", ""), (14, 30, "R2", ""), (20, 0, "R2", ""), (23, 30, "R2", "daily_close")]
        if d0.weekday() == 6:
            sched += [(10, 0, "R5", "weekly"), (11, 0, "R6", "weekly")]
        for hh, mm, name, mode in sorted(sched):
            now = d0.replace(hour=hh, minute=mm).timestamp()
            mk.now = now
            if not db.acquire("tiers", name, now):
                db.add_log(name.lower(), now, dict(action="lock_busy", status="skipped"))
                continue
            try:
                if name == "R5":
                    if r5_fail_day is not None and day == r5_fail_day:
                        db.add_log("routine5", now, dict(action="data_prep", status="error"), "échec simulé")
                    else:
                        res = cli2ter.r5_compute(db.tier_data(), mk.fetch, now, weekly=(mode == "weekly"))
                        apply_r5(db, res)
                        db.add_log("routine5", now, dict(action="data_prep", status="ok", weekly=mode == "weekly"),
                                   evidence=res["log"])
                elif name == "R6":
                    res = cli2ter.r6_compute(db.tier_data(), now, mode, attempt=1)
                    if res["status"] == "wait":
                        mk.now = now + 30 * 60
                        res = cli2ter.r6_compute(db.tier_data(), now + 30 * 60, mode, attempt=2)
                    apply_r6(db, res, now)
                elif name == "R3":
                    closed = [p for p in db.positions if p["status"] == "closed"]
                    db.add_log("adaptation", now, dict(action="stats", status="ok"),
                               evidence=dict(tiers_state=db.config["tier_state"], n_closed_T=len(closed)))
                elif name == "R1":
                    r1(db, mk, now, rnd)
                elif name == "R2":
                    r2(db, mk, now)
                    db.add_log("verification", now, dict(action="check", status="ok", daily=mode == "daily_close"))
                order.append((day, f"{hh:02d}:{mm:02d}", name, mode))
            finally:
                db.release("tiers", name)
    return db, order


def apply_r5(db, res):
    for t in res["shadow"]:
        db.shadow[(t["signal_id"], t["tier"])] = dict(t, exit_reason=t["exit"])
    for f in res["features"]:
        db.features.setdefault(f["signal_id"], dict(f, outcomes=None))
    for sid, o in res["outcomes"].items():
        if sid in db.features:
            db.features[sid]["outcomes"] = o


def apply_r6(db, res, now):
    if res["status"] != "ok":
        db.add_log("routine6", now, dict(action=res["status"], status=res["status"]), res.get("why", ""))
        return
    if res["mode"] == "weekly":
        for t in res["tests"]:
            db.entry_filters[(t["tier"], t["criterion"])] = dict(tier=t["tier"], criterion=t["criterion"], status=t["status"])
        for d in res["decisions"]:
            db.decisions.append(dict(d, read_only=res["read_only"], ts=now))
        if not res["read_only"]:
            db.config["tier_state"] = res["new_state"]
    db.add_log("routine6", now, dict(action=res["log"]["action"], status="ok", read_only=res["read_only"]), evidence=res["log"])


def r1(db, mk, now, rnd):
    btc = mk.fetch("BTCUSDT", "1d", now - 80 * DAY, now)
    open_t = [dict(arm="T", pair=p["pair"], size_usd=p["size_usd"]) for p in db.positions if p["status"] == "open"]
    equity = 1000 + sum(p.get("pnl_usd") or 0 for p in db.positions if p["status"] == "closed")
    entries_today = 0
    for i in range(4):
        pair = f"SYN{rnd.randint(1, 60)}USDT"
        hourly = mk.fetch(pair, "1h", now - 2 * DAY, now)
        daily = mk.fetch(pair, "1d", now - 40 * DAY, now)
        entry = hourly[-1]["c"]
        from .indicators import atr as _atr
        atr = _atr([d for d in daily if d["t"] + DAY <= now][-30:])
        sid = len(db.signals) + 1
        decision = "enter" if i < 2 else "skip"
        db.signals.append(dict(id=sid, pair=pair, detected_at=datetime.fromtimestamp(now, PARIS).isoformat(),
                               decision=decision, price_at_detection=entry, atr14=atr, is_reference=False,
                               outcome_max_gain_pct=None, outcome_max_dd_pct=None))
        f, crit = cli2ter.snapshot(pair, now, mk.fetch, dict(last=entry, atr14=atr, news=[], alerts=[], researched=True), btc)
        db.features[sid] = dict(signal_id=sid, decision_ts=now, pair=pair, features=f, criteria=crit, outcomes=None)
        if decision == "enter":
            st = dict(config=db.config, arms={"T": dict(equity=equity, entries_today=entries_today, drawdown=0,
                                                       active_version=dict(id=10))}, open_positions=open_t)
            plan, why = cli2ter.t_entry(st, pair, entry * 1.001, atr, now)
            if plan:
                pos = tiers.new_pos(plan, now)
                pos.update(id=len(db.positions) + 1, pair=pair, status="open", signal_id=sid, last_checked=now,
                           equity_at_entry=equity)
                db.positions.append(pos)
                open_t.append(dict(arm="T", pair=pair, size_usd=plan["size_usd"]))
                entries_today += 1
    db.add_log("analyse", now, dict(action="entries", status="ok"))


def r2(db, mk, now):
    for p in [p for p in db.positions if p["status"] == "open"]:
        rows = mk.fetch(p["pair"], "15m", max(p["opened_ts"], p["last_checked"]) - 900, now)
        rows = [r for r in rows if r["t"] >= p["opened_ts"] - 1]
        tiers.step_tranches(p, rows, 0.001, 900)
        res = tiers.settle(p, last_price=rows[-1]["c"] if rows else None, now_ts=now)
        p["last_checked"] = now
        if all(d["status"] != "open" for d in p["tranches"].values()):
            p.update(status="closed", pnl_usd=res["pnl_usd"], r_multiple=res["r_multiple"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args(argv)
    db, order = run(a.days)
    by = {}
    for row in db.log:
        by[row["routine"]] = by.get(row["routine"], 0) + 1
    print(json.dumps(dict(steps=len(order), log_rows=by, lock_conflicts=len(db.lock_events),
                          signals=len(db.signals), positions_T=len(db.positions),
                          closed_T=sum(1 for p in db.positions if p["status"] == "closed"),
                          shadow_trades=len(db.shadow), decisions=len(db.decisions)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
