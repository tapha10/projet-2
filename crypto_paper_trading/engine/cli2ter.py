"""Addendum 2ter — commandes des routines pour les paliers et les critères.

DÉMO UNIQUEMENT. Ce module ne passe aucun ordre : il lit des données publiques et
produit du SQL pour la base de démo. Les fonctions de calcul sont pures (elles
prennent un « fetch » de bougies en paramètre) pour être rejouées en mode sec
(engine/dryrun.py) avec exactement le même code qu'en production.

  python -m engine.cli2ter r5 --data data.json --out r5.sql [--weekly]
  python -m engine.cli2ter r6 --data data.json --out r6.sql --mode daily|weekly [--attempt 1|2]
  python -m engine.cli2ter section --data data.json --out tiers.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import discovery, features, market, stats, tiers
from .sqlgen import load_json_loose, q, qts

DAY = 86400
OFFICIAL = ("binance.com", "kucoin.com", "okx.com", "gate.io", "gate.com", "bybit.com", "coinbase.com",
            "upbit.com", "bithumb.com", "mexc.com", "bitget.com", "hyperliquid.xyz")
MAJOR_MEDIA = ("coindesk.com", "theblock.co", "cointelegraph.com", "decrypt.co", "blockworks.co",
               "cryptotimes.io", "bloomberg.com", "reuters.com", "dlnews.com", "wublock")


def cfgv(cfg, key, default=None):
    v = (cfg or {}).get(key, default)
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return default if v is None else v


def default_fetch(sources):
    def fetch(pair, interval, start, end):
        return market.candles(pair, interval, start, end, sources)[0]
    return fetch


# ============================================================ R1 : instantané + palier
def news_info(news, alerts, cand):
    domains, ts, types = set(), [], []
    best = None
    for n in news or []:
        dom = urlparse(n.get("url") or "").netloc.lower().removeprefix("www.")
        if dom:
            domains.add(dom)
        rel = 1.0 if any(dom.endswith(o) for o in OFFICIAL) else (
            0.7 if any(m in dom for m in MAJOR_MEDIA) else 0.4)
        best = max(best or 0, rel)
        if n.get("date_publication"):
            t = stats.parse_ts(n["date_publication"])
            if t:
                ts.append(t)
        if n.get("type"):
            types.append(n["type"])
    researched = cand.get("researched", bool(news) or bool(alerts))
    return dict(catalyst_type=types[0] if types else None, catalyst_reliability=best,
                info_published_at_ts=min(ts) if ts else None, n_sources=len(domains) if researched else None,
                unlock_next_days=cand.get("unlock_next_days"), unlock_last_days=cand.get("unlock_last_days"),
                team_transfer=("alert_team_transfer" in (alerts or [])) if researched else None,
                market_cap=cand.get("market_cap"))


def snapshot(pair, decision_ts, fetch, cand, btc_daily, oi=None):
    """Instantané des critères (bougies fermées avant decision_ts uniquement)."""
    daily = fetch(pair, "1d", decision_ts - 45 * DAY, decision_ts)
    hourly = fetch(pair, "1h", decision_ts - 3 * DAY, decision_ts)
    entry = cand.get("last") or (hourly[-1]["c"] if hourly else daily[-1]["c"])
    atr = cand.get("atr14")
    f = features.compute_features(decision_ts, daily, hourly, btc_daily, oi, cand.get("funding_rate"),
                                  news_info(cand.get("news"), cand.get("alerts"), cand),
                                  tiers.stop_pct(entry, atr, tiers.P1_STOP))
    f["detection_mode"] = cand.get("detection_modes")
    return f, features.eval_criteria(f)


def features_sql(pair, decision_ts, f, crit):
    return ("begin insert into signal_features(signal_id, decision_ts, pair, features, criteria) values "
            f"(sid, {qts(decision_ts)}, {q(pair)}, {q(f)}, {q(crit)}) on conflict (signal_id) do nothing; "
            "exception when others then insert into iteration_log(routine, change, rationale) values "
            f"('analyse', jsonb_build_object('features_error', {q(pair)}, 'signal_id', sid), sqlerrm); end;")


def t_entry(st, pair, entry, atr, now):
    """Plan de la position du portefeuille T (paliers) ou raison du refus."""
    cfg = st.get("config") or {}
    tier_state = cfgv(cfg, "tier_state", {})
    split = tuple((cfgv(cfg, "tranche_split", {}) or {}).get("split") or tiers.DEFAULT_SPLIT)
    t = (st.get("arms") or {}).get("T")
    if not t or not t.get("active_version"):
        return None, "portefeuille T absent (migration 004 non appliquée ?)"
    plan = tiers.plan_t_position(entry, float(t["equity"]), atr, tier_state, split)
    plan["pair"] = pair
    open_t = [p for p in st.get("open_positions", []) if p["arm"] == "T"]
    viol = tiers.check_t_guardrails(plan, float(t["equity"]), open_t, int(t["entries_today"]),
                                    float(t.get("drawdown") or 0))
    if viol:
        return None, "; ".join(viol)
    return plan, None


def t_position_sql(version_id, plan, pair, now):
    tr = {k: {kk: vv for kk, vv in v.items()} for k, v in plan["tranches"].items()}
    meta = dict(split=plan["split"], stop_dist=plan["stop_dist"], atr=plan["atr"],
                chandelier_mult=plan["chandelier_mult"], tranches=tr)
    return ("insert into positions(signal_id, strategy_version_id, arm, tier, pair, side, opened_at, entry_price, "
            "size_usd, leverage, stop_price, tp_price, max_hold_until, liquidation_price, atr_at_entry, margin_usd, "
            "last_checked_at, mfe_pct, mae_pct, tranches, lowest_price) values ("
            f"sid, {version_id}, 'T', 'P1', {q(pair)}, 'long', {qts(now)}, {q(plan['entry_price'])}, "
            f"{q(plan['size_usd'])}, {q(plan['leverage'])}, {q(plan['stop_price'])}, {q(plan['tp_price'])}, "
            f"{qts(now + max(v['max_hold_days'] for v in plan['tranches'].values()) * DAY)}, "
            f"{q(plan['liquidation_price'])}, {q(plan['atr'])}, {q(plan['margin_usd'])}, {qts(now)}, 0, 0, "
            f"{q(meta)}, {q(plan['entry_price'])})")


def decide_hook(st, d, entry, now, fetch, btc_daily, opened_abc):
    """Appelé par `cli decide --tiers` pour chaque signal. Renvoie (sql_extra, résumé)."""
    extra, note = [], []
    cand = dict(d.get("cand") or {})
    cand.setdefault("last", d.get("price"))
    cand.setdefault("atr14", d.get("atr"))
    cand.setdefault("news", d.get("evidence"))
    cand.setdefault("alerts", d.get("alerts"))
    try:
        f, crit = snapshot(d["pair"], now, fetch, cand, btc_daily)
        extra.append(features_sql(d["pair"], now, f, crit))
    except Exception as e:  # l'instantané ne doit jamais bloquer la décision
        note.append(f"instantané indisponible ({str(e)[:80]})")
    if d["decision"] == "enter" and entry and opened_abc:
        plan, why = t_entry(st, d["pair"], entry, d.get("atr"), now)
        if plan:
            vid = st["arms"]["T"]["active_version"]["id"]
            extra.append(
                f"begin {t_position_sql(vid, plan, d['pair'], now)}; exception when others then "
                f"insert into iteration_log(routine, change, rationale) values ('analyse', "
                f"jsonb_build_object('blocked_entry', {q(d['pair'])}, 'arm', 'T', 'signal_id', sid), "
                f"'Entrée palier refusée par les garde-fous de la base : ' || sqlerrm); end;")
            alloc = {k: round(v['share'], 3) for k, v in plan['tranches'].items()}
            note.append(f"palier T/P1 : {plan['size_usd']} USDT x{plan['leverage']}, stop -{plan['stop_dist']:.1%}, "
                        f"tranches {alloc}")
            st.setdefault("open_positions", []).append(dict(arm="T", pair=d["pair"], size_usd=plan["size_usd"]))
            st["arms"]["T"]["entries_today"] = int(st["arms"]["T"]["entries_today"]) + 1
        else:
            note.append(f"palier T refusé : {why}")
    return extra, "; ".join(note)


# ============================================================ R2 : tranches
def pos_from_row(p):
    meta = p.get("tranches") or {}
    entry = float(p["entry_price"])
    pos = dict(entry_price=entry, stop_price=float(p["stop_price"]), size_usd=float(p["size_usd"]),
               risk_usd=float(p.get("risk_usd") or 0), stop_dist=float(meta.get("stop_dist") or
                                                                     (entry - float(p["initial_stop_price"])) / entry),
               atr=meta.get("atr"), chandelier_mult=meta.get("chandelier_mult", tiers.CHANDELIER_ATR_MULT),
               tranches={k: dict(v) for k, v in (meta.get("tranches") or {}).items()},
               opened_ts=stats.parse_ts(p["opened_at"]), highest=float(p.get("highest_price") or entry),
               lowest=float(p.get("lowest_price") or entry), initial_stop_price=float(p["initial_stop_price"]),
               peak_ts=stats.parse_ts(p["peak_at"]) if p.get("peak_at") else stats.parse_ts(p["opened_at"]),
               split=meta.get("split"))
    return pos


def check_t(st, now, fetch, fee, fund, slip, refine=None, funding=None):
    """Suivi des positions du portefeuille T (tranches). Renvoie (sql, lignes, pnl latent)."""
    sql, lines, unreal, marks = [], [], 0.0, {}
    for p in [x for x in st.get("open_positions", []) if x["arm"] == "T"]:
        pos = pos_from_row(p)
        pos["through"] = stats.parse_ts(p["sim_through_at"]) if p.get("sim_through_at") else None
        try:
            rows = fetch(p["pair"], "15m", (pos["through"] or pos["opened_ts"]) - 900, now)
        except Exception as e:
            sql.append(f"insert into price_checks(position_id, note) values ({p['id']}, {q('ERREUR données : ' + str(e)[:200])});")
            lines.append(f"- #{p['id']} T {p['pair']} : données indisponibles")
            continue
        ev = tiers.step_tranches(pos, rows, slip, 900, refine=refine and refine(p["pair"]), now=now)
        last = rows[-1]["c"] if rows else None
        all_closed = all(d["status"] != "open" for d in pos["tranches"].values())
        rates = None
        if all_closed and funding:
            rates = funding(p["pair"], pos["opened_ts"], now)
        res = tiers.settle(pos, fee, fund, last, now, rates)
        meta = dict(p.get("tranches") or {})
        meta["tranches"] = pos["tranches"]
        common = (f"stop_price={q(max(pos['stop_price'], float(p['stop_price'])))}, highest_price={q(pos['highest'])}, "
                  f"lowest_price={q(pos['lowest'])}, mfe_pct={q(res['mfe_pct'])}, mae_pct={q(res['mae_pct'])}, "
                  f"mfe_r={q(res['mfe_r'])}, time_to_peak_h={q(res['time_to_peak_h'])}, "
                  f"peak_at={qts(pos['peak_ts'])}, tranches={q(meta)}, sim_through_at={qts(pos['through'])}, "
                  f"last_checked_at={qts(now)}")
        if all_closed:
            closed_ts = max(d.get("exit_ts") or 0 for d in pos["tranches"].values() if d["share"] > 0)
            reasons = "+".join(f"{k}:{d['exit_reason']}" for k, d in pos["tranches"].items() if d["share"] > 0)
            main_reason = pos["tranches"]["A"]["exit_reason"] if pos["tranches"]["A"]["share"] > 0 else "tp"
            qty = pos["size_usd"] / pos["entry_price"]
            exit_avg = sum(d["share"] * d["exit_price"] for d in pos["tranches"].values() if d["share"] > 0)
            fees = fee * (pos["size_usd"] + qty * exit_avg)
            sql.append(f"update positions set status='closed', closed_at={qts(min(closed_ts, now))}, "
                       f"exit_price={q(exit_avg)}, exit_reason={q(main_reason)}, pnl_usd={q(res['pnl_usd'])}, "
                       f"pnl_pct={q(round(exit_avg / pos['entry_price'] - 1, 6))}, r_multiple={q(res['r_multiple'])}, "
                       f"fees_usd={q(round(fees, 4))}, {common} where id={p['id']} and status='open';")
            lines.append(f"- #{p['id']} T {p['pair']} : FERMÉE ({reasons}) PnL {res['pnl_usd']:+.2f} USDT, "
                         f"R={res['r_multiple']}, par tranche {res['per_tranche']}")
        else:
            unreal += res["pnl_usd"]
            marks[str(p["id"])] = round(res["pnl_usd"], 4)
            sql.append(f"update positions set {common} where id={p['id']} and status='open';")
            done = [f"{k}:{d['exit_reason']}" for k, d in pos["tranches"].items() if d["status"] == "closed"]
            lines.append(f"- #{p['id']} T {p['pair']} : ouverte, stop {pos['stop_price']:.6g}, "
                         f"tranches fermées {done or 'aucune'}")
        note = ("tranches " + ", ".join(f"{e[0]}:{e[1]}" for e in ev)) if ev else "palier T"
        if pos.get("audit"):
            from .cli import audit_note
            note += " | " + audit_note(pos["audit"])
        sql.append(f"insert into price_checks(position_id, last_price, note) values ({p['id']}, {q(last)}, {q(note)});")
    return sql, lines, unreal, marks


# ============================================================ R5 : préparation des données
def r5_compute(data, fetch, now, weekly=False, max_signals=60):
    """Résultats d'ombre par palier et par découpe pour chaque signal (entré ou non).
    Renvoie dict(shadow=[...], outcomes={signal_id: {...}}, features=[...], log=...)."""
    cfg = data.get("config") or {}
    versions = {v["tier"]: v for v in data.get("tier_versions", []) if v.get("status") != "retired"}
    feats = {f["signal_id"]: f for f in data.get("features", [])}
    done = {(t["signal_id"], t["tier"]) for t in data.get("shadow_trades", []) if t.get("complete")}
    shadow, outcomes, new_feats, errors = [], {}, [], []
    btc = None
    n = 0
    for s in sorted(data.get("signals", []), key=lambda s: s["id"]):
        if s.get("is_reference") or not s.get("price_at_detection"):
            continue
        det = stats.parse_ts(s["detected_at"])
        if now - det > 35 * DAY:
            continue
        if all((s["id"], t) in done for t in tiers.TIERS) and s["id"] in feats:
            continue
        if n >= max_signals:
            break
        n += 1
        entry = float(s["price_at_detection"])
        atr = float(s["atr14"]) if s.get("atr14") not in (None, "null") else None
        try:
            rows = fetch(s["pair"], "1h", det - 3600, min(now, det + 31 * DAY))
        except Exception as e:
            errors.append(f"{s['pair']}: {str(e)[:80]}")
            continue
        rows = [r for r in rows if r["t"] >= det - 1]
        if s["id"] not in feats and weekly:
            # rattrapage : instantané calculé APRÈS coup mais avec les seules bougies fermées avant la détection
            try:
                if btc is None:
                    btc = fetch("BTCUSDT", "1d", now - 80 * DAY, now)
                f, crit = snapshot(s["pair"], det, fetch, dict(last=entry, atr14=atr), btc)
                f["backfilled"] = True
                new_feats.append(dict(signal_id=s["id"], decision_ts=det, pair=s["pair"], features=f, criteria=crit))
            except Exception as e:
                errors.append(f"instantané {s['pair']}: {str(e)[:60]}")
        out = {}
        for tier in tiers.TIERS:
            if (s["id"], tier) in done:
                continue
            res = tiers.shadow_tier_trade(tier, entry, atr, rows, det)
            if res is None:
                continue
            res["complete"] = res["complete"] or now - det > (10 if tier in ("P1", "P2") else 30) * DAY + DAY
            out[tier] = res
            shadow.append(dict(signal_id=s["id"], tier=tier, strategy_version_id=(versions.get(tier) or {}).get("id"),
                               opened_at=det, entry_price=entry, **{k: res[k] for k in
                               ("stop_pct", "win", "exit", "r", "r_slip2", "mfe_pct", "mae_pct", "hold_hours", "complete")}))
        splits = {}
        for name, sp in tiers.SPLITS.items():
            try:
                splits[name] = tiers.replay_split(entry, atr, rows, det, sp)["r_multiple"]
            except Exception:
                splits[name] = None
        outcomes[s["id"]] = dict(tiers={k: dict(win=v["win"], r=v["r"], r_slip2=v["r_slip2"], complete=v["complete"])
                                        for k, v in out.items()}, split_r=splits,
                                 complete=all(v["complete"] for v in out.values()) if out else False)
    log = dict(status="ok", signals_processed=n, shadow_rows=len(shadow), backfilled=len(new_feats),
               errors=errors[:10], weekly=weekly)
    return dict(shadow=shadow, outcomes=outcomes, features=new_feats, log=log)


def r5_sql(res):
    sql = []
    if res["shadow"]:
        cols = "signal_id, tier, strategy_version_id, opened_at, entry_price, stop_pct, win, exit_reason, r, r_slip2, mfe_pct, mae_pct, hold_hours, complete"
        rows = []
        for t in res["shadow"]:
            rows.append("(" + ", ".join([q(t["signal_id"]), q(t["tier"]), q(t["strategy_version_id"]), qts(t["opened_at"]),
                                         q(t["entry_price"]), q(round(t["stop_pct"], 6)), q(t["win"]), q(t["exit"]),
                                         q(round(t["r"], 4)), q(round(t["r_slip2"], 4)), q(round(t["mfe_pct"], 6)),
                                         q(round(t["mae_pct"], 6)), q(t["hold_hours"]), q(t["complete"])]) + ")")
        sql.append(f"insert into shadow_trades({cols}) values\n" + ",\n".join(rows) +
                   "\non conflict (signal_id, tier) do update set win=excluded.win, exit_reason=excluded.exit_reason, "
                   "r=excluded.r, r_slip2=excluded.r_slip2, mfe_pct=excluded.mfe_pct, mae_pct=excluded.mae_pct, "
                   "hold_hours=excluded.hold_hours, complete=excluded.complete, updated_at=now();")
    for f in res["features"]:
        sql.append(f"insert into signal_features(signal_id, decision_ts, pair, features, criteria) values "
                   f"({f['signal_id']}, {qts(f['decision_ts'])}, {q(f['pair'])}, {q(f['features'])}, {q(f['criteria'])}) "
                   "on conflict (signal_id) do nothing;")
    for sid, o in res["outcomes"].items():
        sql.append(f"update signal_features set outcomes = coalesce(outcomes, '{{}}'::jsonb) || {q(o)}, "
                   f"outcomes_complete = {q(o['complete'])}, updated_at = now() where signal_id = {sid};")
    sql.append(f"insert into iteration_log(routine, change, rationale, evidence) values ('routine5', "
               f"{q(dict(action='data_prep', status=res['log']['status'], weekly=res['log']['weekly']))}, "
               f"{q('Préparation des données 2ter : résultats d’ombre par palier et par découpe.')}, {q(res['log'])});")
    return sql


# ============================================================ R6 : paliers et critères
def build_events(data):
    """Événements indépendants à partir des signaux, critères et résultats d'ombre."""
    feats = {f["signal_id"]: f for f in data.get("features", [])}
    sh = {}
    for t in data.get("shadow_trades", []):
        sh.setdefault(t["signal_id"], {})[t["tier"]] = dict(
            win=t["win"], r=float(t["r"]) if t.get("r") is not None else None,
            r_slip2=float(t["r_slip2"]) if t.get("r_slip2") is not None else None, complete=t.get("complete"))
    rows = []
    for s in data.get("signals", []):
        f = feats.get(s["id"])
        if not f or s.get("is_reference"):
            continue
        outs = {k: v for k, v in sh.get(s["id"], {}).items() if v.get("complete") and v.get("r") is not None}
        rows.append(dict(id=s["id"], pair=s["pair"], ts=stats.parse_ts(s["detected_at"]),
                         criteria=f.get("criteria") or {}, outcomes=outs,
                         split_r=((f.get("outcomes") or {}).get("split_r") or {})
                         if (f.get("outcomes") or {}).get("complete") else {}))
    return features.cluster_events(rows)


def check_r5(data, now, max_age_h=8):
    last = data.get("last_r5")
    if not last:
        return False, "aucune exécution de la routine 5 trouvée"
    ch = last.get("change") or {}
    age = (now - stats.parse_ts(last["created_at"])) / 3600
    if ch.get("status") != "ok":
        return False, f"dernière routine 5 en échec ({ch.get('status')})"
    if age > max_age_h:
        return False, f"dernière routine 5 terminée il y a {age:.1f} h (> {max_age_h} h)"
    return True, f"routine 5 terminée il y a {age:.1f} h"


def r6_compute(data, now, mode="daily", attempt=1):
    cfg = data.get("config") or {}
    ok, why = check_r5(data, now, 8 if mode == "daily" else 3)
    if not ok:
        if attempt < 2:
            return dict(status="wait", why=why, retry_minutes=30)
        return dict(status="not_run", why=why, log=dict(action="not_run", reason=why, mode=mode))
    ro_until = cfgv(cfg, "r6_readonly_until", None)
    read_only = ro_until is None or now < stats.parse_ts(ro_until)
    events = build_events(data)
    tier_state = cfgv(cfg, "tier_state", {})
    per_tier = {}
    for tier in tiers.TIERS:
        outs = [e["outcomes"][tier] for e in events if tier in e["outcomes"]]
        n = len(outs)
        k = sum(1 for o in outs if o["win"])
        lo, hi = tiers.wilson(k, n)
        per_tier[tier] = dict(n_events=n, wins=k, win_rate=(k / n) if n else None, lo80=lo, hi80=hi,
                              avg_r=(sum(o["r"] for o in outs) / n) if n else None, breakeven=tiers.BREAKEVEN[tier],
                              status=(tier_state.get(tier) or {}).get("status", "shadow"))
    res = dict(status="ok", mode=mode, read_only=read_only, per_tier=per_tier, n_events=len(events))
    if mode == "daily":
        tracked = [(f["tier"], f["criterion"]) for f in data.get("entry_filters", []) if f.get("status") in ("retenu", "hypothèse")]
        res["tracked"] = []
        for tier, crit in tracked[:50]:
            s = discovery.lift_stats(events, discovery.filter_fn(crit), tier)
            res["tracked"].append(dict(tier=tier, criterion=crit, lift=s["lift"], n_with=s["n_with"]))
        res["log"] = dict(action="daily_light", read_only=read_only, n_events=len(events), per_tier=per_tier)
        return res
    tests = discovery.analyse(events)
    new_state, decisions = discovery.decide_tiers(events, tier_state, tests, now, read_only=read_only)
    split_cmp = discovery.compare_splits([dict(ts=e["ts"], split_r=e["split_r"]) for e in events if e["split_r"]],
                                         (cfgv(cfg, "tranche_split", {}) or {}).get("name", "50/30/20"))
    p4 = discovery.p4_rare_events(data.get("signals", []))
    top = sorted([t for t in tests if t["lift"] is not None], key=lambda t: (not t["retained"], t["p_adj"], -t["lift"]))[:5]
    labels = {}
    for tier in tiers.TIERS:
        st = (new_state.get(tier) or tier_state.get(tier) or {}).get("status", "shadow")
        tested = per_tier[tier]["n_events"]
        labels[tier] = "débloqué" if tier == "P1" else tiers.tier_label(tier, st, tested, per_tier[tier]["hi80"])
    if p4["verdict"] == "inconclusif" and labels["P4"] != "débloqué":
        labels["P4"] = "inconclusif"
    res.update(tests=tests, decisions=decisions, new_state=new_state, split_cmp=split_cmp, p4=p4, top=top,
               labels=labels, log=dict(action="weekly_full", read_only=read_only, n_events=len(events),
                                       n_tests=len(tests), n_retained=sum(1 for t in tests if t["retained"]),
                                       decisions=[{k: v for k, v in d.items() if k != "detail"} for d in decisions],
                                       labels=labels, split=split_cmp.get("best"), p4=p4))
    return res


def r6_sql(res, holder="routine6"):
    if res["status"] == "wait":
        return []
    if res["status"] == "not_run":
        return [f"insert into iteration_log(routine, change, rationale, evidence) values ('routine6', "
                f"{q(dict(action='not_run', status='not_run'))}, {q('Routine 6 non exécutée : ' + res['why'])}, {q(res['log'])});"]
    sql = []
    if res["mode"] == "weekly":
        for t in res["tests"]:
            if t["n_with"] < 5:
                continue
            validity = (f"lift {t['lift']:+.2f} sur {t['n_with']} événements ; validation {t['valid_lift'] if t['valid_lift'] is None else round(t['valid_lift'], 3)}"
                        + ("" if t["retained"] else " ; reste une hypothèse"))
            sql.append(
                "insert into entry_filters(tier, criterion, status, n_with, n_without, wr_with, wr_without, lift, lo80, hi80, "
                "p, p_adj, valid_lift, validity, active) values ("
                + ", ".join([q(t["tier"]), q(t["criterion"]), q(t["status"]), q(t["n_with"]), q(t["n_without"]),
                             q(t["wr_with"]), q(t["wr_without"]), q(t["lift"]), q(t["lo80"]), q(t["hi80"]), q(t["p"]),
                             q(t["p_adj"]), q(t["valid_lift"]), q(validity), q(bool(t["retained"] and not res["read_only"]))])
                + ") on conflict (tier, criterion) do update set status=excluded.status, n_with=excluded.n_with, "
                "n_without=excluded.n_without, wr_with=excluded.wr_with, wr_without=excluded.wr_without, lift=excluded.lift, "
                "lo80=excluded.lo80, hi80=excluded.hi80, p=excluded.p, p_adj=excluded.p_adj, valid_lift=excluded.valid_lift, "
                "validity=excluded.validity, active=excluded.active;")
        for d in res["decisions"]:
            applied = (not res["read_only"]) and d["action"] in ("unlock", "risk_up", "demote")
            sql.append(f"insert into promotion_decisions(routine, tier, action, detail, applied, read_only) values "
                       f"('routine6', {q(d['tier'])}, {q(d['action'])}, {q(d)}, {q(applied)}, {q(res['read_only'])});")
        if res["split_cmp"].get("change"):
            sql.append(f"insert into promotion_decisions(routine, tier, action, detail, applied, read_only) values "
                       f"('routine6', null, 'split_change', {q(res['split_cmp'])}, {q(not res['read_only'])}, {q(res['read_only'])});")
            if not res["read_only"]:
                ch = res["split_cmp"]["change"]["to"]
                sql.append(f"update config set value = {q(dict(name=ch, split=list(tiers.SPLITS[ch])))} where key = 'tranche_split';")
        if not res["read_only"]:
            sql.append(f"update config set value = {q(res['new_state'])} where key = 'tier_state';")
            for tier in ("P2", "P3", "P4"):
                st = (res["new_state"].get(tier) or {}).get("status")
                if st:
                    sql.append(f"update strategy_versions set status = {q('champion' if st == 'unlocked' else 'shadow')} "
                               f"where arm = 'T' and tier = {q(tier)} and status <> 'retired';")
    rationale = ("Routine 6 (" + res["mode"] + ")" + (" en LECTURE SEULE : constats sans décision" if res["read_only"] else "")
                 + f" — {res['n_events']} événements indépendants.")
    sql.append(f"insert into iteration_log(routine, change, rationale, evidence) values ('routine6', "
               f"{q(dict(action=res['log']['action'], status='ok', read_only=res['read_only']))}, {q(rationale)}, {q(res['log'])});")
    return sql


# ============================================================ R4 : section du rapport
def report_section(data, r6=None):
    now = time.time()
    r6 = r6 or r6_compute(dict(data, last_r5=dict(created_at=datetime.now(timezone.utc).isoformat(),
                                                  change={"status": "ok"})), now, "weekly")
    L = ["## 9. Échelle d'ambition : paliers P1 à P4 (addendum 2ter)\n"]
    if r6.get("read_only"):
        L.append("> Routine 6 en **lecture seule** (7 premiers jours) : constats uniquement, aucune décision de palier.\n")
        week = [p for p in data.get("tier_positions", []) if stats.parse_ts(p["opened_at"]) >= now - 7 * DAY]
        from .recap import ACTION_FR
        would = [f"{d['tier']} : {ACTION_FR.get(d['action'], d['action'])}" for d in r6.get("decisions", [])]
        L.append(f"Comparaison lecture seule : cette semaine, la routine 1 a ouvert {len(week)} position(s) du "
                 f"portefeuille T (palier P1 seul actif) ; la routine 6 aurait décidé : "
                 f"{', '.join(would) if would else 'rien'}.\n")
    L.append("| Palier | Objectif | Statut | Événements | Réussite | IC 80 % | R moyen | Équilibre |")
    L.append("|---|---|---|---|---|---|---|---|")
    for tier in tiers.TIERS:
        s = r6["per_tier"][tier]
        wr = "–" if s["win_rate"] is None else f"{s['win_rate']:.0%}"
        ar = "–" if s["avg_r"] is None else f"{s['avg_r']:+.2f}"
        L.append(f"| {tier} | {tiers.TARGET_R[tier]:g} R | {r6['labels'][tier]} | {s['n_events']} | {wr} | "
                 f"[{s['lo80']:.0%} ; {s['hi80']:.0%}] | {ar} | {s['breakeven']:.0%} |")
    L.append("\n**Top 5 des critères testés** (lift = écart de taux de réussite avec / sans) :\n")
    if r6["top"]:
        L.append("| Palier | Critère | n avec | Lift | p corrigée (BH) | Statut |\n|---|---|---|---|---|---|")
        for t in r6["top"]:
            from .recap import crit_fr
            L.append(f"| {t['tier']} | {crit_fr(t['criterion'])} | {t['n_with']} | {t['lift']:+.2f} | {t['p_adj']:.3f} | {t['status']} |")
    else:
        L.append("Aucun critère testable pour l'instant (il faut des signaux avec résultats complets).")
    sc = r6["split_cmp"]
    L.append(f"\n**Découpes de sortie** (hors apprentissage, {sc['n_test']} événements) : "
             + ", ".join(f"{k} : {('–' if v['mean_r'] is None else format(v['mean_r'], '+.2f'))} R (n={v['n']})"
                         for k, v in sc["by_split"].items())
             + (f" → changement proposé vers {sc['change']['to']}." if sc.get("change") else " → pas de changement."))
    p4 = r6["p4"]
    L.append(f"\n**P4 (x50)** : {p4['n_big']} hausse(s) > 250 % sur {p4['n_signals']} signaux suivis à 10 jours ; "
             f"verdict : {p4['verdict']}.")
    missing = []
    for tier in ("P2", "P3", "P4"):
        need = tiers.MIN_EVENTS_UNLOCK[tier]
        n = r6["per_tier"][tier]["n_events"]
        if n < need:
            missing.append(f"{tier} : {n}/{need} événements indépendants avec résultat")
    L.append("\n**Ce qui manque pour trancher** : " + ("; ".join(missing) if missing else "rien de quantitatif ; voir décisions."))
    L.append("\n**Prochaine expérience proposée** : " + next_experiment(r6))
    return "\n".join(L) + "\n"


def next_experiment(r6):
    hyp = [t for t in r6.get("tests", []) if t["status"] == "hypothèse" and (t["lift"] or 0) >= 0.10]
    if hyp:
        t = max(hyp, key=lambda t: t["lift"])
        from .recap import crit_fr
        return (f"suivre en priorité « {crit_fr(t['criterion'])} » sur {t['tier']} (lift {t['lift']:+.2f} sur {t['n_with']} "
                f"événements, il en faut 30) en enrichissant la collecte des signaux qui le vérifient.")
    if r6["n_events"] < 40:
        return "accumuler des événements indépendants (élargir la collecte des candidats, y compris les skip)."
    return "tester la découpe 30/30/40 contre 50/30/20 sur les 30 prochains événements."


# ============================================================ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="engine.cli2ter")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("r5"); s.add_argument("--data", required=True); s.add_argument("--out", required=True)
    s.add_argument("--weekly", action="store_true")
    s = sub.add_parser("r6"); s.add_argument("--data", required=True); s.add_argument("--out", required=True)
    s.add_argument("--mode", choices=("daily", "weekly"), default="daily"); s.add_argument("--attempt", type=int, default=1)
    s = sub.add_parser("section"); s.add_argument("--data", required=True); s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    data = load_json_loose(a.data)
    sources = tuple(cfgv(data.get("config"), "data_sources", list(market.DEFAULT_SOURCES)))
    now = time.time()
    if a.cmd == "r5":
        res = r5_compute(data, default_fetch(sources), now, a.weekly)
        sql = r5_sql(res)
        open(a.out, "w").write("begin;\n" + "\n".join(sql) + "\ncommit;\n")
        print(json.dumps(res["log"], ensure_ascii=False))
    elif a.cmd == "r6":
        res = r6_compute(data, now, a.mode, a.attempt)
        sql = r6_sql(res)
        open(a.out, "w").write(("begin;\n" + "\n".join(sql) + "\ncommit;\n") if sql else "select 'attente' as info;\n")
        if res["status"] == "wait":
            print(f"ATTENTE : {res['why']} — réessayer dans {res['retry_minutes']} minutes (tentative 2).")
        elif res["status"] == "not_run":
            print(f"NON EXÉCUTÉE : {res['why']}")
        else:
            print(json.dumps({k: v for k, v in res["log"].items() if k != "per_tier"}, ensure_ascii=False, default=str)[:1500])
            for tier, s in res["per_tier"].items():
                print(f"{tier}: {s['n_events']} événements, réussite {s['win_rate']}, statut {s['status']}")
    elif a.cmd == "section":
        open(a.out, "w").write(report_section(data))
        print(open(a.out).read())


if __name__ == "__main__":
    sys.exit(main())
