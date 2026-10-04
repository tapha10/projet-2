"""Ligne de commande utilisée par les routines.

python -m foot.cli <commande> [options]
  audit                     audit des sources -> foot_source_audit
  history [--refresh]       télécharge l'historique (cache local)
  backtest                  backtest complet M0..M4 + références -> docs/backtest.md, data/base_full.pkl
  train                     entraîne M2/M3/M4 sur l'historique et sauvegarde models_store/learned.pkl
  r1 [--day J] [--fixtures F]   prédictions + combinés du jour (verrouillés à l'exécution)
  r2 [--news F.json]        nouvelles d'avant-match (compositions/absences) -> foot_team_news
  r3                        résultats + règlement
  r4 [--day J]              rapport du lendemain
  r6 [--day J]              rapport hebdomadaire
  state-load DIR            recharge l'état exporté de Supabase (un fichier JSON par table)
  dump-queries              requêtes SQL d'export de l'état Supabase
  outbox [--clear]          affiche (et vide) les requêtes SQL à appliquer sur Supabase
  state-query / state-load-json F   export/import de l'état Supabase en une requête
  gate RX                   vérifie que la routine précédente n'a pas échoué
  lock-sql acquire|release HOLDER   SQL du verrou partagé (table foot_locks sur Supabase)
  not-run RX "motif"        journalise une routine non exécutée
  r5 [--deep]               optimisation : métriques en direct, recalibration, prochaine hypothèse
  exp-check / exp-record / lesson   mémoire (un test identique n'est jamais relancé)
Base locale : data/foot.sqlite ; boîte d'envoi : data/state/outbox.sql
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import AVERTISSEMENT, ROOT, load_config
from .db import Store, dump_queries, now_utc

DB = ROOT / "data" / "foot.sqlite"
OUTBOX = ROOT / "data" / "state" / "outbox.sql"
LEARNED = ROOT / "models_store" / "learned.pkl"
PARIS = ZoneInfo("Europe/Paris")


def store():
    DB.parent.mkdir(parents=True, exist_ok=True)
    return Store(DB)


def today_paris():
    return datetime.now(PARIS).date()


def cmd_audit(a):
    from .audit import run_audit
    s = store()
    for r in run_audit(s):
        print(f"{'OK ' if r['accessible'] else 'NON'} {r['status_code']} {r['source']} — {r['notes']}")
    s.flush_outbox(OUTBOX)


def load_hist(refresh=False, seasons=None):
    from .data import load_history
    log = []
    cfg = load_config()
    df = load_history(seasons=seasons, cfg=cfg, refresh_current=refresh, log=log)
    for m in log:
        print("manquant :", m, file=sys.stderr)
    return df


def cmd_history(a):
    df = load_hist(a.refresh)
    df.to_pickle(ROOT / "data" / "history.pkl")
    print(len(df), "matchs ;", df.kickoff.max())


def cmd_train(a):
    from .pipeline import fit_learned
    from .backtest import build_base, add_learned_models
    from .stats import log_loss
    from .models import m4_weights
    cfg = load_config()
    base_p = ROOT / "data" / "base_full.pkl"
    if base_p.exists() and not a.rebuild:
        full = pd.read_pickle(base_p)
    else:
        hist = load_hist(refresh=True)
        base = build_base(hist, cfg, seasons_test=cfg["saisons_historiques"][1:])
        full, _ = add_learned_models(base)
        full.to_pickle(base_p)
    learned = fit_learned(full)
    recent = full[full.season == full.season.max()].dropna(subset=["y"])
    if len(recent) < 1000:
        recent = full[full.season >= sorted(full.season.unique())[-2]].dropna(subset=["y"])
    ll = {m: log_loss(recent.dropna(subset=[m])[m], recent.dropna(subset=[m]).y)
          for m in ["p_m0", "p_m1", "p_m2", "p_m3"] if recent[m].notna().sum() > 300}
    w = m4_weights(ll)
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNED, "wb") as f:
        pickle.dump({"learned": learned, "m4w": w, "trained_at": now_utc().isoformat(),
                     "n_train": int(full.y.notna().sum())}, f)
    print("poids M4 :", w)


def get_learned():
    if LEARNED.exists():
        with open(LEARNED, "rb") as f:
            d = pickle.load(f)
        return d["learned"], d["m4w"]
    return None, None


def cmd_r1(a):
    from .data import load_fixtures
    from .pipeline import run_r1
    cfg = load_config()
    day = date.fromisoformat(a.day) if a.day else today_paris()
    s = store()
    cur = cfg["saison_courante"]
    seasons = [x for x in cfg["saisons_historiques"] if x >= str(int(cur[:2]) - 2).zfill(2) + str(int(cur[2:]) - 2).zfill(2)]
    hist = load_hist(refresh=True, seasons=seasons)
    fx, captured = load_fixtures(cfg, a.fixtures)
    learned, m4w = get_learned()
    if m4w:
        cfg["_m4_poids"] = m4w
    out = run_r1(s, hist, fx, captured, day, cfg, hist_base=None, now=now_utc(), learned=learned)
    c = out["combos"]["principal"]
    print(f"{AVERTISSEMENT}\nPhase {out['phase']} — {len(out['decisions'])} matchs évalués, "
          f"{sum(d.get('retenu', False) for d in out['decisions'])} sélection(s).")
    for l in c["legs"]:
        print(f"  {l['home']} – {l['away']} ({l['league']}) {l['side']} @ {l['odds']:.2f} p={l['p']:.3f} ev={l['ev']:+.3f}")
    if c["legs"]:
        print(f"  cote {c['cote']:.2f} · p estimée {c['p_estimee']:.4f} · seuil {c['seuil_equilibre']:.4f}")
    for n in c["notes"]:
        print("  note :", n)
    (ROOT / "data" / "state").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "state" / f"combo_{day.isoformat()}.json", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in c.items()}, f, default=str, ensure_ascii=False)
    from .report import append_today_combo
    new = append_today_combo(s, day - timedelta(days=1), c)
    if new:
        write_report_file(day - timedelta(days=1), new)
    s.flush_outbox(OUTBOX)


def write_report_file(day, content, weekly=False):
    d = ROOT / "rapports" / ("hebdo" if weekly else "quotidien")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day.isoformat()}.md").write_text(content, encoding="utf-8")


def cmd_r2(a):
    from .pipeline import run_r2
    s = store()
    news = json.loads(Path(a.news).read_text()) if a.news else []
    n = run_r2(s, news)
    print(f"{n} nouvelle(s) enregistrée(s)" + ("" if news else " — aucune source de compositions accessible"))
    s.flush_outbox(OUTBOX)


def results_frame(cfg):
    """Scores finaux : football-data (saison courante) + OpenLigaDB (Allemagne)."""
    from .data import load_history
    cur = load_history(seasons=[cfg["saison_courante"]], cfg=cfg, refresh_current=True)
    res = cur[["match_id", "fthg", "ftag"]].dropna().assign(status="FT", source="football-data")
    return res


def cmd_r3(a):
    from .pipeline import run_r3, analyse_errors
    cfg = load_config()
    s = store()
    res = results_frame(cfg)
    n = run_r3(s, res)
    for d in range(1, 4):
        analyse_errors(s, today_paris() - timedelta(days=d))
    print(f"{n} résultat(s) enregistré(s)")
    s.flush_outbox(OUTBOX)


def cmd_r4(a):
    from .report import daily_report
    s = store()
    day = date.fromisoformat(a.day) if a.day else today_paris() - timedelta(days=1)
    p = ROOT / "data" / "state" / f"combo_{(day + timedelta(days=1)).isoformat()}.json"
    combo = json.loads(p.read_text()) if p.exists() else None
    content = daily_report(s, day, combo)
    write_report_file(day, content)
    print(content)
    s.flush_outbox(OUTBOX)


def cmd_r6(a):
    from .report import weekly_report
    s = store()
    day = date.fromisoformat(a.day) if a.day else today_paris()
    from .r5 import live_model_table
    table, _ = live_model_table(s)
    content = weekly_report(s, day, model_table=table)
    write_report_file(day, content, weekly=True)
    print(content)
    s.flush_outbox(OUTBOX)


def cmd_state_load(a):
    s = store()
    d = Path(a.dir)
    for t in dump_queries():
        f = d / f"{t}.json"
        if f.exists():
            rows = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows and isinstance(rows[0], dict) and "rows" in rows[0]:
                rows = rows[0]["rows"] or []
            s.load_dump(t, rows)
            print(t, len(rows))


def cmd_state_load_json(a):
    """Charge un objet JSON {table: [lignes]} (sortie de la requête `state-query`)."""
    s = store()
    data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    if isinstance(data, list):  # sortie brute de l'outil SQL : [{"state": {...}}]
        data = data[0].get("state", data[0])
    for t in dump_queries():
        if t in data:
            s.load_dump(t, data[t] or [])
            print(t, len(data[t] or []))


def cmd_state_query(a):
    from .db import state_query
    print(state_query(a.days))


def cmd_gate(a):
    """Dépendances : R2<-R1, R4<-R3, R5<-R3, R6<-R4. Sortie 1 si la routine précédente a échoué."""
    from .memory import last_status
    deps = {"R2": "R1", "R4": "R3", "R5": "R3", "R6": "R4"}
    s = store()
    prev = deps.get(a.routine)
    st = last_status(s, prev) if prev else None
    if st and st["status"] == "échec":
        print(f"BLOQUÉ : dernière exécution de {prev} en échec ({st['finished_at']})")
        sys.exit(1)
    print(f"OK : {a.routine} peut tourner" + (f" ({prev} : {st['status'] if st else 'jamais exécutée'})" if prev else ""))


def cmd_lock_sql(a):
    from .db import lock_sql
    print(lock_sql(a.action, a.holder))


def cmd_not_run(a):
    s = store()
    s.insert("foot_iteration_log", {"routine": a.routine, "run_day": today_paris().isoformat(),
                                    "started_at": now_utc(), "finished_at": now_utc(),
                                    "status": "non exécutée", "details": a.reason})
    s.flush_outbox(OUTBOX)


def cmd_r5(a):
    from .r5 import run_r5
    s = store()
    print(run_r5(s, deep=a.deep))
    s.flush_outbox(OUTBOX)


def cmd_exp_check(a):
    from .memory import should_run
    s = store()
    go, key, why = should_run(s, a.hypothesis, json.loads(a.protocol), a.reason)
    print(json.dumps({"lancer": go, "cle": key, "motif": why}, ensure_ascii=False))
    sys.exit(0 if go else 3)


def cmd_exp_record(a):
    from .memory import record_experiment
    s = store()
    k = record_experiment(s, a.hypothesis, json.loads(a.protocol), json.loads(a.result), a.conclusion,
                          a.data, a.period, a.model, (a.ci_low, a.ci_high), a.reason)
    if a.hyp_title:
        s.insert("foot_hypotheses", {"title": a.hyp_title, "status": "testée", "experiment_key": k}, upsert=False)
        s.execute("update foot_hypotheses set status='testée', experiment_key=? where title=?", (k, a.hyp_title))
        s.outbox.append(f"update foot_hypotheses set status='testée', experiment_key={s.pg_literal(k)} "
                        f"where title={s.pg_literal(a.hyp_title)};")
    print(k)
    s.flush_outbox(OUTBOX)


def cmd_lesson(a):
    from .memory import add_lesson
    s = store()
    add_lesson(s, a.error, a.rule, a.ref or "")
    s.flush_outbox(OUTBOX)


def cmd_dump_queries(a):
    for t, q in dump_queries().items():
        print(f"-- {t}\n{q}")


def cmd_outbox(a):
    if OUTBOX.exists():
        print(OUTBOX.read_text(encoding="utf-8"))
        if a.clear:
            OUTBOX.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(prog="foot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit").set_defaults(f=cmd_audit)
    h = sub.add_parser("history"); h.add_argument("--refresh", action="store_true"); h.set_defaults(f=cmd_history)
    t = sub.add_parser("train"); t.add_argument("--rebuild", action="store_true"); t.set_defaults(f=cmd_train)
    r1 = sub.add_parser("r1"); r1.add_argument("--day"); r1.add_argument("--fixtures"); r1.set_defaults(f=cmd_r1)
    r2 = sub.add_parser("r2"); r2.add_argument("--news"); r2.set_defaults(f=cmd_r2)
    sub.add_parser("r3").set_defaults(f=cmd_r3)
    r4 = sub.add_parser("r4"); r4.add_argument("--day"); r4.set_defaults(f=cmd_r4)
    r6 = sub.add_parser("r6"); r6.add_argument("--day"); r6.set_defaults(f=cmd_r6)
    sl = sub.add_parser("state-load"); sl.add_argument("dir"); sl.set_defaults(f=cmd_state_load)
    sub.add_parser("dump-queries").set_defaults(f=cmd_dump_queries)
    slj = sub.add_parser("state-load-json"); slj.add_argument("file"); slj.set_defaults(f=cmd_state_load_json)
    sq = sub.add_parser("state-query"); sq.add_argument("--days", type=int, default=120); sq.set_defaults(f=cmd_state_query)
    g = sub.add_parser("gate"); g.add_argument("routine"); g.set_defaults(f=cmd_gate)
    ls = sub.add_parser("lock-sql"); ls.add_argument("action", choices=["acquire", "release"])
    ls.add_argument("holder"); ls.set_defaults(f=cmd_lock_sql)
    nr = sub.add_parser("not-run"); nr.add_argument("routine"); nr.add_argument("reason"); nr.set_defaults(f=cmd_not_run)
    r5 = sub.add_parser("r5"); r5.add_argument("--deep", action="store_true"); r5.set_defaults(f=cmd_r5)
    ec = sub.add_parser("exp-check"); ec.add_argument("--hypothesis", required=True)
    ec.add_argument("--protocol", required=True); ec.add_argument("--reason"); ec.set_defaults(f=cmd_exp_check)
    er = sub.add_parser("exp-record")
    for k in ["hypothesis", "protocol", "result", "conclusion"]:
        er.add_argument(f"--{k}", required=True)
    for k in ["data", "period", "model", "reason", "hyp-title"]:
        er.add_argument(f"--{k}", default="" if k in ("data", "period", "model") else None)
    er.add_argument("--ci-low", type=float); er.add_argument("--ci-high", type=float); er.set_defaults(f=cmd_exp_record)
    le = sub.add_parser("lesson"); le.add_argument("--error", required=True); le.add_argument("--rule", required=True)
    le.add_argument("--ref"); le.set_defaults(f=cmd_lesson)
    ob = sub.add_parser("outbox"); ob.add_argument("--clear", action="store_true"); ob.set_defaults(f=cmd_outbox)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
