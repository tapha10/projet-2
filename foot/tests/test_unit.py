"""Tests unitaires (section 12)."""
import math

import numpy as np
import pandas as pd
import pytest

from foot import load_config
from foot.odds import remove_margin, combo_odds, combo_breakeven, breakeven_prob, overround, expected_value
from foot.settle import settle_side, settle_combo
from foot.selection import is_national_league, evaluate_match, build_combo, combo_summary, same_referee
from foot.features import eligible_played
from foot.stats import wilson, brier, log_loss, benjamini_hochberg, expected_longest_losing_streak
from foot.models import p_over_from_lambdas, m0_prob, m4_weights, m4_combine

CFG = load_config()


# ---- retrait de la marge
def test_remove_margin_proportional():
    p = remove_margin([1.90, 1.90])
    assert p == pytest.approx([0.5, 0.5])
    p = remove_margin([1.80, 2.10])
    assert sum(p) == pytest.approx(1.0)
    assert p[0] == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 2.1))


def test_remove_margin_power_sums_to_one_and_shrinks_longshot():
    prop = remove_margin([1.30, 3.60]); power = remove_margin([1.30, 3.60], "power")
    assert sum(power) == pytest.approx(1.0, abs=1e-9)
    assert power[1] < prop[1]  # le pari risqué perd un peu plus de marge


def test_overround_and_invalid():
    assert overround([1.9, 1.9]) == pytest.approx(2 / 1.9 - 1)
    with pytest.raises(ValueError):
        remove_margin([1.0, 2.0])


# ---- combiné et seuil d'équilibre
def test_combo_odds_and_breakeven():
    o = [1.70] * 5
    assert combo_odds(o) == pytest.approx(1.7 ** 5)
    assert combo_odds(o) == pytest.approx(14.199, abs=1e-3)
    assert combo_breakeven(o) == pytest.approx(0.0704, abs=1e-4)
    assert breakeven_prob(1.70) == pytest.approx(0.588, abs=1e-3)
    assert 0.6 ** 5 == pytest.approx(0.0778, abs=1e-4)
    assert 0.7 ** 5 == pytest.approx(0.168, abs=1e-3)
    assert expected_value(0.6, 1.7) == pytest.approx(0.02)


# ---- règlement
@pytest.mark.parametrize("hg,ag,side,exp", [
    (1, 1, "under", "win"), (2, 0, "over", "loss"), (2, 1, "over", "win"), (3, 0, "under", "loss"),
    (0, 0, "under", "win"), (4, 3, "over", "win")])
def test_settle(hg, ag, side, exp):
    assert settle_side(side, hg, ag) == exp


def test_settle_void_and_regular_time_only():
    assert settle_side("over", None, None, "POSTPONED") == "void"
    with pytest.raises(ValueError):
        settle_side("over", None, None, "FT")
    # la fonction reçoit les buts du temps réglementaire : 1-1 après 90 min = moins, même si 2-1 a.p.
    assert settle_side("under", 1, 1) == "win"


def test_settle_combo():
    assert settle_combo(["win", "win"], [1.8, 1.9]) == ("win", pytest.approx(3.42))
    assert settle_combo(["win", "loss"], [1.8, 1.9])[0] == "loss"
    out, pay = settle_combo(["win", "void", "win"], [1.8, 2.0, 1.9])
    assert out == "win" and pay == pytest.approx(1.8 * 1.9)
    assert settle_combo(["void"], [2.0]) == ("void", 1.0)


# ---- filtres
def test_national_league_filter():
    assert is_national_league("E0", CFG)
    assert not is_national_league("CL", CFG)
    assert not is_national_league("E0", CFG, "FA Cup")
    assert not is_national_league("F1", CFG, "Coupe de France")
    assert not is_national_league("USA", CFG)  # pas de cote plus/moins disponible


def test_min_matches_filter_strict_and_at_least():
    row = {"h_played_season": 6, "a_played_season": 6}
    assert eligible_played(row, 5, "strict")
    row = {"h_played_season": 5, "a_played_season": 9}
    assert not eligible_played(row, 5, "strict")
    assert eligible_played(row, 5, "au_moins")
    assert not eligible_played({"h_played_season": np.nan, "a_played_season": 9})


def _row(**kw):
    base = {"match_id": "m1", "league": "E0", "h_played_season": 8, "a_played_season": 8,
            "o_over_avg": 1.80, "o_under_avg": 2.05, "o_over_b365": np.nan, "o_under_b365": np.nan}
    base.update(kw)
    return base


def test_min_odds_filter():
    e = evaluate_match(_row(), 0.62, CFG)            # plus à 1,80, p=0,62 -> EV = 0,116
    assert e["retenu"] and e["side"] == "over"
    e = evaluate_match(_row(o_over_avg=1.65), 0.70, CFG)
    assert not e["retenu"] and "cote" in e["motif"]  # côté le plus probable sous 1,70 : écarté, pas forcé
    e = evaluate_match(_row(o_over_avg=1.70), 0.70, CFG)
    assert e["retenu"]                                # 1,70 exactement : accepté


def test_value_threshold():
    e = evaluate_match(_row(), 0.52, CFG)            # 0,52*1,80-1 = -0,064
    assert not e["retenu"] and "valeur" in e["motif"]


def test_odds_fallback_b365():
    e = evaluate_match(_row(o_over_avg=np.nan, o_over_b365=1.9), 0.6, CFG)
    assert e["retenu"] and e["odds_src"] == "b365"


# ---- construction du combiné
def _sel(i, ev, p=0.6, odds=1.8, mid=None, ref=None):
    return {"match_id": mid or f"m{i}", "ev": ev, "p": p, "odds": odds, "retenu": True, "referee": ref}


def test_build_combo_five_unique():
    sels = [_sel(i, ev=i / 100) for i in range(8)] + [_sel(99, ev=0.5, mid="m7")]
    legs, notes = build_combo(sels, 5)
    assert len(legs) == 5
    assert len({l["match_id"] for l in legs}) == 5
    assert legs[0]["match_id"] == "m7"


def test_build_combo_short_when_insufficient():
    legs, notes = build_combo([_sel(1, 0.1), _sel(2, 0.05)], 5)
    assert len(legs) == 2 and any("seulement 2" in n for n in notes)


def test_build_combo_notes_shared_referee():
    legs, notes = build_combo([_sel(1, 0.1, ref="X"), _sel(2, 0.05, ref="X")], 5, conflicts=same_referee)
    assert any("même arbitre" in n for n in notes)


def test_combo_summary():
    s = combo_summary([_sel(i, 0.1, p=0.6, odds=1.7) for i in range(5)])
    assert s["cote"] == pytest.approx(14.199, abs=1e-3)
    assert s["p_estimee"] == pytest.approx(0.07776)
    assert s["seuil_equilibre"] == pytest.approx(1 / 14.19857, abs=1e-5)


# ---- Wilson
def test_wilson():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(10, 10)
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)


# ---- métriques
def test_brier_logloss():
    assert brier([1, 0], [1, 0]) == 0
    assert brier([0.5, 0.5], [1, 0]) == 0.25
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))
    assert log_loss([0.9], [1]) == pytest.approx(-math.log(0.9))


def test_bh_and_streak():
    sig = benjamini_hochberg([0.001, 0.2, 0.03, 0.04], 0.05)
    assert sig.tolist() == [True, False, False, False]
    assert expected_longest_losing_streak(100, 0.07) > 20


# ---- modèles
def test_poisson_over_probability():
    p = p_over_from_lambdas(1.5, 1.2)[0]
    from scipy.stats import poisson
    lam = 2.7
    exact = 1 - sum(poisson.pmf(k, lam) for k in range(3))
    assert p == pytest.approx(exact, abs=1e-6)  # rho=0 : somme de Poisson indépendants


def test_m0_and_m4():
    assert m0_prob(1.9, 1.9) == pytest.approx(0.5)
    assert np.isnan(m0_prob(np.nan, 1.9))
    w = m4_weights({"a": 0.68, "b": 0.69, "c": np.nan})
    assert set(w) == {"a", "b"} and w["a"] > w["b"]
    assert m4_combine({"a": 0.6, "b": 0.6}, w) == pytest.approx(0.6)
