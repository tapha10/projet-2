"""Mémoire : expériences (jamais relancées à l'identique), leçons, hypothèses, journal des routines."""
from __future__ import annotations

import json

from .db import Store, now_utc, payload_hash

CONCLUSIONS = ("confirmé", "infirmé", "inconclusif", "en cours")


def experiment_key(hypothesis: str, protocol: dict) -> str:
    """Clé d'un test = empreinte de l'hypothèse + du protocole (données, période, modèle, paramètres)."""
    return payload_hash({"h": hypothesis.strip().lower(), "p": protocol})[:24]


def find_experiment(store: Store, key: str):
    rows = store.query("select * from foot_experiments where exp_key = ?", (key,))
    return rows[0] if rows else None


def should_run(store: Store, hypothesis: str, protocol: dict, data_changed_reason: str | None = None):
    """(lancer?, clé, motif). Un test identique déjà enregistré n'est pas relancé, sauf si les données
    ont grandement changé — et alors le motif est obligatoire et enregistré."""
    key = experiment_key(hypothesis, protocol)
    prev = find_experiment(store, key)
    if prev is None:
        return True, key, "nouveau test"
    if data_changed_reason:
        return True, key, f"relance justifiée : {data_changed_reason}"
    return False, key, f"déjà testé le {prev['created_at']} : {prev['conclusion']}"


def record_experiment(store: Store, hypothesis, protocol, result: dict, conclusion: str,
                      data_desc="", period="", model="", ci=(None, None), rerun_reason=None):
    assert conclusion in CONCLUSIONS, conclusion
    key = experiment_key(hypothesis, protocol)
    if rerun_reason and find_experiment(store, key):
        key_db = f"{key}-r{now_utc().strftime('%Y%m%d%H%M')}"
        rerun_of = key
    else:
        key_db, rerun_of = key, None
    store.insert("foot_experiments", {
        "exp_key": key_db, "hypothesis": hypothesis, "protocol": protocol, "data_desc": data_desc,
        "period": period, "model": model, "result": result, "ci_low": ci[0], "ci_high": ci[1],
        "conclusion": conclusion, "rerun_of": rerun_of, "rerun_reason": rerun_reason,
        "created_at": now_utc()})
    return key_db


def add_lesson(store: Store, error: str, rule: str, source_ref: str = ""):
    exists = store.query("select id from foot_lessons where rule = ?", (rule,))
    if not exists:
        store.insert("foot_lessons", {"error": error, "rule": rule, "source_ref": source_ref,
                                      "active": 1, "created_at": now_utc()})


def add_hypothesis(store: Store, title, description, priority=3):
    store.insert("foot_hypotheses", {"title": title, "description": description, "priority": priority,
                                     "status": "à tester", "created_at": now_utc()})


def next_hypothesis(store: Store):
    rows = store.query("select * from foot_hypotheses where status='à tester' order by priority, id limit 1")
    return rows[0] if rows else None


class RoutineRun:
    """Journal + verrou : `with RoutineRun(store, 'R1') as run: ...`"""

    def __init__(self, store: Store, routine: str, run_day=None, dry=False):
        self.store, self.routine, self.run_day, self.dry = store, routine, run_day, dry
        self.read, self.changed, self.why, self.details = {}, {}, "", ""
        self.holder = f"{routine}-{now_utc().timestamp():.0f}"
        self.started = now_utc()

    def __enter__(self):
        if not self.store.acquire_lock("foot_routines", self.holder):
            self._log("non exécutée", "verrou occupé par une autre routine")
            raise RuntimeError("verrou occupé")
        return self

    def _log(self, status, details=""):
        self.store.insert("foot_iteration_log", {
            "routine": self.routine, "run_day": str(self.run_day) if self.run_day else None,
            "started_at": self.started, "finished_at": now_utc(), "status": status,
            "read_summary": self.read, "changed_summary": self.changed, "why": self.why,
            "details": details or self.details})

    def __exit__(self, et, ev, tb):
        status = "échec" if et else ("sec" if self.dry else "succès")
        self._log(status, f"{et.__name__}: {ev}" if et else self.details)
        self.store.release_lock("foot_routines", self.holder)
        return False


def last_status(store: Store, routine: str):
    rows = store.query("select status, finished_at from foot_iteration_log where routine=? "
                       "order by id desc limit 1", (routine,))
    return rows[0] if rows else None
