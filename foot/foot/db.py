"""Stockage : base SQLite locale au même schéma que Supabase (traduit depuis la migration Postgres),
plus une « boîte d'envoi » de requêtes SQL Postgres à appliquer sur Supabase (via l'outil SQL / MCP).

Prédictions, combinés et jambes : ajout seulement (déclencheurs qui refusent UPDATE/DELETE),
avec empreinte SHA-256 de leur contenu pour prouver qu'ils n'ont pas été changés après coup.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ROOT

MIGRATIONS = ROOT / "migrations"
APPEND_ONLY = ("foot_predictions", "foot_combos", "foot_combo_legs", "foot_features")
SERIAL_TABLES = ("foot_source_audit", "foot_odds_snapshots", "foot_team_news", "foot_experiments",
                 "foot_lessons", "foot_error_analysis", "foot_hypotheses", "foot_iteration_log")
UPSERT = {"foot_config": "key", "foot_matches": "match_id", "foot_results": "match_id",
          "foot_combo_results": "combo_id", "foot_daily_reports": "day",
          "foot_weekly_reports": "week_start", "foot_model_versions": "version"}
# colonnes de conflit pour les tables à identifiant auto (dédoublonnage côté Supabase)
NATURAL_KEYS = {"foot_experiments": "exp_key", "foot_hypotheses": "title",
                "foot_error_analysis": "prediction_id",
                "foot_odds_snapshots": "match_id, side, line, source, captured_at"}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def payload_hash(d: dict) -> str:
    canon = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def pg_to_sqlite(sql: str) -> str:
    sql = sql.split("-- Prédictions et combinés")[0]
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = sql.replace("bigserial primary key", "integer primary key autoincrement")
    sql = re.sub(r"'\{\}'::jsonb", "'{}'", sql)
    for a, b in (("timestamptz", "text"), ("jsonb", "text"), ("boolean", "integer"),
                 ("numeric", "real"), ("default now()", "default CURRENT_TIMESTAMP"),
                 (" date ", " text "), ("default true", "default 1"), ("default false", "default 0")):
        sql = sql.replace(a, b)
    sql = re.sub(r"\bdate\b(?= not null| primary key|,)", "text", sql)
    return sql


class Store:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("pragma foreign_keys = on")
        self.outbox: list[str] = []
        self.migrate()

    # ------------------------------------------------------------ schéma
    def migrate(self):
        for f in sorted(MIGRATIONS.glob("*.sql")):
            self.con.executescript(pg_to_sqlite(f.read_text(encoding="utf-8")))
        for t in APPEND_ONLY:
            for op in ("update", "delete"):
                self.con.execute(
                    f"create trigger if not exists {t}_no_{op} before {op} on {t} "
                    f"begin select raise(abort, '{t} en ajout seulement'); end;")
        self.con.commit()

    def tables(self):
        return [r[0] for r in self.con.execute(
            "select name from sqlite_master where type='table' and name like 'foot_%' order by name")]

    def columns(self, table):
        return [r[1] for r in self.con.execute(f"pragma table_info({table})")]

    # ------------------------------------------------------------ écriture
    def insert(self, table, row: dict, upsert=False, sync=True):
        row = {k: (json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v)
               for k, v in row.items()}
        row = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in row.items()}
        cols = ", ".join(row); qs = ", ".join("?" for _ in row)
        if upsert and table in UPSERT:
            pk = UPSERT[table]
            upd = ", ".join(f"{c}=excluded.{c}" for c in row if c != pk)
            sql = f"insert into {table} ({cols}) values ({qs}) on conflict({pk}) do update set {upd}"
        else:
            sql = f"insert or ignore into {table} ({cols}) values ({qs})"
        cur = self.con.execute(sql, list(row.values()))
        self.con.commit()
        if sync:
            self.outbox.append(self.pg_insert(table, row, upsert))
        return cur.lastrowid

    def execute(self, sql, params=()):
        cur = self.con.execute(sql, params)
        self.con.commit()
        return cur

    def query(self, sql, params=()):
        return [dict(r) for r in self.con.execute(sql, params)]

    # ------------------------------------------------------------ Postgres (Supabase)
    @staticmethod
    def pg_literal(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            if v != v:  # NaN
                return "null"
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"

    def pg_insert(self, table, row: dict, upsert=False):
        row = dict(row)
        if table in SERIAL_TABLES:
            row.pop("id", None)
        bool_cols = {"accessible", "after_lock", "selected", "counted", "active"}
        vals = []
        for k, v in row.items():
            if k in bool_cols and v in (0, 1):
                v = bool(v)
            vals.append(self.pg_literal(v))
        cols = ", ".join(row)
        sql = f"insert into {table} ({cols}) values ({', '.join(vals)})"
        if upsert and table in UPSERT:
            pk = UPSERT[table]
            upd = ", ".join(f"{c}=excluded.{c}" for c in row if c != pk)
            sql += f" on conflict ({pk}) do update set {upd}" if upd else f" on conflict ({pk}) do nothing"
        elif table in NATURAL_KEYS:
            sql += f" on conflict ({NATURAL_KEYS[table]}) do nothing"
        elif table not in SERIAL_TABLES:
            sql += " on conflict do nothing"
        return sql + ";"

    def flush_outbox(self, path: Path | None = None):
        sql = "\n".join(self.outbox)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(sql + ("\n" if sql else ""))
        self.outbox = []
        return sql

    def load_dump(self, table, rows: list[dict]):
        """Recharge l'état exporté de Supabase (json_agg) dans la base locale, sans renvoi vers Supabase."""
        cols = set(self.columns(table))
        for r in rows or []:
            r = {k: v for k, v in r.items() if k in cols}
            if r:
                self.insert(table, r, upsert=table in UPSERT, sync=False)

    # ------------------------------------------------------------ verrou simple
    def acquire_lock(self, name, holder, minutes=50):
        now = now_utc()
        self.con.execute("delete from foot_locks where name=? and expires_at < ?", (name, iso(now)))
        try:
            self.con.execute("insert into foot_locks (name, holder, acquired_at, expires_at) values (?,?,?,?)",
                             (name, holder, iso(now), iso(now + timedelta(minutes=minutes))))
            self.con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def release_lock(self, name, holder):
        self.con.execute("delete from foot_locks where name=? and holder=?", (name, holder))
        self.con.commit()


DUMP_TABLES = ["foot_config", "foot_matches", "foot_features", "foot_model_versions", "foot_predictions", "foot_combos",
               "foot_combo_legs", "foot_results", "foot_combo_results", "foot_experiments",
               "foot_lessons", "foot_hypotheses", "foot_error_analysis", "foot_team_news",
               "foot_odds_snapshots", "foot_daily_reports", "foot_iteration_log"]


def dump_queries():
    """Requêtes à exécuter sur Supabase pour reconstruire l'état local (une par table)."""
    return {t: f"select coalesce(json_agg(t), '[]'::json) as rows from {t} t;" for t in DUMP_TABLES}


RECENT = {"foot_team_news": "captured_at", "foot_iteration_log": "started_at", "foot_daily_reports": "day"}


def state_query(days=120):
    """Une seule requête Supabase qui renvoie l'état utile aux routines : {table: [lignes]}."""
    parts = []
    for t in DUMP_TABLES:
        if t in ("foot_odds_snapshots", "foot_features"):
            continue
        where = f" where {RECENT[t]} >= now() - interval '{days} days'" if t in RECENT else ""
        parts.append(f"'{t}', (select coalesce(json_agg(x), '[]'::json) from {t} x{where})")
    parts.append("'foot_features', (select coalesce(json_agg(x), '[]'::json) from foot_features x "
                 f"where computed_at >= now() - interval '{days} days')")
    return "select json_build_object(" + ", ".join(parts) + ") as state;"


def lock_sql(action, holder, minutes=50):
    """Verrou partagé entre routines, sur Supabase (la base locale est propre à chaque session)."""
    h = holder.replace("'", "")
    if action == "acquire":
        return ("delete from foot_locks where name='foot_routines' and expires_at < now(); "
                f"insert into foot_locks (name, holder, expires_at) values ('foot_routines', '{h}', "
                f"now() + interval '{minutes} minutes') on conflict (name) do nothing returning holder;")
    return f"delete from foot_locks where name='foot_routines' and holder='{h}';"
