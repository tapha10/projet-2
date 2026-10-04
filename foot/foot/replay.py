"""Rejeu en mode sec du cycle complet (R1 -> R6) sur des journées passées, sans regard vers le futur.

Pour chaque jour J : historique = matchs avant J ; matchs du jour = matchs de J sans score ;
R1 verrouille à J 08:00 UTC ; R2 sans nouvelles ; R3 règle avec les scores de J ; R4 rapport ; R6 à la fin.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from . import load_config
from .db import Store
from .memory import RoutineRun
from .pipeline import analyse_errors, fit_learned, run_r1, run_r2, run_r3
from .report import daily_report, weekly_report


def replay(hist: pd.DataFrame, start: date, days: int, store: Store | None = None, cfg=None,
           base_full: pd.DataFrame | None = None, leagues=None):
    cfg = dict(cfg or load_config())
    store = store or Store()
    store.insert("foot_config", {"key": "date_jour1", "value": f'"{start.isoformat()}"'}, upsert=True)
    store.insert("foot_config", {"key": "date_activation", "value": f'"{start.isoformat()}"'}, upsert=True)
    learned = None
    if base_full is not None:
        past = base_full[base_full.date < pd.Timestamp(start)]
        learned = fit_learned(past)
        from .models import m4_weights
        from .stats import log_loss
        last = past[past.season == past.season.max()].dropna(subset=["y"])
        cfg["_m4_poids"] = m4_weights({m: log_loss(last.dropna(subset=[m])[m], last.dropna(subset=[m]).y)
                                       for m in ["p_m0", "p_m1", "p_m2", "p_m3"] if last[m].notna().sum() > 300})
    if leagues:
        hist = hist[hist.league.isin(leagues)]
    reports = []
    for k in range(days):
        d = start + timedelta(days=k)
        before = hist[hist.date < pd.Timestamp(d)]
        today = hist[hist.date == pd.Timestamp(d)]
        fx = today.copy()
        fx[["fthg", "ftag", "hthg", "htag", "hxg", "axg", "hs", "as_", "hst", "ast"]] = float("nan")
        fx[["c_over_avg", "c_under_avg", "c_over_b365", "c_under_b365"]] = float("nan")  # clôture inconnue
        lock = datetime.combine(d, time(8, 0), tzinfo=timezone.utc)
        captured = lock - timedelta(minutes=30)
        out = run_r1(store, before, fx, captured, d, cfg, now=lock, dry=True, learned=learned)
        run_r2(store, [], now=lock + timedelta(hours=4), dry=True)
        res = today[["match_id", "fthg", "ftag"]].assign(status="FT", source="replay")
        run_r3(store, res, now=datetime.combine(d + timedelta(days=1), time(5, 30), tzinfo=timezone.utc), dry=True)
        analyse_errors(store, d)
        with RoutineRun(store, "R4", d + timedelta(days=1), dry=True):
            reports.append(daily_report(store, d, None))
    with RoutineRun(store, "R6", start + timedelta(days=days - 1), dry=True):
        weekly = weekly_report(store, start + timedelta(days=days - 1))
    return store, reports, weekly
