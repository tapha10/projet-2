"""Portefeuille « S » : stratégie INVERSE (short), DÉMO uniquement (GUARDRAILS section 11).

Pour chaque signal entré dans les bras A, B, C ou T, un short virtuel est ouvert au même moment et
au même prix (glissement forfaitaire en moins), puis rejoué bougie par bougie (15 min, affiné à
1 min quand stop et objectif sont dans la même bougie ; si l'ordre reste inconnu, le stop compte
d'abord). Aucune position réelle, aucun exchange authentifié, la table `positions` n'est jamais
touchée. Commandes :
    python3 -m engine.inverse run    --state inv_state.json --out inv.sql
    python3 -m engine.inverse report --state inv_state.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import market, simulate
from .sqlgen import load_json_loose, q, qts
from .stats import parse_ts

PARIS = ZoneInfo("Europe/Paris")
DEFAULTS = dict(stop_pct=0.30, tp_pct=0.10, hold_days=7, leverage=2.0, risk_pct=0.01,
                tp_trail_pct=None, max_open=8, max_per_day=3, drawdown_halt=0.15, capital=1000.0)
FEE = 0.00055      # par côté (Bybit), comme les autres bras
SLIP = 0.001       # glissement forfaitaire par exécution


def params_of(state):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (state.get("params") or {}).items() if k in DEFAULTS})
    p["leverage"] = min(float(p["leverage"]), 2.0)          # plafond de la section 11
    p["risk_pct"] = min(float(p["risk_pct"]), 0.01)
    p["max_open"] = min(int(p["max_open"]), 8)
    p["max_per_day"] = min(int(p["max_per_day"]), 3)
    return p


def paris_day(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(PARIS).date()


class Short:
    """Position inverse en cours de simulation (prix en unités de la paire)."""

    def __init__(self, row):
        self.id = row.get("id")
        self.signal_id = row["signal_id"]
        self.pair = row["pair"]
        self.entry = float(row["entry_price"])
        self.size = float(row["size_usd"])
        self.lev = float(row["leverage"])
        self.stop = float(row["stop_price"])
        self.initial_stop = float(row["initial_stop_price"])
        self.tp = float(row["tp_price"])
        self.trailing = bool(row.get("trailing_active"))
        self.opened = parse_ts(row["opened_at"])
        self.hold = parse_ts(row["max_hold_until"])
        self.low = float(row.get("lowest_price") or self.entry)
        self.high = float(row.get("highest_price") or self.entry)
        self.through = parse_ts(row.get("sim_through_at"))
        self.trail_pct = None
        self.audit = []


def _eventful(s):
    return lambda k: k["h"] >= s.stop or k["l"] <= s.tp or (s.trailing and k["l"] < s.low)


def _advance(s, slip):
    def adv(k, cs, fine):
        o, h, l, c = k["o"], k["h"], k["l"], k["c"]
        end_ts = k["t"] + cs
        # côté hausse d'abord (hypothèse prudente pour un short si l'ordre reste inconnu)
        if h >= s.stop:
            s.high = max(s.high, h)
            fill = max(s.stop, o) * (1 + slip)          # gap au-dessus du stop : exécution à l'ouverture
            return dict(exit_price=fill, exit_reason="trailing" if s.trailing else "sl", exit_ts=k["t"])
        s.high = max(s.high, h)
        s.low = min(s.low, l)
        if not s.trailing and l <= s.tp:
            if s.trail_pct:                              # TP « augmenté » : on laisse courir avec un stop suiveur
                s.trailing = True
            else:
                return dict(exit_price=s.tp * (1 + slip), exit_reason="tp", exit_ts=k["t"])
        if s.trailing:
            new_stop = s.low * (1 + (s.trail_pct or 0.05))
            if new_stop < s.stop:
                s.stop = new_stop
        if end_ts >= s.hold:
            return dict(exit_price=c * (1 + slip), exit_reason="time", exit_ts=end_ts)
        return None
    return adv


def simulate_short(s, candles, now, refine, slip=SLIP):
    res, s.through = simulate.walk(candles, 900, now, refine, s.opened, s.through,
                                   _eventful(s), _advance(s, slip), s.audit)
    return res


def settle(s, res, funding_rates=None):
    qty = s.size / s.entry
    gross = qty * (s.entry - res["exit_price"])
    fees = FEE * (s.size + qty * res["exit_price"])
    funding = 0.0
    if funding_rates:   # un short REÇOIT le funding quand le taux est positif
        funding = sum(s.size * r for t, r in funding_rates if s.opened < t <= res["exit_ts"])
    net = gross - fees + funding
    risk = s.size * (s.initial_stop - s.entry) / s.entry
    return dict(pnl_usd=round(net, 4), pnl_pct=round(1 - res["exit_price"] / s.entry, 6),
                r_multiple=round(net / risk, 4) if risk > 0 else None,
                fees_usd=round(fees, 4), funding_usd=round(funding, 4),
                mfe_pct=round(1 - s.low / s.entry, 6), mae_pct=round(-(s.high / s.entry - 1), 6))


def _rows(pair, start, now, srcs=market.DEFAULT_SOURCES):
    rows, _ = market.candles(pair, "15m", start - 900, now, srcs)
    return rows


def _refine(pair):
    return lambda t0, t1: market.fine_candles(pair, t0, t1)[0]


def _funding(pair, start, end):
    try:
        return market.funding_history(pair, start, end)[0]
    except Exception:
        return None


def equity_at(rows, t, capital):
    return capital + sum(float(r["pnl_usd"]) for r in rows
                         if r.get("status") == "closed" and r.get("closed_at") and parse_ts(r["closed_at"]) <= t)


def can_open(rows, t, pair, p):
    """Plafonds de la section 11 à l'instant t (rejeu de l'historique compris)."""
    open_now = [r for r in rows if parse_ts(r["opened_at"]) <= t
                and (r.get("status") == "open" or not r.get("closed_at") or parse_ts(r["closed_at"]) > t)]
    if len(open_now) >= p["max_open"]:
        return "8 positions ouvertes"
    if any(r["pair"] == pair for r in open_now):
        return "même pair déjà ouvert"
    day = paris_day(t)
    if sum(1 for r in rows if paris_day(parse_ts(r["opened_at"])) == day) >= p["max_per_day"]:
        return "3 entrées par jour"
    # drawdown réalisé depuis le plus haut
    eq = peak = p["capital"]
    for r in sorted((r for r in rows if r.get("closed_at") and parse_ts(r["closed_at"]) <= t),
                    key=lambda r: parse_ts(r["closed_at"])):
        eq += float(r["pnl_usd"]); peak = max(peak, eq)
    if peak > 0 and 1 - eq / peak > p["drawdown_halt"]:
        return "drawdown > 15 %"
    return None


def new_row(src, rows, p):
    t = parse_ts(src["opened_at"])
    entry = float(src["entry_price"]) * (1 - SLIP) / (1 + SLIP)      # prix de signal, vendu avec glissement
    stop = entry * (1 + p["stop_pct"]); tp = entry * (1 - p["tp_pct"])
    eq = equity_at(rows, t, p["capital"])
    size = min(eq * p["risk_pct"] / p["stop_pct"], eq * 0.5)
    return dict(signal_id=src["signal_id"], source_position_ids=src.get("position_ids") or [],
                pair=src["pair"], opened_at=datetime.fromtimestamp(t, tz=timezone.utc).isoformat(),
                entry_price=entry, size_usd=round(size, 4), leverage=p["leverage"],
                stop_price=stop, initial_stop_price=stop, tp_price=tp, trailing_active=False,
                max_hold_until=datetime.fromtimestamp(t + p["hold_days"] * 86400, tz=timezone.utc).isoformat(),
                status="open", lowest_price=entry, highest_price=entry)


def apply_sim(row, p, now, candles=None, refine=None, funding=None):
    """Simule une ligne (dict) jusqu'à `now`; met la ligne à jour; renvoie True si fermée."""
    s = Short(row)
    s.trail_pct = p.get("tp_trail_pct")
    candles = candles if candles is not None else _rows(s.pair, s.through or s.opened, now)
    res = simulate_short(s, candles, now, refine or _refine(s.pair))
    row.update(stop_price=s.stop, trailing_active=s.trailing, lowest_price=s.low, highest_price=s.high,
               sim_through_at=datetime.fromtimestamp(s.through or s.opened, tz=timezone.utc).isoformat(),
               last_checked_at=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
               mfe_pct=round(1 - s.low / s.entry, 6), mae_pct=round(-(s.high / s.entry - 1), 6))
    if res:
        rates = funding if funding is not None else _funding(s.pair, s.opened, res["exit_ts"])
        row.update(status="closed", closed_at=datetime.fromtimestamp(res["exit_ts"], tz=timezone.utc).isoformat(),
                   exit_price=res["exit_price"], exit_reason=res["exit_reason"], **settle(s, res, rates))
    return bool(res)


def run(state, now=None):
    now = now or time.time()
    p = params_of(state)
    rows = [dict(r) for r in state.get("inverse") or []]
    known = {r["signal_id"] for r in rows}
    log = dict(updated=0, closed=0, opened=0, skipped=[], errors=[])
    updates, inserts = [], []
    for r in rows:
        if r["status"] == "open":
            try:
                if apply_sim(r, p, now):
                    log["closed"] += 1
                log["updated"] += 1
                updates.append(r)
            except Exception as e:
                log["errors"].append(f"{r['pair']}: {e}")
    for src in sorted(state.get("sources") or [], key=lambda x: parse_ts(x["opened_at"])):
        if src["signal_id"] in known:
            continue
        t = parse_ts(src["opened_at"])
        why = can_open(rows, t, src["pair"], p)
        if why:
            log["skipped"].append(f"{src['pair']} (signal {src['signal_id']}): {why}")
            continue
        r = new_row(src, rows, p)
        try:
            if apply_sim(r, p, now):
                log["closed"] += 1
        except Exception as e:
            log["errors"].append(f"{r['pair']}: {e}")
            continue
        rows.append(r); inserts.append(r); known.add(src["signal_id"]); log["opened"] += 1
    return rows, inserts, updates, log


_COLS = ("signal_id", "source_position_ids", "pair", "opened_at", "entry_price", "size_usd", "leverage",
         "stop_price", "initial_stop_price", "tp_price", "trailing_active", "max_hold_until", "status",
         "closed_at", "exit_price", "exit_reason", "pnl_usd", "pnl_pct", "r_multiple", "fees_usd",
         "funding_usd", "mfe_pct", "mae_pct", "lowest_price", "highest_price", "sim_through_at",
         "last_checked_at")
_TS = {"opened_at", "max_hold_until", "closed_at", "sim_through_at", "last_checked_at"}


def _v(col, v):
    if col in _TS:
        return qts(v)
    if col == "source_position_ids":
        return "array[" + ",".join(str(int(i)) for i in v) + "]::bigint[]" if v else "'{}'::bigint[]"
    return q(v)


def to_sql(inserts, updates, log):
    L = ["begin;"]
    for r in inserts:
        L.append("insert into inverse_positions(" + ",".join(_COLS) + ") values ("
                 + ",".join(_v(c, r.get(c)) for c in _COLS) + ") on conflict (signal_id) do nothing;")
    upd = ("stop_price", "trailing_active", "status", "closed_at", "exit_price", "exit_reason", "pnl_usd",
           "pnl_pct", "r_multiple", "fees_usd", "funding_usd", "mfe_pct", "mae_pct", "lowest_price",
           "highest_price", "sim_through_at", "last_checked_at")
    for r in updates:
        L.append("update inverse_positions set " + ", ".join(f"{c}={_v(c, r.get(c))}" for c in upd)
                 + f" where id={int(r['id'])} and status='open';")
    L.append("insert into iteration_log(routine, change, rationale) values ('inverse', "
             + q({"action": "inverse_run", "opened": log["opened"], "closed": log["closed"],
                  "updated": log["updated"], "skipped": log["skipped"][:10], "errors": log["errors"][:5]})
             + ", " + q("Portefeuille S (stratégie inverse, démo) : %d ouverte(s), %d fermée(s), %d suivie(s)"
                        % (log["opened"], log["closed"], log["updated"])) + ");")
    L.append("commit;")
    return "\n".join(L) + "\n"


def report_lines(rows, prices=None):
    """Résumé du portefeuille S (réalisé, latent, gagnants/perdants) pour le rapport."""
    prices = prices or {}
    cl = [r for r in rows if r["status"] == "closed"]
    op = [r for r in rows if r["status"] == "open"]
    real = sum(float(r["pnl_usd"]) for r in cl)
    wins = [r for r in cl if float(r["pnl_usd"]) > 0.005]
    loss = [r for r in cl if float(r["pnl_usd"]) < -0.005]
    lat = 0.0
    for r in op:
        px = prices.get(r["pair"])
        if px:
            qty = float(r["size_usd"]) / float(r["entry_price"])
            lat += qty * (float(r["entry_price"]) - px)
    L = ["### Portefeuille S — stratégie inverse (short, démo)", "",
         f"- Ouvertes : {len(op)} · fermées : {len(cl)} ({len(wins)} gagnantes, {len(loss)} perdantes)",
         f"- Réalisé : {real:+.2f} $ · latent : {lat:+.2f} $ · capital estimé : {1000 + real + lat:.2f} $", ""]
    for r in sorted(cl, key=lambda r: -float(r["pnl_usd"])):
        L.append(f"- {r['pair'].replace('USDT', '')} : {float(r['pnl_usd']):+.2f} $ ({r['exit_reason']})")
    return L


def main(argv=None):
    ap = argparse.ArgumentParser(prog="engine.inverse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run"); a.add_argument("--state", required=True); a.add_argument("--out", required=True)
    b = sub.add_parser("report"); b.add_argument("--state", required=True)
    args = ap.parse_args(argv)
    state = load_json_loose(args.state)
    if args.cmd == "run":
        rows, ins, upd, log = run(state)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(to_sql(ins, upd, log))
        print(f"Portefeuille S (démo) : {log['opened']} ouverte(s), {log['closed']} fermée(s), "
              f"{log['updated']} suivie(s), {len(log['skipped'])} refusée(s), {len(log['errors'])} erreur(s)")
        for s in log["skipped"]:
            print("  refusée :", s)
        for e in log["errors"]:
            print("  erreur :", e)
        print("\n".join(report_lines(rows)))
    else:
        print("\n".join(report_lines(state.get("inverse") or [])))


if __name__ == "__main__":
    main()
