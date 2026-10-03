"""Interface des routines. DÉMO UNIQUEMENT : ce programme ne fait que lire des
données publiques et produire du SQL pour la base de démo. Il ne contient
aucun client d'exchange authentifié et ne peut passer aucun ordre réel.

Usage (depuis crypto_paper_trading/) :
  python -m engine.cli scan     --state state.json --out candidates.json
  python -m engine.cli decide   --state state.json --candidates candidates.json --out entries.sql
  python -m engine.cli check    --state state.json --out check.sql [--daily]
  python -m engine.cli outcomes --history history.json --out outcomes.sql
  python -m engine.cli adapt    --history history.json --out adapt.sql
  python -m engine.cli report   --history history.json --calendar calendar.md --out report.md --sql report.sql
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from . import indicators, market, risk, simulate, stats
from .sqlgen import load_json_loose, q, qarr, qts

ARMS = ("A", "B", "C")
DAY = 86400


def now_ts():
    return time.time()


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def cfgv(cfg, key, default=None):
    v = cfg.get(key, default)
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# =================================================================== SCAN
def market_profile(pair, ticker=None, sources=market.DEFAULT_SOURCES):
    """Mesures de marché d'un pair à partir des bougies journalières (40 j)."""
    now = now_ts()
    daily, src = market.candles(pair, "1d", now - 40 * DAY, now, sources)
    complete = [d for d in daily if d["t"] + DAY <= now]
    last = ticker["last"] if ticker else daily[-1]["c"]
    qv = ticker["quote_vol_24h"] if ticker else None
    closes = [d["c"] for d in complete] + [last]
    hi20 = max((d["h"] for d in complete[-20:]), default=None)
    prof = dict(
        pair=pair, last=last, data_source=src,
        change_24h=ticker["change_24h"] if ticker else (last / complete[-1]["c"] - 1 if complete else None),
        quote_vol_24h=qv,
        vol_ratio=indicators.volume_ratio(complete + [dict(vq=qv)] if qv else daily, qv),
        vol_doubling=indicators.volume_doubling(complete[-3:] + ([dict(vq=qv)] if qv else [])),
        rsi14=indicators.rsi(closes),
        atr14=indicators.atr(complete[-30:]),
        breakout_20d=bool(hi20 and last > hi20),
        n_daily=len(complete),
    )
    # Bougie du signal = plus forte variation journalière (ouverture -> clôture) parmi
    # la veille complète et le jour en cours, ou la variation 24 h glissante.
    cands = [(prof["change_24h"] or 0, None)]
    if complete:
        cands.append((complete[-1]["c"] / complete[-1]["o"] - 1, complete[-1]["t"]))
    cur = [d for d in daily if d["t"] + DAY > now]
    if cur:
        cands.append((last / cur[-1]["o"] - 1, cur[-1]["t"]))
    big = max(cands, key=lambda x: x[0])
    prof["signal_candle_change"] = big[0]
    prof["signal_day_ts"] = big[1] if big[1] is not None else (cur[-1]["t"] if cur else None)
    # pic déjà passé : +50 % sur 10 j puis rendu plus de 25 % depuis le plus haut
    w = complete[-10:]
    if w:
        hi = max(d["h"] for d in w)
        lo = min(d["l"] for d in w)
        prof["peak_passed"] = bool(hi >= 1.5 * lo and last <= 0.75 * hi)
        prof["high_10d"] = hi
    try:
        oi, _ = market.open_interest_usd(pair, days=5)
        if len(oi) >= 4 and oi[-4][1] > 0:
            prof["oi_change_3d"] = oi[-1][1] / oi[-4][1] - 1
    except Exception as e:
        prof["oi_error"] = str(e)[:120]
    return prof


def market_signal_types(p, listed):
    types, alerts = [], []
    if p.get("vol_doubling"):
        types.append("volume_doubling")
    if (p.get("oi_change_3d") or 0) >= 0.20:
        types.append("oi_rising")
    if (p.get("rsi14") or 50) < 30 or p.get("breakout_20d"):
        types.append("oversold_or_breakout")
    if (p.get("change_24h") or 0) >= 0.10:
        types.append("top_gainer_24h")
    if p["pair"] in listed:
        types.append("listing_or_perp")
    if p.get("peak_passed"):
        alerts.append("alert_peak_passed")
    return types, alerts


def cmd_scan(a):
    st = load_json_loose(a.state)
    cfg = st["config"]
    rules = cfgv(cfg, "entry_rules", {})
    sources = tuple(cfgv(cfg, "data_sources", list(market.DEFAULT_SOURCES)))
    tick, tsrc = market.tickers()
    try:
        contracts = market.crypto_contracts()
        tick = [t for t in tick if t["pair"] in contracts]  # crypto uniquement
        listed_rows, _ = market.new_listings(7, contracts)
        listed = {r["pair"]: r["launched_at"] for r in listed_rows}
    except Exception:
        listed = {}
    by_pair = {t["pair"]: t for t in tick}
    recent = {s["pair"] for s in st.get("recent_signals", [])
              if stats.parse_ts(s["detected_at"]) > now_ts() - 3 * DAY}
    open_pairs = {p["pair"] for p in st.get("open_positions", [])}
    waiting = {w["pair"] for w in st.get("pending_waits", [])}
    liquid = [t for t in tick if t["quote_vol_24h"] >= float(rules.get("min_quote_volume_24h", 2e6))
              and t["pair"] not in ("BTCUSDT", "ETHUSDT")]
    gainers = sorted(liquid, key=lambda t: -t["change_24h"])[:25]
    fresh = [by_pair[p] for p in listed if p in by_pair
             and by_pair[p]["quote_vol_24h"] >= float(rules.get("min_quote_volume_24h", 2e6)) / 4]
    pool, seen = [], set()
    for t in gainers + fresh:
        if t["pair"] in seen or t["pair"] in recent or t["pair"] in open_pairs or t["pair"] in waiting:
            continue
        seen.add(t["pair"])
        pool.append(t)
    cands, errors = [], []
    for t in pool:
        try:
            p = market_profile(t["pair"], t, sources)
        except Exception as e:
            errors.append(f"{t['pair']}: {e}"[:200])
            continue
        types, alerts = market_signal_types(p, listed)
        if not types:
            continue
        p.update(market_signal_types=types, market_alerts=alerts,
                 listed_at=iso(listed[t["pair"]]) if t["pair"] in listed else None,
                 news=[], alerts=[], unlock_supply_pct_7d=None, notes="")
        cands.append(p)
    w = {k: float(v) for k, v in cfgv(cfg, "signal_weights", {}).items() if k != "version"}
    cands.sort(key=lambda c: -sum(w.get(x, 0) for x in c["market_signal_types"] + c["market_alerts"]))
    cands = cands[: int(rules.get("max_candidates_per_scan", 15))]

    waits = []
    for s in st.get("pending_waits", []):
        m = s.get("metrics") or {}
        root_ts = stats.parse_ts(m.get("root_detected_at") or s["detected_at"])
        age_days = (now_ts() - root_ts) / DAY
        item = dict(signal_id=s["id"], pair=s["pair"], age_days=round(age_days, 2),
                    root_detected_at=iso(root_ts), news=[], alerts=[], unlock_supply_pct_7d=None)
        try:
            daily, src = market.candles(s["pair"], "1d", root_ts - 20 * DAY, now_ts(), sources)
            day0 = int(m.get("signal_day_ts") or (root_ts // DAY * DAY))
            before = [d for d in daily if d["t"] < day0][-14:]
            sig_day = next((d for d in daily if d["t"] == day0), None)
            tk = by_pair.get(s["pair"])
            last = tk["last"] if tk else daily[-1]["c"]
            qv = tk["quote_vol_24h"] if tk else daily[-1]["vq"]
            avg14 = sum(d["vq"] for d in before) / len(before) if before else None
            sdc = s.get("signal_day_close") or (sig_day["c"] if sig_day and sig_day["t"] + DAY <= now_ts() else None)
            item.update(last=last, data_source=src, signal_day_close=sdc,
                        vol_ratio_vs_pre_signal=(qv / avg14) if avg14 else None,
                        drop_from_signal_close=(last / sdc - 1) if sdc else None,
                        change_24h=tk["change_24h"] if tk else None,
                        atr14=indicators.atr([d for d in daily if d["t"] + DAY <= now_ts()][-30:]),
                        parent=s)
        except Exception as e:
            item["error"] = str(e)[:200]
        waits.append(item)

    out = dict(generated_at=iso(now_ts()), tickers_source=tsrc, candidates=cands,
               waits=waits, errors=errors,
               instructions=("Complète news[] ({type, url, titre, date_publication}), alerts[] "
                             "(alert_team_transfer, alert_unlock_7d) et unlock_supply_pct_7d pour "
                             "chaque candidat et chaque wait, puis lance `decide`."))
    write(a.out, json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(f"{len(cands)} candidats, {len(waits)} wait à réévaluer, source tickers={tsrc}, "
          f"{len(errors)} erreurs -> {a.out}")


# ================================================================= DECIDE
NEWS_TYPES = {"dated_announcement", "listing_or_perp", "revenue_or_buyback"}


def score_of(types, alerts, weights):
    return round(sum(float(weights.get(t, 0)) for t in set(types) | set(alerts)), 3)


def arm_capacity(st):
    """Places disponibles par bras aujourd'hui, compte tenu de tous les plafonds."""
    cfg = st["config"]
    hl = risk.HARD
    cap = {}
    for arm in ARMS:
        info = st["arms"][arm]
        max_open = min(int(cfgv(cfg, "max_open_positions_per_arm", 8)), hl["max_open_per_arm"])
        max_day = min(int(cfgv(cfg, "max_new_entries_per_day_per_arm", 3)), hl["max_entries_per_day_per_arm"])
        dd_halt = min(float(cfgv(cfg, "drawdown_halt_pct", 0.15)), hl["drawdown_halt"])
        dd = float(info.get("drawdown") or 0)
        if dd > dd_halt:
            cap[arm] = (0, f"bras {arm} suspendu : drawdown {dd:.1%} > {dd_halt:.0%}")
            continue
        n = min(max_open - int(info["n_open"]), max_day - int(info["entries_today"]))
        cap[arm] = (max(0, n), None if n > 0 else f"bras {arm} : plafond de positions/entrées atteint")
    return cap


def decide_candidate(c, rules, weights):
    news_types = [n.get("type") for n in c.get("news", []) if n.get("type") in NEWS_TYPES]
    types = sorted(set(c.get("market_signal_types", []) + news_types))
    alerts = sorted(set(c.get("market_alerts", []) + c.get("alerts", [])))
    unlock = c.get("unlock_supply_pct_7d")
    if unlock is not None and float(unlock) > float(rules.get("unlock_max_supply_pct", 0.005)):
        alerts = sorted(set(alerts) | {"alert_unlock_7d"})
    sc = score_of(types, alerts, weights)
    if "alert_team_transfer" in alerts:
        return types, alerts, sc, "skip", "alerte : transferts de l'équipe / market maker vers les exchanges"
    if "alert_unlock_7d" in alerts:
        return types, alerts, sc, "skip", "alerte : unlock > 0,5 % de l'offre dans les 7 jours"
    if sc < float(rules.get("min_score_enter", 3.0)):
        return types, alerts, sc, "skip", f"score {sc} < seuil {rules.get('min_score_enter', 3.0)}"
    ch = max(c.get("change_24h") or 0, c.get("signal_candle_change") or 0)
    if ch >= float(rules.get("signal_candle_max_change", 0.15)):
        return types, alerts, sc, "wait", (f"bougie du signal (+{ch:.0%} sur la journée ou 24 h) : "
                                           "on n'achète jamais la bougie du signal, réévaluation dans 1-2 jours")
    return types, alerts, sc, "enter", f"score {sc} >= seuil, aucune alerte bloquante"


def decide_wait(w, rules):
    alerts = sorted(set(w.get("alerts", [])))
    unlock = w.get("unlock_supply_pct_7d")
    if unlock is not None and float(unlock) > float(rules.get("unlock_max_supply_pct", 0.005)):
        alerts = sorted(set(alerts) | {"alert_unlock_7d"})
    age = w["age_days"]
    if w.get("error"):
        return alerts, ("wait" if age < float(rules.get("wait_max_days", 2)) else "skip"), \
            f"données indisponibles : {w['error'][:80]}"
    if age < float(rules.get("wait_min_days", 1)) - 0.2:
        return alerts, None, "trop tôt pour réévaluer"
    fails = []
    if "alert_team_transfer" in alerts:
        fails.append("transferts de l'équipe vers les exchanges")
    if "alert_unlock_7d" in alerts:
        fails.append("unlock > 0,5 % de l'offre dans les 7 jours")
    vr = w.get("vol_ratio_vs_pre_signal")
    if vr is None or vr < float(rules.get("vol_ratio_min", 2.0)):
        fails.append(f"volume {vr and round(vr, 2)}x < {rules.get('vol_ratio_min', 2.0)}x la moyenne 14 j")
    dd = w.get("drop_from_signal_close")
    if dd is not None and dd < -float(rules.get("max_drop_from_signal_close", 0.15)):
        fails.append(f"prix {dd:.1%} depuis la clôture du jour du signal")
    if (w.get("change_24h") or 0) >= float(rules.get("signal_candle_max_change", 0.15)):
        fails.append(f"nouvelle bougie de signal (+{w['change_24h']:.0%})")
    if not fails:
        return alerts, "enter", (f"réévaluation J+{age:.1f} : volume {vr:.1f}x, prix "
                                 f"{(dd or 0):+.1%} depuis la clôture du signal, aucune alerte")
    if age < float(rules.get("wait_max_days", 2)) - 0.2 and not any("équipe" in f or "unlock" in f for f in fails):
        return alerts, "wait", "conditions non remplies (" + "; ".join(fails) + "), dernière chance demain"
    return alerts, "skip", "conditions d'entrée non remplies : " + "; ".join(fails)


def position_sql(arm, version, plan, pair, opened_ts, atr):
    return (
        "insert into positions(signal_id, strategy_version_id, arm, pair, side, opened_at, entry_price, "
        "size_usd, leverage, stop_price, tp_price, breakeven_trigger_price, trailing_pct, "
        "trailing_activate_price, max_hold_until, liquidation_price, atr_at_entry, margin_usd, "
        "last_checked_at, mfe_pct, mae_pct) values ("
        f"sid, {version['id']}, {q(arm)}, {q(pair)}, 'long', {qts(opened_ts)}, {q(plan['entry_price'])}, "
        f"{q(plan['size_usd'])}, {q(plan['leverage'])}, {q(plan['stop_price'])}, {q(plan['tp_price'])}, "
        f"{q(plan['breakeven_trigger_price'])}, {q(plan['trailing_pct'])}, "
        f"{q(plan['trailing_activate_price'])}, {qts(opened_ts + plan['max_hold_days'] * DAY)}, "
        f"{q(plan['liquidation_price'])}, {q(atr)}, {q(plan['margin_usd'])}, {qts(opened_ts)}, 0, 0)"
    )


def signal_block(sig, positions_sql):
    cols = ("pair, signal_types, score, info_published_at, evidence, price_at_detection, decision, "
            "decision_reason, data_source, alerts, metrics, signal_day_close, parent_signal_id, reevaluate_after")
    vals = ", ".join([q(sig["pair"]), qarr(sig["signal_types"]), q(sig["score"]),
                      qts(sig.get("info_published_at")), q(sig.get("evidence") or []),
                      q(sig.get("price")), q(sig["decision"]), q(sig["reason"]), q(sig.get("data_source")),
                      qarr(sig.get("alerts")), q(sig.get("metrics") or {}), q(sig.get("signal_day_close")),
                      q(sig.get("parent_signal_id")), qts(sig.get("reevaluate_after"))])
    body = [f"insert into signals({cols}) values ({vals}) returning id into sid;"]
    for arm, psql in positions_sql:
        body.append(
            f"begin {psql}; exception when others then "
            f"insert into iteration_log(routine, change, rationale) values ('analyse', "
            f"jsonb_build_object('blocked_entry', {q(sig['pair'])}, 'arm', {q(arm)}, 'signal_id', sid), "
            f"'Entrée refusée par les garde-fous de la base : ' || sqlerrm); end;")
    return "do $$ declare sid bigint; begin\n  " + "\n  ".join(body) + "\nend $$;\n"


def first_info_ts(news):
    ts = [stats.parse_ts(n["date_publication"]) for n in news if n.get("date_publication")]
    ts = [t for t in ts if t]
    return min(ts) if ts else None


def cmd_decide(a):
    st = load_json_loose(a.state)
    cd = load_json_loose(a.candidates)
    cfg = st["config"]
    rules = cfgv(cfg, "entry_rules", {})
    weights = {k: v for k, v in cfgv(cfg, "signal_weights", {}).items() if k != "version"}
    sources = tuple(cfgv(cfg, "data_sources", list(market.DEFAULT_SOURCES)))
    slip = float(cfgv(cfg, "slippage_pct", 0.001))
    cap = arm_capacity(st)
    remaining = {arm: cap[arm][0] for arm in ARMS}
    open_pairs = {(p["arm"], p["pair"]) for p in st.get("open_positions", [])}
    open_margin = {arm: sum(float(p.get("margin_usd") or p["size_usd"] / p["leverage"])
                            for p in st.get("open_positions", []) if p["arm"] == arm) for arm in ARMS}
    now = now_ts()
    decisions = []

    for w in cd.get("waits", []):
        alerts, dec, reason = decide_wait(w, rules)
        if dec is None:
            continue
        parent = w.get("parent") or {}
        decisions.append(dict(
            pair=w["pair"], signal_types=parent.get("signal_types") or ["wait_reevaluation"],
            score=parent.get("score"), info_published_at=parent.get("info_published_at"),
            evidence=(parent.get("evidence") or []) + w.get("news", []), price=w.get("last"),
            decision=dec, reason=reason, data_source=w.get("data_source"), alerts=alerts,
            metrics=dict(reevaluation=True, root_detected_at=w.get("root_detected_at"),
                         signal_day_ts=(parent.get("metrics") or {}).get("signal_day_ts"),
                         root_signal_id=(parent.get("metrics") or {}).get("root_signal_id", w["signal_id"]),
                         age_days=w["age_days"], vol_ratio_vs_pre_signal=w.get("vol_ratio_vs_pre_signal"),
                         drop_from_signal_close=w.get("drop_from_signal_close"), atr14=w.get("atr14"),
                         change_24h=w.get("change_24h"), entry_rules_version=rules.get("version")),
            signal_day_close=w.get("signal_day_close"), parent_signal_id=w["signal_id"],
            reevaluate_after=now + 0.8 * DAY if dec == "wait" else None, atr=w.get("atr14"),
            rank=float(parent.get("score") or 0) + 100))  # les wait validés passent en premier

    for c in cd.get("candidates", []):
        types, alerts, sc, dec, reason = decide_candidate(c, rules, weights)
        decisions.append(dict(
            pair=c["pair"], signal_types=types or ["none"], score=sc,
            info_published_at=first_info_ts(c.get("news", [])), evidence=c.get("news", []),
            price=c.get("last"), decision=dec, reason=reason, data_source=c.get("data_source"),
            alerts=alerts, atr=c.get("atr14"), rank=sc,
            metrics={k: c.get(k) for k in ("change_24h", "signal_candle_change", "signal_day_ts",
                                           "quote_vol_24h", "vol_ratio", "vol_doubling",
                                           "oi_change_3d", "rsi14", "atr14", "breakout_20d",
                                           "peak_passed", "listed_at", "unlock_supply_pct_7d", "notes")}
            | {"entry_rules_version": rules.get("version"),
               "weights_version": cfgv(cfg, "signal_weights", {}).get("version")},
            reevaluate_after=now + 0.8 * DAY if dec == "wait" else None))

    blocks, summary = [], []
    for d in sorted(decisions, key=lambda d: -d["rank"]):
        psqls = []
        if d["decision"] == "enter":
            try:
                entry, src = market.last_price(d["pair"], sources)
                entry *= 1 + slip
            except Exception as e:
                d["decision"], d["reason"] = "skip", f"prix indisponible : {e}"[:200]
                entry = None
            blocked = []
            for arm in ARMS if entry else ():
                if remaining[arm] <= 0:
                    blocked.append(cap[arm][1] or f"bras {arm} plein")
                    continue
                if (arm, d["pair"]) in open_pairs:
                    blocked.append(f"bras {arm} : pair déjà ouvert")
                    continue
                version = st["arms"][arm]["active_version"]
                try:
                    plan = risk.plan_position(version["params"], entry, float(st["arms"][arm]["equity"]),
                                              {k: cfgv(cfg, k) for k in cfg}, d.get("atr"), open_margin[arm])
                except ValueError as e:
                    blocked.append(f"bras {arm} : {e}")
                    continue
                psqls.append((arm, position_sql(arm, version, plan, d["pair"], now, d.get("atr"))))
                remaining[arm] -= 1
                open_margin[arm] += plan["margin_usd"]
            if entry and not psqls:
                d["decision"] = "skip"
                d["reason"] = "signal valide mais aucune place : " + "; ".join(blocked)
            elif blocked:
                d["reason"] += " | non ouvert : " + "; ".join(blocked)
            if entry:
                d["price"] = entry / (1 + slip)
        blocks.append(signal_block(d, psqls))
        summary.append(f"- {d['pair']} : {d['decision'].upper()} (score {d['score']}) — {d['reason']}"
                       + (f" -> bras {', '.join(x for x, _ in psqls)}" if psqls else ""))
    write(a.out, "\n".join(blocks) if blocks else "select 'aucune décision' as info;\n")
    print("Décisions du jour :\n" + ("\n".join(summary) if summary else "- aucun candidat"))


# ================================================================== CHECK
def pos_state(p):
    entry = float(p["entry_price"])
    stop = float(p["stop_price"])
    init = float(p.get("initial_stop_price") or stop)
    kind = "sl"
    if abs(stop - entry) / entry < 1e-9:
        kind = "breakeven"
    elif stop > init * (1 + 1e-9):
        kind = "trailing"
    return simulate.PosState(
        entry=entry, size_usd=float(p["size_usd"]), leverage=float(p["leverage"]), stop=stop,
        initial_stop=init, tp=float(p["tp_price"]), opened_ts=stats.parse_ts(p["opened_at"]),
        max_hold_ts=stats.parse_ts(p["max_hold_until"]),
        be_trigger=float(p["breakeven_trigger_price"]) if p.get("breakeven_trigger_price") else None,
        trailing_pct=float(p["trailing_pct"]) if p.get("trailing_pct") else None,
        trailing_activate=float(p["trailing_activate_price"]) if p.get("trailing_activate_price") else None,
        liquidation=float(p["liquidation_price"]) if p.get("liquidation_price") else None,
        highest=float(p.get("highest_price") or entry),
        lowest=entry * (1 + float(p.get("mae_pct") or 0)), stop_kind=kind)


def cmd_check(a):
    st = load_json_loose(a.state)
    cfg = st["config"]
    fee = float(cfgv(cfg, "fee_rate_per_side", 0.0005))
    fund = float(cfgv(cfg, "funding_rate_8h_estimate", 0.0001))
    slip = float(cfgv(cfg, "slippage_pct", 0.001))
    sources = tuple(cfgv(cfg, "data_sources", list(market.DEFAULT_SOURCES)))
    now = now_ts()
    sql, lines = [], []
    unreal = {arm: 0.0 for arm in ARMS}
    for p in st.get("open_positions", []):
        ps = pos_state(p)
        since = stats.parse_ts(p.get("last_checked_at") or p["opened_at"])
        start = max(ps.opened_ts, since) - simulate.CANDLE_SECONDS
        try:
            rows, src = market.candles(p["pair"], "15m", start, now, sources)
        except Exception as e:
            sql.append(f"insert into price_checks(position_id, note) values ({p['id']}, "
                       f"{q('ERREUR données : ' + str(e)[:300])});")
            lines.append(f"- #{p['id']} {p['arm']} {p['pair']} : données indisponibles, position laissée ouverte")
            continue
        rows = [r for r in rows if r["t"] >= ps.opened_ts - 1]
        hi = max((r["h"] for r in rows), default=None)
        lo = min((r["l"] for r in rows), default=None)
        last = rows[-1]["c"] if rows else None
        res = simulate.step(ps, rows, slip)
        if res is None and now >= ps.max_hold_ts and last is not None:
            res = dict(exit_price=last * (1 - slip), exit_reason="time", exit_ts=now)
        ev = "; ".join(str(e[0]) for e in ps.events)
        if res:
            r = simulate.pnl(ps, res["exit_price"], res["exit_ts"], res["exit_reason"], fee, fund)
            sql.append(
                f"update positions set status='closed', closed_at={qts(min(res['exit_ts'], now))}, "
                f"exit_price={q(res['exit_price'])}, exit_reason={q(res['exit_reason'])}, "
                f"pnl_usd={q(r['pnl_usd'])}, pnl_pct={q(r['pnl_pct'])}, r_multiple={q(r['r_multiple'])}, "
                f"fees_usd={q(r['fees_usd'])}, funding_usd={q(r['funding_usd'])}, mfe_pct={q(r['mfe_pct'])}, "
                f"mae_pct={q(r['mae_pct'])}, highest_price={q(ps.highest)}, stop_price={q(ps.stop)}, "
                f"last_checked_at={qts(now)} where id={p['id']} and status='open';")
            note = f"CLÔTURE {res['exit_reason']} à {res['exit_price']:.6g} ({src}) {ev}".strip()
            lines.append(f"- #{p['id']} {p['arm']} {p['pair']} : FERMÉE ({res['exit_reason']}) "
                         f"PnL {r['pnl_usd']:+.2f} USDT, R={r['r_multiple']}")
        else:
            if last is not None:
                qty = ps.size_usd / ps.entry
                unreal[p["arm"]] += qty * (last - ps.entry) - fee * ps.size_usd
            sql.append(
                f"update positions set stop_price={q(ps.stop)}, highest_price={q(ps.highest)}, "
                f"mfe_pct={q(round(ps.highest / ps.entry - 1, 6))}, "
                f"mae_pct={q(round(ps.lowest / ps.entry - 1, 6))}, last_checked_at={qts(now)} "
                f"where id={p['id']} and status='open';")
            note = f"ouverte ({src}) {ev}".strip()
            lines.append(f"- #{p['id']} {p['arm']} {p['pair']} : ouverte, dernier {last}, "
                         f"stop {ps.stop:.6g}{' — ' + ev if ev else ''}")
        sql.append(f"insert into price_checks(position_id, last_price, high_since_last, low_since_last, note) "
                   f"values ({p['id']}, {q(last)}, {q(hi)}, {q(lo)}, {q(note)});")
    if a.daily:
        sql.append(f"select paper_record_daily({q({k: round(v, 4) for k, v in unreal.items()})});")
    write(a.out, "begin;\n" + "\n".join(sql) + "\ncommit;\n" if sql else "select 'aucune position ouverte';\n")
    print(f"{len(st.get('open_positions', []))} positions vérifiées\n" + "\n".join(lines)
          + (f"\nPnL latent estimé par bras : {unreal}" if a.daily else ""))


# =============================================================== OUTCOMES
def cmd_outcomes(a):
    """Résultat a posteriori (10 j) de chaque signal, entré ou non : mesure des
    occasions manquées, avance du signal et résultats contrefactuels par bras."""
    h = load_json_loose(a.history)
    cfg = h["config"]
    fee = float(cfgv(cfg, "fee_rate_per_side", 0.0005))
    fund = float(cfgv(cfg, "funding_rate_8h_estimate", 0.0001))
    sources = tuple(cfgv(cfg, "data_sources", list(market.DEFAULT_SOURCES)))
    active = {}
    for v in h["versions"]:
        if v["status"] != "retired":
            active[v["arm"]] = v
    now = now_ts()
    sql, n = [], 0
    for s in h["signals"]:
        det = stats.parse_ts(s["detected_at"])
        if s.get("outcome_computed_at") or s.get("is_reference") or not s.get("price_at_detection"):
            continue
        if now - det < 10 * DAY or n >= a.limit:
            continue
        n += 1
        try:
            rows, src = market.candles(s["pair"], "1h", det - 3 * DAY, det + 10 * DAY, sources)
        except Exception as e:
            sql.append(f"update signals set outcome_computed_at=now(), counterfactual="
                       f"{q({'error': str(e)[:200]})} where id={s['id']};")
            continue
        p0 = float(s["price_at_detection"])
        after = [r for r in rows if r["t"] >= det]
        if not after:
            continue
        peak = max(after, key=lambda r: r["h"])
        pre = [r for r in rows if r["t"] <= peak["t"]]
        start = min(pre, key=lambda r: r["l"]) if pre else after[0]
        cf = {}
        for arm, v in active.items():
            try:
                plan = risk.plan_position(v["params"], p0, 1000.0, {k: cfgv(cfg, k) for k in cfg},
                                          (s.get("metrics") or {}).get("atr14"))
                rep = simulate.replay(plan, after, det, fee, fund)
                cf[arm] = dict(r=rep["r_multiple"], exit=rep["exit_reason"], version=v["id"])
            except Exception as e:
                cf[arm] = dict(error=str(e)[:100])
        sql.append(
            f"update signals set outcome_computed_at=now(), peak_at={qts(peak['t'])}, "
            f"peak_price={q(peak['h'])}, rise_started_at={qts(start['t'])}, "
            f"outcome_max_gain_pct={q(round(peak['h'] / p0 - 1, 6))}, "
            f"outcome_max_dd_pct={q(round(min(r['l'] for r in after) / p0 - 1, 6))}, "
            f"counterfactual={q(cf)} where id={s['id']};")
    write(a.out, "begin;\n" + "\n".join(sql) + "\ncommit;\n" if sql else "select 'aucun signal mûr';\n")
    print(f"{len(sql)} signaux mis à jour (résultat à 10 jours)")


# ================================================================== ADAPT
PARAM_PATHS = [("stop", "pct"), ("stop", "mult"), ("tp", "pct"), ("tp", "r"),
               ("max_hold_days",), ("breakeven_trigger_pct",), ("trailing", "activate_pct")]
FACTORS = (0.8, 0.9, 1.1, 1.2)  # jamais plus de ±20 % de la valeur actuelle
MIN_TRADES = 30
ROLLBACK_TRADES = 20


def get_path(d, path):
    for k in path:
        if not isinstance(d, dict) or d.get(k) is None:
            return None
        d = d[k]
    return d


def set_path(d, path, value):
    d = json.loads(json.dumps(d))
    cur = d
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    return d


class CandleCache:
    def __init__(self, sources):
        self.sources, self.cache = sources, {}

    def get(self, pair, start):
        key = (pair, int(start))
        if key not in self.cache:
            try:
                self.cache[key] = market.candles(pair, "1h", start - 3600, start + 13 * DAY, self.sources)[0]
            except Exception:
                self.cache[key] = None
        return self.cache[key]


def replay_trade(t, params, cfg, cache):
    rows = cache.get(t["pair"], stats.parse_ts(t["opened_at"]))
    if not rows:
        return None
    opened = stats.parse_ts(t["opened_at"])
    rows = [r for r in rows if r["t"] >= opened - 1]
    try:
        plan = risk.plan_position(params, float(t["entry_price"]), 1000.0,
                                  {k: cfgv(cfg, k) for k in cfg}, t.get("atr_at_entry") and float(t["atr_at_entry"]))
    except ValueError:
        return None
    rep = simulate.replay(plan, rows, opened, float(cfgv(cfg, "fee_rate_per_side", 0.0005)),
                          float(cfgv(cfg, "funding_rate_8h_estimate", 0.0001)),
                          float(cfgv(cfg, "slippage_pct", 0.001)), 3600)
    return rep and rep["r_multiple"]


def evaluate(trades, params, cfg, cache):
    return [replay_trade(t, params, cfg, cache) for t in trades]


def paired(a, b):
    return [x - y for x, y in zip(a, b) if x is not None and y is not None]


def cmd_adapt(a):
    h = load_json_loose(a.history)
    cfg = h["config"]
    sources = tuple(cfgv(cfg, "data_sources", list(market.DEFAULT_SOURCES)))
    versions = {v["id"]: v for v in h["versions"]}
    active = {}
    for v in h["versions"]:
        if v["status"] != "retired":
            active[v["arm"]] = v
    sig_by_id = {s["id"]: s for s in h["signals"]}
    closed = [p for p in h["positions"] if p["status"] == "closed"]
    cap0 = float(cfgv(cfg, "initial_capital_usdt", 1000))

    # ---- statistiques (toujours enregistrées)
    by_arm = {arm: stats.metrics([p for p in closed if p["arm"] == arm], cap0) for arm in ARMS}
    by_type = {}
    for p in closed:
        for ty in (sig_by_id.get(p["signal_id"]) or {}).get("signal_types", []) or ["inconnu"]:
            by_type.setdefault(f"{p['arm']}|{ty}", []).append(p)
    by_type = {k: stats.metrics(v) for k, v in by_type.items()}
    leads = []
    for s in h["signals"]:
        if s.get("info_published_at") and s.get("rise_started_at"):
            leads.append((stats.parse_ts(s["rise_started_at"]) - stats.parse_ts(s["info_published_at"])) / 3600)
    lead = dict(n=len(leads), mean_hours=stats.mean(leads))
    # occasions manquées : signaux non entrés dont le gain max 10 j >= 40 %
    missed = [dict(id=s["id"], pair=s["pair"], decision=s["decision"], max_gain=s["outcome_max_gain_pct"])
              for s in h["signals"] if s.get("decision") in ("skip", "wait")
              and (s.get("outcome_max_gain_pct") or 0) >= 0.40]
    # comparaison appariée des bras sur les mêmes signaux
    r_by_sig = {}
    for p in closed:
        if p.get("r_multiple") is not None:
            r_by_sig.setdefault(p["signal_id"], {})[p["arm"]] = float(p["r_multiple"])
    pair_cmp = {}
    for x in ARMS:
        for y in ARMS:
            if x < y:
                d = [v[x] - v[y] for v in r_by_sig.values() if x in v and y in v]
                pair_cmp[f"{x}-{y}"] = stats.bootstrap_mean_ci(d) if len(d) >= 2 else dict(n=len(d))
    report = dict(by_arm=by_arm, by_arm_signal_type=by_type, signal_lead=lead,
                  missed_opportunities=missed[-20:], paired_arm_diff_R=pair_cmp,
                  n_closed_by_arm={arm: by_arm[arm]["n"] for arm in ARMS})
    sql = [f"insert into iteration_log(routine, change, rationale, evidence) values ('adaptation', "
           f"{q({'action': 'stats'})}, {q('Statistiques quotidiennes (aucun changement implicite).')}, "
           f"{q(report)});"]
    msgs = []
    cache = CandleCache(sources)
    changed = False

    # ---- 1) retour arrière si une règle récente dégrade les résultats
    for arm in ARMS:
        v = active[arm]
        if changed or not v.get("parent_id") or not str(v.get("rationale", "")).startswith("ADAPT"):
            continue
        mine = sorted([p for p in closed if p["strategy_version_id"] == v["id"]],
                      key=lambda p: stats.parse_ts(p["opened_at"]))
        if len(mine) < ROLLBACK_TRADES:
            continue
        mine = mine[-ROLLBACK_TRADES:]
        parent = versions[v["parent_id"]]
        new_r = [float(p["r_multiple"]) if p.get("r_multiple") is not None else None for p in mine]
        old_r = evaluate(mine, parent["params"], cfg, cache)
        diff = paired(new_r, old_r)
        if diff and stats.mean(diff) < 0:
            ci = stats.bootstrap_mean_ci(diff)
            rationale = (f"ROLLBACK bras {arm} : sur les {len(diff)} derniers trades, la version {v['id']} "
                         f"fait {stats.mean(diff):+.3f} R/trade de moins que sa version parente {parent['id']} "
                         f"(rejouée sur les mêmes trades).")
            sql += [f"update strategy_versions set status='retired' where id={v['id']};",
                    f"insert into strategy_versions(name, arm, status, params, rationale, parent_id) values ("
                    f"{q(parent['name'] + '-restored')}, {q(arm)}, 'challenger', {q(parent['params'])}, "
                    f"{q(rationale)}, {v['id']});",
                    f"insert into iteration_log(routine, change, rationale, evidence) values ('adaptation', "
                    f"{q({'action': 'rollback', 'arm': arm, 'from': v['id'], 'to_params_of': parent['id']})}, "
                    f"{q(rationale)}, {q({'paired_diff_ci': ci})});"]
            msgs.append(rationale)
            changed = True

    # ---- 2) un seul changement à la fois, seulement au-delà de 30 trades
    proposals, refused = [], []
    if not changed:
        for arm in ARMS:
            v = active[arm]
            trades = [p for p in closed if p["arm"] == arm]
            if len(trades) < MIN_TRADES:
                msgs.append(f"Bras {arm} : {len(trades)}/{MIN_TRADES} trades fermés, aucun changement.")
                continue
            train, test = stats.walk_forward_split(trades, key=lambda p: stats.parse_ts(p["opened_at"]))
            base_train = evaluate(train, v["params"], cfg, cache)
            best = None
            for path in PARAM_PATHS:
                cur = get_path(v["params"], path)
                if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                    continue
                for f in FACTORS:
                    newp = set_path(v["params"], path, round(cur * f, 6))
                    if arm == "A" and newp.get("max_leverage", 2) > 2:
                        continue
                    r = evaluate(train, newp, cfg, cache)
                    d = paired(r, base_train)
                    if d and (best is None or stats.mean(d) > best[0]):
                        best = (stats.mean(d), path, cur, round(cur * f, 6), newp)
            if not best or best[0] <= 0:
                refused.append(f"Bras {arm} : aucun réglage ±20 % n'améliore la partie d'apprentissage (70 %).")
                continue
            d_test = paired(evaluate(test, best[4], cfg, cache), evaluate(test, v["params"], cfg, cache))
            ci = stats.bootstrap_mean_ci(d_test)
            item = dict(arm=arm, param=".".join(best[1]), old=best[2], new=best[3],
                        train_gain_R=round(best[0], 4), test=ci, n_train=len(train), n_test=len(test))
            if ci and ci["mean"] > 0 and ci["lo"] > 0:
                proposals.append(item)
            else:
                refused.append(f"Bras {arm} : {item['param']} {best[2]} -> {best[3]} refusé "
                               f"(test 30 % : {ci and round(ci['mean'], 3)} R, IC95 "
                               f"[{ci and round(ci['lo'], 3)}; {ci and round(ci['hi'], 3)}] non > 0).")
        if proposals:
            p = max(proposals, key=lambda x: x["test"]["mean"])
            v = active[p["arm"]]
            newp = set_path(v["params"], tuple(p["param"].split(".")), p["new"])
            rationale = (f"ADAPT bras {p['arm']} : {p['param']} {p['old']} -> {p['new']} (±20 % max). "
                         f"Walk-forward : +{p['train_gain_R']} R/trade sur 70 % anciens ({p['n_train']} trades), "
                         f"{p['test']['mean']:+.3f} R/trade sur 30 % récents ({p['n_test']} trades), "
                         f"IC95 bootstrap [{p['test']['lo']:+.3f}; {p['test']['hi']:+.3f}] > 0.")
            sql += [f"update strategy_versions set status='retired' where id={v['id']};",
                    f"insert into strategy_versions(name, arm, status, params, rationale, parent_id) values ("
                    f"{q(p['arm'] + '-adapt-v' + str(sum(1 for x in h['versions'] if x['arm'] == p['arm']) + 1))}, {q(p['arm'])}, 'champion', "
                    f"{q(newp)}, {q(rationale)}, {v['id']});",
                    f"insert into iteration_log(routine, change, rationale, evidence) values ('adaptation', "
                    f"{q({'action': 'promote', **{k: p[k] for k in ('arm', 'param', 'old', 'new')}})}, "
                    f"{q(rationale)}, {q(p)});"]
            msgs.append(rationale)
            changed = True
        for r in refused:
            sql.append(f"insert into iteration_log(routine, change, rationale) values ('adaptation', "
                       f"{q({'action': 'refused'})}, {q(r)});")

    # ---- 3) bras champion (comparaison appariée), sans toucher aux paramètres
    if not changed and all(by_arm[x]["n"] >= MIN_TRADES for x in ARMS):
        for x in ARMS:
            wins = []
            for y in ARMS:
                if x == y:
                    continue
                key = f"{min(x, y)}-{max(x, y)}"
                ci = pair_cmp.get(key) or {}
                sign = 1 if x < y else -1
                lo = ci.get("lo") if sign == 1 else (-ci["hi"] if ci.get("hi") is not None else None)
                wins.append(lo is not None and lo > 0)
            if all(wins) and active[x]["status"] != "champion":
                sql += [f"update strategy_versions set status='challenger' where status='champion' and id<>{active[x]['id']};",
                        f"update strategy_versions set status='champion' where id={active[x]['id']};",
                        f"insert into iteration_log(routine, change, rationale, evidence) values ('adaptation', "
                        f"{q({'action': 'arm_champion', 'arm': x})}, "
                        f"{q(f'Bras {x} meilleur que les deux autres en R apparié (IC95 > 0).')}, {q(pair_cmp)});"]
                msgs.append(f"Bras {x} désigné champion (comparaison appariée).")

    write(a.out, "begin;\n" + "\n".join(sql) + "\ncommit;\n")
    write(a.out.replace(".sql", ".json"), json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print("\n".join(msgs + refused) or "Rien à changer.")
    for arm in ARMS:
        m = by_arm[arm]
        print(f"Bras {arm}: n={m['n']} " + (f"réussite={m['win_rate']:.0%} R moyen={m['avg_r']}" if m["n"] else ""))


# ================================================================= REPORT
def fmt_pct(x, d=1):
    return "n/d" if x is None else f"{x * 100:.{d}f} %"


def fmt(x, d=2):
    return "n/d" if x is None else f"{x:.{d}f}"


def spark(values):
    bars = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    lo, hi = min(values), max(values)
    return "".join(bars[int((v - lo) / (hi - lo) * 7) if hi > lo else 3] for v in values)


def cmd_report(a):
    h = load_json_loose(a.history)
    cfg = h["config"]
    cap0 = float(cfgv(cfg, "initial_capital_usdt", 1000))
    now = now_ts()
    week_start = datetime.fromtimestamp(now, tz=timezone.utc).date() - timedelta(days=6)
    wk0 = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    pos = h["positions"]
    closed = [p for p in pos if p["status"] == "closed"]
    week_closed = [p for p in closed if stats.parse_ts(p["closed_at"]) >= wk0]
    sig = h["signals"]
    week_sig = [s for s in sig if stats.parse_ts(s["detected_at"]) >= wk0 and not s.get("is_reference")]
    daily = h.get("daily_results", [])
    L = []
    L.append(f"# Rapport hebdomadaire — paper trading crypto (semaine du {week_start.isoformat()})\n")
    L.append("> **DÉMO UNIQUEMENT.** Aucun ordre réel n'a été passé. Les résultats simulés ignorent une partie "
             "du glissement réel (0,1 % forfaitaire seulement), de la profondeur du carnet et du funding réel "
             "(estimé à 0,01 %/8 h). Aucun résultat n'est garanti.\n")
    if a.intro:
        try:
            intro = open(a.intro, encoding="utf-8").read().strip()
        except OSError:
            intro = ""
        if intro:
            L.append("## Lecture de la semaine\n\n" + intro + "\n")
    # capital
    L.append("## 1. Capital virtuel\n")
    L.append("Chaque bras est un portefeuille virtuel séparé de "
             f"{cap0:,.0f} USDT (mêmes signaux, mêmes entrées).\n".replace(",", " "))
    L.append("| Bras | Capital réalisé | ROI cumulé | PnL semaine | ROI semaine | Drawdown max | Trades fermés |")
    L.append("|---|---|---|---|---|---|---|")
    metrics = dict(by_arm={}, week_by_arm={})
    dd_alert = []
    for arm in ARMS:
        arm_closed = [p for p in closed if p["arm"] == arm]
        m = stats.metrics(arm_closed, cap0)
        mw = stats.metrics([p for p in week_closed if p["arm"] == arm])
        eq = cap0 + sum(float(p["pnl_usd"] or 0) for p in arm_closed)
        wk = sum(float(p["pnl_usd"] or 0) for p in week_closed if p["arm"] == arm)
        metrics["by_arm"][arm], metrics["week_by_arm"][arm] = m, mw
        eq_seq = [cap0]
        for p in sorted(arm_closed, key=lambda p: stats.parse_ts(p["closed_at"])):
            eq_seq.append(eq_seq[-1] + float(p["pnl_usd"] or 0))
        peak = max(eq_seq)
        if peak and (peak - eq) / peak > 0.15:
            dd_alert.append(arm)
        L.append(f"| {arm} | {eq:.2f} | {fmt_pct(eq / cap0 - 1)} | {wk:+.2f} | {fmt_pct(wk / (eq - wk) if eq - wk else None)} "
                 f"| {fmt_pct(m.get('max_drawdown_pct'))} | {m['n']} |")
    if daily:
        eqs = [float(d["equity"]) for d in daily if d.get("equity") is not None][-30:]
        L.append(f"\nCourbe de capital (somme des 3 bras, 30 derniers jours) : `{spark(eqs)}` "
                 f"({eqs[0]:.0f} → {eqs[-1]:.0f} USDT)\n" if eqs else "")
    if dd_alert:
        L.append(f"\n**⚠ ALERTE : drawdown > 15 % sur le(s) bras {', '.join(dd_alert)} — nouvelles entrées "
                 "suspendues pour ce(s) bras (GUARDRAILS.md, règle 4).**\n")
    # comparaison des bras
    L.append("\n## 2. Comparaison des bras A / B / C\n")
    L.append("| Bras | n | Réussite | R moyen | Espérance (USDT/trade) | Facteur de profit | Durée moy. (j) | MFE moy. | MAE moy. | Avertissement |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        m = metrics["by_arm"][arm]
        if m["n"] == 0:
            L.append(f"| {arm} | 0 | – | – | – | – | – | – | – | aucun trade fermé |")
            continue
        L.append(f"| {arm} | {m['n']} | {fmt_pct(m['win_rate'], 0)} | {fmt(m['avg_r'])} | {fmt(m['expectancy_usd'])} "
                 f"| {fmt(m['profit_factor'])} | {fmt(m['avg_duration_days'], 1)} | {fmt_pct(m['avg_mfe_pct'])} "
                 f"| {fmt_pct(m['avg_mae_pct'])} | {stats.sample_warning(m['n'])} |")
    L.append("\nRappel mathématique (hors frais) : bras A gain/perte = 40/25 = **1,6** → équilibre à **39 %** de "
             "réussite ; bras B = 40/12 = **3,3** → équilibre à **23 %**, mais B est plus souvent sorti par le bruit "
             "(les petites capitalisations bougent souvent de plus de 10 % par jour). Bras C : 2,5 R → équilibre ≈ 29 %.\n")
    # types de signaux
    L.append("## 3. Par type de signal (tous bras)\n")
    sig_by_id = {s["id"]: s for s in sig}
    types = {}
    for p in closed:
        for ty in (sig_by_id.get(p["signal_id"]) or {}).get("signal_types") or ["inconnu"]:
            types.setdefault(ty, []).append(p)
    if types:
        L.append("| Type | n trades | Réussite | R moyen | Avertissement |\n|---|---|---|---|---|")
        for ty, ps in sorted(types.items(), key=lambda kv: -len(kv[1])):
            m = stats.metrics(ps)
            L.append(f"| {ty} | {m['n']} | {fmt_pct(m['win_rate'], 0)} | {fmt(m['avg_r'])} | {stats.sample_warning(m['n'])} |")
    else:
        L.append("Aucun trade fermé pour l'instant : impossible de comparer les types de signaux.")
    metrics["by_signal_type"] = {k: stats.metrics(v) for k, v in types.items()}
    # avance du signal
    leads = [(stats.parse_ts(s["rise_started_at"]) - stats.parse_ts(s["info_published_at"])) / 3600
             for s in sig if s.get("info_published_at") and s.get("rise_started_at")]
    L.append("\n## 4. Avance du signal\n")
    L.append(f"Avance moyenne entre la première info publiée et le début de la hausse : "
             f"{fmt(stats.mean(leads), 1)} h sur {len(leads)} signaux mesurés "
             "(positif = l'info précède la hausse). " + stats.sample_warning(len(leads)))
    metrics["signal_lead_hours"] = stats.mean(leads)
    # décisions de la semaine
    dec = {}
    for s in week_sig:
        dec[s["decision"]] = dec.get(s["decision"], 0) + 1
    L.append(f"\nDécisions de la semaine : {dec or 'aucune'}.\n")
    metrics["week_decisions"] = dec
    # changements
    L.append("## 5. Changements de stratégie\n")
    logs = [l for l in h.get("iteration_log", []) if stats.parse_ts(l["created_at"]) >= wk0
            and l.get("routine") == "adaptation"]
    done = [l for l in logs if (l.get("change") or {}).get("action") in ("promote", "rollback", "arm_champion")]
    ref = [l for l in logs if (l.get("change") or {}).get("action") == "refused"]
    blocked = [l for l in h.get("iteration_log", []) if stats.parse_ts(l["created_at"]) >= wk0
               and (l.get("change") or {}).get("blocked_entry")]
    L += [f"- ✅ {l['rationale']}" for l in done] or ["- Aucun changement appliqué cette semaine "
                                                       "(seuil : 30 trades fermés par bras, puis walk-forward + bootstrap)."]
    L += [f"- ❌ {l['rationale']}" for l in ref[-10:]]
    if blocked:
        L.append(f"- {len(blocked)} entrée(s) bloquée(s) par les garde-fous de la base.")
    # trades notables
    L.append("\n## 6. Trades notables\n")
    if week_closed:
        best = max(week_closed, key=lambda p: float(p["r_multiple"] or 0))
        worst = min(week_closed, key=lambda p: float(p["r_multiple"] or 0))
        for lab, p in (("Meilleur", best), ("Pire", worst)):
            L.append(f"- {lab} : {p['pair']} bras {p['arm']}, {p['exit_reason']}, {float(p['pnl_usd']):+.2f} USDT "
                     f"(R = {fmt(float(p['r_multiple']))}, MFE {fmt_pct(float(p['mfe_pct'] or 0))}).")
    else:
        L.append("- Aucun trade fermé cette semaine.")
    missed = [s for s in sig if s.get("decision") in ("skip", "wait") and (s.get("outcome_max_gain_pct") or 0) >= 0.4
              and stats.parse_ts(s["detected_at"]) >= wk0 - 14 * DAY]
    L += [f"- Occasion manquée : {s['pair']} ({s['decision']}, {s['decision_reason'][:80]}…) a fait jusqu'à "
          f"{fmt_pct(s['outcome_max_gain_pct'])} en 10 j." for s in missed[:5]] or \
         ["- Aucune occasion manquée mesurée (les résultats à 10 jours arrivent après 10 jours)."]
    open_now = [p for p in pos if p["status"] == "open"]
    L.append(f"\nPositions ouvertes : {len(open_now)} — " +
             (", ".join(f"{p['pair']}({p['arm']})" for p in open_now) or "aucune"))
    # calendrier
    L.append("\n## 7. Calendrier de la semaine prochaine\n")
    cal = ""
    if a.calendar:
        try:
            cal = open(a.calendar, encoding="utf-8").read().strip()
        except OSError:
            cal = ""
    L.append(cal or "Calendrier non disponible (recherche web non effectuée).")
    # conclusion
    n_min = min(metrics["by_arm"][x]["n"] for x in ARMS)
    L.append("\n## 8. Limites et recommandation\n")
    L.append("- Démo : glissement, profondeur de marché et funding réels partiellement ignorés ; les prix viennent "
             "de sources publiques (Gate.io en priorité, puis OKX, MEXC, KuCoin).")
    L.append("- Échantillon de départ biaisé (4 cas, uniquement des hausses) : le vrai taux de réussite est ce que "
             "ce système mesure.")
    L.append(f"- Plus petit nombre de trades fermés par bras : **{n_min}**. "
             + ("**Ne pas envisager de réel** : il faut plusieurs dizaines de trades par bras (au moins 50-100) et "
                "un résultat stable sur plusieurs semaines, puis relire GUARDRAILS.md ensemble."
                if n_min < 100 else
                "Même avec un échantillon correct, un passage au réel exigerait une relecture de GUARDRAILS.md "
                "avec vous et un test à très petite taille ; ce système reste en démo."))
    md = "\n".join(L) + "\n"
    write(a.out, md)
    metrics["generated_at"] = iso(now)
    if a.sql:
        write(a.sql, f"insert into weekly_reports(week_start, report_md, metrics) values "
                     f"({q(week_start.isoformat())}::date, {q(md)}, {q(metrics)});\n")
    print(md)


# =================================================================== MAIN
def main(argv=None):
    ap = argparse.ArgumentParser(prog="engine.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--state", required=True); s.add_argument("--out", required=True)
    s = sub.add_parser("decide"); s.add_argument("--state", required=True)
    s.add_argument("--candidates", required=True); s.add_argument("--out", required=True)
    s = sub.add_parser("check"); s.add_argument("--state", required=True); s.add_argument("--out", required=True)
    s.add_argument("--daily", action="store_true")
    s = sub.add_parser("outcomes"); s.add_argument("--history", required=True); s.add_argument("--out", required=True)
    s.add_argument("--limit", type=int, default=40)
    s = sub.add_parser("adapt"); s.add_argument("--history", required=True); s.add_argument("--out", required=True)
    s = sub.add_parser("report"); s.add_argument("--history", required=True); s.add_argument("--out", required=True)
    s.add_argument("--calendar"); s.add_argument("--sql"); s.add_argument("--intro")
    a = ap.parse_args(argv)
    {"scan": cmd_scan, "decide": cmd_decide, "check": cmd_check, "outcomes": cmd_outcomes,
     "adapt": cmd_adapt, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
