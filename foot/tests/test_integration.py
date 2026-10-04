"""Tests d'intégration (section 12) : migrations, cycle complet, mémoire, reprise, sources."""
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from foot import ROOT, load_config
from foot.audit import run_audit, SOURCES
from foot.db import Store, dump_queries
from foot.memory import should_run, record_experiment, RoutineRun, last_status
from foot.replay import replay
from tests.test_leakage_synthetic import synthetic_league


def with_odds(df, seed=5):
    rng = np.random.default_rng(seed)
    p = np.clip(0.52 + rng.normal(0, 0.08, len(df)), 0.3, 0.75)
    m = 1.06
    df = df.copy()
    df["o_over_avg"] = 1 / (p * m); df["o_under_avg"] = 1 / ((1 - p) * m)
    df["c_over_avg"] = df.o_over_avg; df["c_under_avg"] = df.o_under_avg
    for c in ["o_over_b365", "o_under_b365", "o_over_max", "o_under_max", "c_over_b365", "c_under_b365",
              "hthg", "htag", "hst", "ast"]:
        df[c] = np.nan
    return df


def test_migrations_run_twice_without_loss(tmp_path):
    db = tmp_path / "f.sqlite"
    s = Store(db)
    s.insert("foot_matches", {"match_id": "a", "league": "E0", "home": "A", "away": "B"})
    s.insert("foot_lessons", {"error": "e", "rule": "r"})
    s2 = Store(db)  # rejoue toutes les migrations
    s2.migrate()
    assert s2.query("select count(*) n from foot_matches")[0]["n"] == 1
    assert s2.query("select count(*) n from foot_lessons")[0]["n"] == 1
    sql = (ROOT / "migrations" / "001_foot_init.sql").read_text(encoding="utf-8")
    assert sql.count("create table if not exists") == len(s2.tables())  # même schéma des deux côtés


def test_postgres_and_sqlite_schemas_match():
    import re
    sql = (ROOT / "migrations" / "001_foot_init.sql").read_text(encoding="utf-8")
    s = Store()
    for m in re.finditer(r"create table if not exists (\w+) \((.*?)\n\);", sql, re.S):
        t, body = m.group(1), m.group(2)
        pg_cols = [m2.group(1) for m2 in re.finditer(
            r"^\s*([a-z_]+)\s+(?:text|integer|numeric|boolean|jsonb|timestamptz|date|bigserial)\b", body, re.M)]
        assert pg_cols == s.columns(t), t


def test_full_cycle_dry_replay_14_days():
    df = with_odds(synthetic_league(n_teams=12, rounds=4, seed=2))
    cfg = dict(load_config()); cfg["modele_actif"] = "M1"; cfg["ligues"] = {"E0": "test"}
    days = sorted(df.date.unique())
    start = pd.Timestamp(days[-14]).date()
    # journées hebdomadaires : on rejoue 14 jours de calendrier contenant 2 journées
    store, reports, weekly = replay(df, start, 14, cfg=cfg)
    logs = store.query("select routine, status from foot_iteration_log")
    assert {l["routine"] for l in logs} >= {"R1", "R2", "R3", "R4", "R6"}
    assert all(l["status"] == "sec" for l in logs)
    assert store.query("select count(*) n from foot_predictions")[0]["n"] > 0
    assert store.query("select count(*) n from foot_results")[0]["n"] > 0
    assert len(reports) == 14 and "Simulation papier" in reports[0] and "Verdict" in weekly
    # aucune prédiction verrouillée après son coup d'envoi
    assert store.query("select count(*) n from foot_predictions where locked_at >= kickoff")[0]["n"] == 0


def test_memory_prevents_rerun():
    s = Store()
    proto = {"modele": "M3", "periode": "2324-2627"}
    go, key, _ = should_run(s, "M3 bat M0", proto)
    assert go
    record_experiment(s, "M3 bat M0", proto, {"p": 0.07}, "inconclusif")
    go, _, why = should_run(s, "M3 bat M0", proto)
    assert not go and "déjà testé" in why
    go, _, why = should_run(s, "  m3 BAT m0 ", proto)  # même test, écriture différente
    assert not go
    go, _, why = should_run(s, "M3 bat M0", proto, data_changed_reason="+5000 matchs avec xG")
    assert go and "justifiée" in why
    record_experiment(s, "M3 bat M0", proto, {"p": 0.01}, "confirmé", rerun_reason="+5000 matchs avec xG")
    rows = s.query("select rerun_of, rerun_reason from foot_experiments where rerun_of is not null")
    assert rows and rows[0]["rerun_reason"]


def test_restart_from_dump(tmp_path):
    """Reprise après coupure : l'état exporté de Supabase (JSON) reconstruit la base locale à l'identique."""
    s = Store()
    s.insert("foot_matches", {"match_id": "x", "league": "E0", "home": "A", "away": "B",
                              "kickoff": "2026-10-04T15:00:00+00:00"})
    s.insert("foot_predictions", {"id": "p", "match_id": "x", "model": "M3", "model_version": "M3-v1",
                                  "side": "over", "prob": 0.6, "odds": 1.8, "selected": 1, "phase": "2",
                                  "counted": 0, "kickoff": "2026-10-04T15:00:00+00:00",
                                  "locked_at": "2026-10-04T09:00:00+00:00", "payload_hash": "h"})
    s.insert("foot_lessons", {"error": "e", "rule": "r"})
    d = tmp_path / "dump"; d.mkdir()
    for t in dump_queries():
        rows = s.query(f"select * from {t}")
        (d / f"{t}.json").write_text(json.dumps([{"rows": rows}]), encoding="utf-8")
    s2 = Store()
    from foot.cli import cmd_state_load
    import foot.cli as cli
    cli.store = lambda: s2
    cmd_state_load(type("A", (), {"dir": str(d)}))
    assert s2.query("select payload_hash from foot_predictions")[0]["payload_hash"] == "h"
    assert s2.query("select count(*) n from foot_lessons")[0]["n"] == 1
    assert s2.outbox == []  # rien n'est renvoyé vers Supabase lors d'un rechargement
    assert (ROOT / "docs" / "memoire.md").exists()


def test_lock_prevents_concurrent_routines():
    s = Store()
    assert s.acquire_lock("foot_routines", "R1-a")
    with pytest.raises(RuntimeError):
        with RoutineRun(s, "R2"):
            pass
    assert last_status(s, "R2")["status"] == "non exécutée"
    s.release_lock("foot_routines", "R1-a")
    with RoutineRun(s, "R2"):
        pass
    assert last_status(s, "R2")["status"] == "succès"


def test_failed_routine_logged():
    s = Store()
    with pytest.raises(ValueError):
        with RoutineRun(s, "R3"):
            raise ValueError("source indisponible")
    assert last_status(s, "R3")["status"] == "échec"


def test_source_failures_handled():
    s = Store()

    def flaky(src, cfg):
        return (None, "timeout") if "understat" in src["url"] else (403, None) if "fbref" in src["url"] else (200, None)
    rows = run_audit(s, probe_fn=flaky)
    assert len(rows) == len(SOURCES)
    by = {r["source"]: r for r in rows}
    assert not by["Understat (xG)"]["accessible"] and "timeout" in by["Understat (xG)"]["notes"]
    assert not by["FBref (StatsBomb/Opta)"]["accessible"]
    key_rows = [r for r in rows if "clé absente" in r["notes"]]
    assert all(not r["accessible"] for r in key_rows)  # pas de clé = pas accessible, jamais simulé


def test_missing_source_data_stays_empty():
    """Une source qui échoue ne fausse pas les données : valeurs vides, pas d'invention."""
    from foot.data import normalize
    raw = pd.DataFrame({"Div": ["E0"], "Date": ["04/10/2026"], "Time": ["15:00"], "HomeTeam": ["A"],
                        "AwayTeam": ["B"], "Avg>2.5": ["-0.25"], "Avg<2.5": ["2.6"]})
    df = normalize(raw, "2627")
    assert pd.isna(df.loc[0, "o_over_avg"]) and pd.isna(df.loc[0, "fthg"])


def test_outbox_sql_replays_into_fresh_local_base():
    """Le journal SQL (syntaxe Postgres) se rejoue dans une base locale neuve : mode de repli sans Supabase."""
    s = Store()
    s.insert("foot_config", {"key": "date_jour1", "value": '"2026-10-05"'}, upsert=True)
    s.insert("foot_matches", {"match_id": "x", "league": "E0", "home": "A", "away": "B"})
    s.insert("foot_predictions", {"id": "p", "match_id": "x", "model": "M3", "model_version": "M3-v1",
                                  "side": "over", "prob": 0.6, "odds": 1.8, "selected": 1, "phase": "2",
                                  "counted": 0, "kickoff": "2026-10-05T15:00:00+00:00",
                                  "locked_at": "2026-10-05T08:00:00+00:00", "payload_hash": "h"})
    s.insert("foot_lessons", {"error": "e", "rule": "r", "active": 1})
    s.insert("foot_features", {"match_id": "x", "model_version": "all-v1", "computed_at": "2026-10-05T08:00:00+00:00",
                               "data_cutoff": "2026-10-05T07:30:00+00:00", "features": {"p_m0": 0.5}})
    sql = s.flush_outbox()
    s2 = Store()
    s2.con.executescript(sql + "\n" + sql)  # rejoué deux fois : aucune erreur, aucun doublon
    assert s2.query("select count(*) n from foot_predictions")[0]["n"] == 1
    assert s2.query("select count(*) n from foot_features")[0]["n"] == 1
    assert s2.query("select value from foot_config")[0]["value"] == '"2026-10-05"'
    assert s2.query("select selected, counted from foot_predictions")[0] == {"selected": 1, "counted": 0}
