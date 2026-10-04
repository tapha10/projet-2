"""Cycle sec de 14 jours de la routine 7 (sans réseau, sans base) : 04:00 R5, 05:30 R6, 05:45 R7,
14:00 R1 (signaux), 14:20 R7, vérifications R2 08:00/14:30/20:00/23:30, dimanche 11:30 R7.

Les actions de cli7 sont appliquées à un magasin en mémoire qui recopie les garde-fous de la base
(GUARDRAILS section 10) et la clôture des étapes (trigger chain_on_position_close) : toute action
qui violerait un garde-fou est comptée comme violation (attendu : 0).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import chains as C
from . import cli7, simulate

PARIS = ZoneInfo("Europe/Paris")
DAY = 86400


def iso(t):
    return datetime.fromtimestamp(t, PARIS).isoformat()


class Market:
    """Prix synthétiques par pair : marche aléatoire horaire, déterministe."""

    def __init__(self, seed):
        self.seed = seed
        self.cache = {}

    def hourly(self, pair, start, end):
        if pair not in self.cache:
            r = random.Random(f"{self.seed}:{pair}")
            t0 = int(start // 3600 * 3600) - 40 * DAY
            p, rows = 1.0, []
            drift = r.uniform(-0.0005, 0.0012)
            for i in range(24 * 120):
                o = p
                c = max(1e-6, o * (1 + r.gauss(drift, 0.012)))
                rows.append(dict(t=t0 + i * 3600, o=o, h=max(o, c) * (1 + abs(r.gauss(0, 0.006))),
                                 l=min(o, c) * (1 - abs(r.gauss(0, 0.006))), c=c, vq=1e6))
                p = c
            self.cache[pair] = rows
        return [x for x in self.cache[pair] if start <= x["t"] <= end]

    def fetch(self, pair, iv, a, b):
        if iv == "1h":
            return self.hourly(pair, a, b)
        rows = self.hourly(pair, a - DAY, b)
        out = {}
        for x in rows:
            d = int(x["t"] // DAY * DAY)
            k = out.setdefault(d, dict(t=d, o=x["o"], h=x["h"], l=x["l"], c=x["c"], vq=0))
            k["h"], k["l"], k["c"], k["vq"] = max(k["h"], x["h"]), min(k["l"], x["l"]), x["c"], k["vq"] + x["vq"]
        return [out[d] for d in sorted(out) if d + DAY <= b]

    def last(self, pair, now):
        rows = self.hourly(pair, now - 3 * 3600, now)
        return rows[-1]["c"] if rows else None


class Store:
    def __init__(self, data):
        self.d = data
        self.positions = []
        self.violations = []
        self.next_id = dict(chain=1, step=1, pos=1, dec=1)
        self.k_realized = 0.0

    def view(self, now):
        d = dict(self.d)
        d["open_k"] = [p for p in self.positions if p["status"] == "open"]
        d["k_equity"] = 1000.0 + self.k_realized
        d["config"] = dict(d["config"])
        return d

    def apply(self, acts, now):
        for a in acts:
            k = a["kind"]
            if k == "decision":
                self.d["decisions"].append(dict(a, created_at=iso(now)))
            elif k == "log":
                self.d["routine_log"].append(dict(routine="routine7", change=dict(status=a["status"]), created_at=iso(now)))
            elif k == "sim_run":
                self.d["sim_runs"].append(dict(source=a["source"], variant=a["variant"], params_id=a["params_id"],
                                               detail=a.get("s") or a.get("mc") or {}))
            elif k == "stats":
                self.d["stats"].append(dict(variant=a["variant"], source=a["source"], p_full=a["p_full"]))
            elif k == "gating_change":
                for g in self.d["gating"]:
                    if g["params_id"] == a["params_id"] and g["k"] == a["level"]:
                        g["min_score"] = a["new"]
            elif k == "open_step":
                if a.get("read_only"):
                    self.d["decisions"].append(dict(a, action="entrer", created_at=iso(now)))
                    continue
                self.open_step(a, now)

    # -- recopie des garde-fous de la base (section 10)
    def open_step(self, a, now):
        eq = 1000.0 + self.k_realized
        if a.get("new_chain"):
            n_open = sum(1 for c in self.d["chains"] if c["state"] == "ouverte")
            if n_open >= 3:
                self.violations.append("4e chaîne ouverte")
                return
            c = dict(id=self.next_id["chain"], params_id=a["params_id"], source="live_paper", state="ouverte",
                     level=0, gate_level=0, house=0.0, gains=0.0, bank=0.0, started_at=iso(now))
            self.next_id["chain"] += 1
            self.d["chains"].append(c)
        else:
            c = next(x for x in self.d["chains"] if x["id"] == a["chain_id"])
        sd = (a["entry"] - a["stop"]) / a["entry"]
        risk = a["size"] * sd
        if sd > 0.15 + 1e-9:
            self.violations.append("stop > 15 %")
        if a["k"] == 1 and risk > 0.01 * eq * 1.0001:
            self.violations.append(f"étape 1 risque {risk:.2f} > 1 %")
        if a["k"] > 1:
            prev = next((s for s in self.d["steps"] if s["chain_id"] == c["id"] and s["k"] == a["k"] - 1), None)
            if not prev or prev.get("outcome") != "victoire" or risk > (prev.get("pnl") or 0) * 1.0001:
                self.violations.append(f"étape {a['k']} risque {risk:.2f} > gain précédent")
        if a["size"] / eq > 3 + 1e-9 or a["leverage"] > 3:
            self.violations.append("levier > 3x")
        if a.get("vol_24h") and a["size"] > 0.001 * a["vol_24h"] * 1.0001:
            self.violations.append("liquidité")
        if any(p["status"] == "open" and (p["chain_id"] == c["id"] or p["pair"] == a["pair"]) for p in self.positions):
            self.violations.append("2e position (chaîne ou pair)")
        st = dict(id=self.next_id["step"], chain_id=c["id"], k=a["k"], signal_id=a["signal_id"], pair=a["pair"],
                  outcome="ouverte", risk=risk)
        self.next_id["step"] += 1
        self.d["steps"].append(st)
        pos = dict(id=self.next_id["pos"], arm="K", pair=a["pair"], chain_id=c["id"], chain_step=a["k"],
                   entry_price=a["entry"], stop_price=a["stop"], tp_price=a["target"], size_usd=a["size"],
                   leverage=a["leverage"], opened_ts=now, status="open", initial_stop_price=a["stop"],
                   max_hold_until=iso(now + 10 * DAY), opened_at=iso(now))
        self.next_id["pos"] += 1
        self.positions.append(pos)
        self.d["decisions"].append(dict(action="entrer", chain_id=c["id"], created_at=iso(now)))

    # -- routine 2 (moteur existant) + trigger de clôture
    def check(self, mk, now):
        for p in [p for p in self.positions if p["status"] == "open"]:
            ps = simulate.PosState(entry=p["entry_price"], size_usd=p["size_usd"], leverage=p["leverage"],
                                   stop=p["stop_price"], initial_stop=p["stop_price"], tp=p["tp_price"],
                                   opened_ts=p["opened_ts"], max_hold_ts=p["opened_ts"] + 10 * DAY)
            ps.through = p.get("through")
            rows = mk.hourly(p["pair"], (ps.through or ps.opened_ts) - 3600, now)
            res = simulate.step(ps, rows, 0.001, 3600, now=now)
            p["through"] = ps.through
            if not res:
                continue
            r = simulate.pnl(ps, res["exit_price"], res["exit_ts"], res["exit_reason"], 0.00055, 0.0001)
            p.update(status="closed", exit_reason=res["exit_reason"], pnl_usd=r["pnl_usd"], closed_ts=res["exit_ts"])
            self.k_realized += r["pnl_usd"]
            self.close_step(p)

    def close_step(self, p):
        c = next(x for x in self.d["chains"] if x["id"] == p["chain_id"])
        st = next(s for s in self.d["steps"] if s["chain_id"] == c["id"] and s["k"] == p["chain_step"])
        win = p["exit_reason"] == "tp"
        st.update(outcome="victoire" if win else "perte", pnl=p["pnl_usd"], closed_at=iso(p["closed_ts"]))
        c["gains"] += p["pnl_usd"]
        if win:
            c["level"], c["gate_level"], c["house"] = p["chain_step"], c["gate_level"] + 1, p["pnl_usd"]
            if c["level"] >= 5:
                c.update(state="réussie", bank=c["gains"], house=0.0)
        else:
            c.update(state="échouée", bank=c["gains"], house=0.0)


def _base_data(now):
    params, gating = [], []
    for i, v in enumerate(C.default_variants(), 1):
        params.append(dict(id=i, name=v["name"], params=v, status="champion" if i == 1 else "ombre"))
        for k, g in enumerate(v["gating"], 1):
            gating.append(dict(params_id=i, k=k, min_score=g))
    return dict(config=dict(chain_readonly_until=iso(now + 7 * DAY), slippage_pct=0.001), params=params,
                gating=gating, chains=[], steps=[], signals=[], entry_filters=[], sim_runs=[], stats=[],
                decisions=[], routine_log=[], global_drawdown=0.0)


def cycle(days=14, seed=21, start=None, r6_fail_day=3, crash_day=10, hist_events=None):
    start = start or datetime(2026, 9, 7, tzinfo=PARIS).timestamp()
    mk = Market(seed)
    rnd = random.Random(seed)
    st = Store(_base_data(start))
    order, sig_id = [], [1]
    for day in range(days):
        d0 = datetime.fromtimestamp(start, PARIS) + timedelta(days=day)
        sched = [(4, 0, "R5"), (5, 30, "R6"), (5, 45, "R7d"), (8, 0, "R2"), (14, 0, "R1"), (14, 20, "R7e"),
                 (14, 30, "R2"), (20, 0, "R2"), (23, 30, "R2")]
        if d0.weekday() == 6:
            sched += [(11, 30, "R7w")]
        for hh, mm, name in sorted(sched):
            now = d0.replace(hour=hh, minute=mm).timestamp()
            if name == "R5":
                st.d["routine_log"].append(dict(routine="routine5", change=dict(status="ok"), created_at=iso(now)))
            elif name == "R6":
                if day != r6_fail_day:                     # jour où la routine 6 n'a pas fini
                    st.d["routine_log"].append(dict(routine="routine6", change=dict(status="ok"), created_at=iso(now)))
            elif name == "R7d":
                acts = cli7.daily(st.view(now), mk.fetch, now, attempt=1)
                if acts and acts[0]["kind"] == "wait":
                    order.append((day, "05:45", "R7 attend", acts[0]["logic"]))
                    later = now + 30 * 60
                    acts = cli7.daily(st.view(later), mk.fetch, later, attempt=2)
                st.apply(acts, now)
                order.append((day, "05:45", "R7", acts[0]["kind"] + ("/" + acts[0].get("action", "") if acts else "")))
            elif name == "R1":
                for _ in range(rnd.choice([0, 1, 1, 2, 3])):
                    pair = f"P{rnd.randint(1, 40)}USDT"
                    px = mk.last(pair, now)
                    st.d["signals"].append(dict(id=sig_id[0], pair=pair, detected_at=iso(now), decision="enter",
                                                score=rnd.choice([2.5, 3, 3.5, 4, 4.5, 5, 6]), price_at_detection=px,
                                                quote_vol_24h=5e7, criteria={}, is_reference=False))
                    sig_id[0] += 1
            elif name == "R7e":
                acts = cli7.decide(st.view(now), lambda pair: mk.last(pair, now), now)
                if day == crash_day:                         # coupure : rien n'est appliqué, la routine repart
                    order.append((day, "14:20", "R7", f"coupure simulée ({len(acts)} actions perdues)"))
                    acts = cli7.decide(st.view(now), lambda pair: mk.last(pair, now), now)
                st.apply(acts, now)
                acts2 = cli7.decide(st.view(now), lambda pair: mk.last(pair, now), now)   # relance immédiate
                dup = [a for a in acts2 if a["kind"] == "open_step" and not a.get("read_only") and not a.get("new_chain")]
                if dup:
                    st.violations.append(f"relance : {len(dup)} doublon(s)")
                order.append((day, "14:20", "R7", f"{sum(1 for a in acts if a['kind'] == 'open_step')} entrée(s)"))
            elif name == "R2":
                st.check(mk, now)
            elif name == "R7w":
                acts = cli7.weekly(st.view(now), dict(events=hist_events or []), now, [])
                st.apply(acts, now)
                order.append((day, "11:30", "R7 dimanche", acts[-1].get("rationale", "")[:80]))
    return st, order
