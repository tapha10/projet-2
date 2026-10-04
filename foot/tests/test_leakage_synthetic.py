"""Absence de fuite (section 12) et données synthétiques."""
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from foot import ROOT, load_config
from foot.db import Store, payload_hash
from foot.decision import screen_features, sample_status, edge_verdict, should_switch
from foot.features import match_features
from foot.models import m1_walkforward

CFG = load_config()


def synthetic_league(n_teams=12, rounds=4, seed=1, start="2024-08-01"):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    att = rng.normal(0, 0.25, n_teams); dfn = rng.normal(0, 0.25, n_teams)
    rows, d = [], pd.Timestamp(start)
    for r in range(rounds * (n_teams - 1)):
        perm = rng.permutation(n_teams)
        for k in range(0, n_teams, 2):
            i, j = perm[k], perm[k + 1]
            lh = np.exp(0.3 + att[i] - dfn[j]); la = np.exp(0.05 + att[j] - dfn[i])
            rows.append({"league": "E0", "season": "2425", "date": d, "home": teams[i], "away": teams[j],
                         "fthg": rng.poisson(lh), "ftag": rng.poisson(la)})
        d += pd.Timedelta(days=7)
    df = pd.DataFrame(rows)
    df["kickoff"] = df.date.dt.tz_localize("Europe/London") + pd.Timedelta(hours=15)
    df["match_id"] = [f"m{i}" for i in range(len(df))]
    for c in ["hxg", "axg", "hs", "as_", "o_over_avg", "o_under_avg", "c_over_avg", "c_under_avg"]:
        df[c] = np.nan
    df["referee"] = None
    return df


# ---------------------------------------------------------------- fuite
def test_features_ignore_future():
    df = synthetic_league()
    cut = df.date.sort_values().iloc[len(df) // 2]
    f1 = match_features(df)
    df2 = df.copy()
    df2.loc[df2.date >= cut, ["fthg", "ftag"]] = [9, 9]  # on change radicalement le futur
    f2 = match_features(df2)
    cols = [c for c in f1.columns if c.startswith(("h_", "a_"))]
    past = f1.date <= cut  # jour de coupure inclus : ses propres variables n'utilisent que la veille
    pd.testing.assert_frame_equal(f1.loc[past, cols].reset_index(drop=True),
                                  f2.loc[past, cols].reset_index(drop=True))


def test_m1_ignores_same_day_and_future():
    df = synthetic_league(rounds=6)
    d = df.date.sort_values().unique()[-5]
    targets = df[df.date == d]
    p1 = m1_walkforward(df, targets, CFG)
    df2 = df.copy()
    df2.loc[df2.date >= d, ["fthg", "ftag"]] = [7, 0]
    p2 = m1_walkforward(df2, targets, CFG)
    assert len(p1) == len(targets)
    np.testing.assert_allclose(p1.p_m1.to_numpy(), p2.p_m1.to_numpy())


def _pred_row(locked, kickoff):
    body = {"match_id": "x", "model": "M1", "model_version": "M1-v1", "variant": "principal", "side": "over",
            "prob": 0.6, "odds": 1.8, "selected": 1, "phase": "2", "counted": 0,
            "kickoff": kickoff.isoformat(), "locked_at": locked.isoformat()}
    return {"id": "p1", **body, "payload_hash": payload_hash(body)}


def test_locked_prediction_cannot_be_modified():
    s = Store()
    s.insert("foot_matches", {"match_id": "x", "league": "E0", "home": "A", "away": "B"})
    now = datetime(2026, 10, 4, 9, tzinfo=timezone.utc)
    s.insert("foot_predictions", _pred_row(now, now + timedelta(hours=5)))
    with pytest.raises(sqlite3.IntegrityError):
        s.execute("update foot_predictions set side='under' where id='p1'")
    with pytest.raises(sqlite3.IntegrityError):
        s.execute("delete from foot_predictions where id='p1'")
    r = s.query("select * from foot_predictions where id='p1'")[0]
    body = {k: r[k] for k in ["match_id", "model", "model_version", "variant", "side", "prob", "odds",
                              "selected", "phase", "counted", "kickoff", "locked_at"]}
    assert payload_hash(body) == r["payload_hash"]  # empreinte vérifiable


def test_prediction_after_kickoff_refused():
    s = Store()
    s.insert("foot_matches", {"match_id": "x", "league": "E0", "home": "A", "away": "B"})
    now = datetime(2026, 10, 4, 15, tzinfo=timezone.utc)
    s.insert("foot_predictions", _pred_row(now, now - timedelta(minutes=1)))
    assert s.query("select count(*) n from foot_predictions")[0]["n"] == 0  # contrainte locked_at < kickoff


def test_postgres_migration_has_append_only_triggers_and_rls():
    sql = (ROOT / "migrations" / "001_foot_init.sql").read_text(encoding="utf-8")
    for t in ("foot_predictions", "foot_combos", "foot_combo_legs"):
        assert f"before update or delete on {t}" in sql
    assert "enable row level security" in sql
    assert "check (locked_at < kickoff)" in sql


# ---------------------------------------------------------------- synthétique
def _synthetic_signal(n=6000, seed=3, n_noise=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    base = rng.normal(size=n)
    y = (rng.random(n) < 1 / (1 + np.exp(-(0.1 + 0.6 * x + 0.3 * base)))).astype(int)
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=n, freq="h"), "signal": x,
                       "base": base, "y": y})
    for k in range(n_noise):
        df[f"bruit_{k}"] = rng.normal(size=n)
    return df


def test_real_signal_is_found():
    df = _synthetic_signal()
    out = screen_features(df, ["base"], ["signal"])
    assert out.loc[0, "retenue"] and out.loc[0, "gain_logloss"] > 0.01


def test_200_random_variables_not_retained():
    df = _synthetic_signal(n=4000, n_noise=200)
    out = screen_features(df, ["base"], [f"bruit_{k}" for k in range(200)])
    assert out.retenue.sum() <= 1  # contrôle du taux de fausses découvertes (BH 5 %)


def test_small_sample_inconclusive():
    assert sample_status(40, 30)["statut"] == "inconclusif"
    assert edge_verdict(40, 32, 0.55, 1, 3, ["M0", "M1"])[0] == "inconclusif"
    # même un taux énorme sur peu de matchs reste inconclusif
    assert edge_verdict(20, 20, 0.55, 1, 1, ["M1"])[0] == "inconclusif"
    ok, why = should_switch(np.full(100, 0.5), np.full(100, 0.6), np.ones(100))
    assert not ok and "300" in why


def test_edge_verdicts():
    assert edge_verdict(600, 400, 0.56, 3, 5, ["M0", "M1", "M2", "M3", "M4"])[0] == "avantage mesuré"
    assert edge_verdict(600, 300, 0.56, 3, 5, ["M0", "M1", "M2", "M3", "M4"])[0] == "aucun avantage mesuré"
    assert edge_verdict(600, 300, 0.56, 1, 5, ["M0", "M1", "M2", "M3", "M4"])[0] == "inconclusif"  # < 2 mois


def test_upcoming_match_gets_same_features_as_training():
    """Un match à venir reçoit les mêmes variables (dont l'enjeu) que s'il était dans l'historique."""
    df = synthetic_league(rounds=3)
    last_day = df.date.max()
    full = match_features(df)
    up = df.copy()
    up.loc[up.date == last_day, ["fthg", "ftag"]] = np.nan
    fut = match_features(up)
    cols = ["h_played_season", "a_played_season", "h_rest_days", "h_pts_before", "h_frac_season",
            "h_gap_top", "a_gap_releg", "h_ew_over", "a_ew_tot"]
    a = full.loc[full.date == last_day, cols].reset_index(drop=True)
    b = fut.loc[fut.date == last_day, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a.astype(float), b.astype(float), check_exact=False, atol=1e-9)
