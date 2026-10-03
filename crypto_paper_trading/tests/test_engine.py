"""Tests hors réseau : python -m unittest discover -s tests (depuis crypto_paper_trading/)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import cli, indicators, risk, simulate, stats  # noqa: E402
from engine.sqlgen import load_json_loose, q, qarr  # noqa: E402

A = {"stop": {"type": "fixed_pct", "pct": 0.25}, "tp": {"type": "fixed_pct", "pct": 0.40},
     "max_leverage": 2, "max_hold_days": 10, "breakeven_trigger_pct": None, "trailing": None}
B = {"stop": {"type": "fixed_pct", "pct": 0.12}, "tp": {"type": "fixed_pct", "pct": 0.40},
     "max_leverage": 10, "max_hold_days": 10, "breakeven_trigger_pct": 0.15, "trailing": None}
C = {"stop": {"type": "atr", "mult": 1.5, "period": 14, "min_pct": 0.10, "max_pct": 0.25},
     "tp": {"type": "r_multiple", "r": 2.5}, "max_leverage": 10, "max_hold_days": 10,
     "breakeven_trigger_pct": None, "trailing": {"activate_pct": 0.20, "distance": "stop_distance"}}
CFG = {"risk_pct": 0.01, "max_leverage": 10, "maintenance_margin_rate": 0.01, "liquidation_buffer_pct": 0.02}


def k(t, o, h, l, c):
    return dict(t=t, o=o, h=h, l=l, c=c, vq=1.0)


class TestRisk(unittest.TestCase):
    def test_arm_a(self):
        p = risk.plan_position(A, 100.0, 1000.0, CFG)
        self.assertAlmostEqual(p["stop_price"], 75.0)
        self.assertAlmostEqual(p["tp_price"], 140.0)
        self.assertAlmostEqual(p["risk_usd"], 10.0, places=2)       # 1 % de 1000
        self.assertLessEqual(p["leverage"], 2)
        self.assertLess(p["liquidation_price"], p["stop_price"])   # liquidation sous le stop

    def test_arm_b(self):
        p = risk.plan_position(B, 100.0, 1000.0, CFG)
        self.assertAlmostEqual(p["stop_price"], 88.0)
        self.assertAlmostEqual(p["breakeven_trigger_price"], 115.0)
        self.assertAlmostEqual(p["size_usd"], 83.33, places=2)
        self.assertLess(p["liquidation_price"], p["stop_price"])

    def test_arm_c_bounds(self):
        low = risk.plan_position(C, 100.0, 1000.0, CFG, atr_value=2.0)    # 3 % -> borné à 10 %
        high = risk.plan_position(C, 100.0, 1000.0, CFG, atr_value=30.0)  # 45 % -> borné à 25 %
        mid = risk.plan_position(C, 100.0, 1000.0, CFG, atr_value=10.0)   # 15 %
        self.assertAlmostEqual(low["stop_dist"], 0.10)
        self.assertAlmostEqual(high["stop_dist"], 0.25)
        self.assertAlmostEqual(mid["stop_dist"], 0.15)
        self.assertAlmostEqual(mid["tp_dist"], 0.375)
        self.assertLess(mid["liquidation_price"], mid["stop_price"])

    def test_hard_limits_cannot_be_loosened(self):
        p = risk.plan_position(B, 100.0, 1000.0, dict(CFG, risk_pct=0.5, max_leverage=50))
        self.assertLessEqual(p["risk_usd"], 10.0001)
        self.assertLessEqual(p["leverage"], 10)

    def test_breakeven_winrates(self):
        rr, be = risk.breakeven_winrate(A)
        self.assertAlmostEqual(rr, 1.6)
        self.assertAlmostEqual(be, 0.3846, places=3)
        rr, be = risk.breakeven_winrate(B)
        self.assertAlmostEqual(round(rr, 1), 3.3)
        self.assertAlmostEqual(be, 0.2308, places=3)


class TestSimulate(unittest.TestCase):
    def ps(self, params, entry=100.0, atr=None):
        plan = risk.plan_position(params, entry, 1000.0, CFG, atr)
        return simulate.PosState(entry=entry, size_usd=plan["size_usd"], leverage=plan["leverage"],
                                 stop=plan["stop_price"], initial_stop=plan["stop_price"], tp=plan["tp_price"],
                                 opened_ts=0, max_hold_ts=10 * 86400,
                                 be_trigger=plan["breakeven_trigger_price"], trailing_pct=plan["trailing_pct"],
                                 trailing_activate=plan["trailing_activate_price"],
                                 liquidation=plan["liquidation_price"])

    def test_stop_first_when_both_in_same_candle(self):
        ps = self.ps(A)
        r = simulate.step(ps, [k(0, 100, 150, 70, 120)])
        self.assertEqual(r["exit_reason"], "sl")
        self.assertAlmostEqual(r["exit_price"], 75.0)

    def test_tp(self):
        ps = self.ps(A)
        r = simulate.step(ps, [k(0, 100, 110, 95, 105), k(900, 105, 141, 100, 139)])
        self.assertEqual(r["exit_reason"], "tp")
        self.assertAlmostEqual(r["exit_price"], 140.0)

    def test_gap_below_stop_fills_at_open(self):
        ps = self.ps(B)
        r = simulate.step(ps, [k(0, 80, 82, 78, 79)])
        self.assertAlmostEqual(r["exit_price"], 80.0)

    def test_breakeven_next_candle(self):
        ps = self.ps(B)
        self.assertIsNone(simulate.step(ps, [k(0, 100, 116, 99, 112)]))
        self.assertEqual(ps.stop, 100.0)
        r = simulate.step(ps, [k(900, 112, 113, 99, 100)])
        self.assertEqual(r["exit_reason"], "breakeven")
        self.assertAlmostEqual(r["exit_price"], 100.0)

    def test_trailing(self):
        ps = self.ps(C, atr=10.0)  # stop 15 %, objectif +37,5 %, suiveur après +20 %
        self.assertIsNone(simulate.step(ps, [k(0, 100, 130, 99, 128)]))
        self.assertAlmostEqual(ps.stop, 130 * 0.85)
        r = simulate.step(ps, [k(900, 128, 129, 110, 111)])
        self.assertEqual(r["exit_reason"], "trailing")
        self.assertAlmostEqual(r["exit_price"], 110.5)

    def test_time_exit(self):
        ps = self.ps(A)
        cs = [k(t, 100, 101, 99, 100) for t in range(0, 11 * 86400, 900)]
        r = simulate.step(ps, cs)
        self.assertEqual(r["exit_reason"], "time")
        self.assertLessEqual(r["exit_ts"], 10 * 86400 + 900)

    def test_pre_entry_candle_ignored(self):
        ps = self.ps(A)
        ps.opened_ts = 1000
        self.assertIsNone(simulate.step(ps, [k(900 - 900, 100, 101, 10, 100)]))

    def test_pnl_and_r(self):
        ps = self.ps(A)
        r = simulate.pnl(ps, 75.0, 3600, "sl", 0.0005, 0.0)
        self.assertAlmostEqual(r["r_multiple"], -1.0 - r["fees_usd"] / 10.0, places=3)
        r = simulate.pnl(ps, 140.0, 3600, "tp", 0.0, 0.0)
        self.assertAlmostEqual(r["r_multiple"], 1.6, places=3)


class TestStats(unittest.TestCase):
    def test_metrics(self):
        tr = [dict(pnl_usd=16, r_multiple=1.6, opened_at=0, closed_at=86400, mfe_pct=0.4, mae_pct=-0.05),
              dict(pnl_usd=-10, r_multiple=-1, opened_at=0, closed_at=2 * 86400, mfe_pct=0.05, mae_pct=-0.25)]
        m = stats.metrics(tr, 1000)
        self.assertEqual(m["n"], 2)
        self.assertAlmostEqual(m["win_rate"], 0.5)
        self.assertAlmostEqual(m["avg_r"], 0.3)
        self.assertAlmostEqual(m["profit_factor"], 1.6)
        self.assertAlmostEqual(m["avg_duration_days"], 1.5)

    def test_bootstrap(self):
        ci = stats.bootstrap_mean_ci([0.5] * 20 + [0.6] * 20)
        self.assertGreater(ci["lo"], 0)
        ci = stats.bootstrap_mean_ci([1, -1] * 10)
        self.assertLess(ci["lo"], 0)
        self.assertGreater(ci["hi"], 0)

    def test_walk_forward(self):
        tr, te = stats.walk_forward_split(list(range(10)), key=lambda x: x)
        self.assertEqual(tr, list(range(7)))
        self.assertEqual(te, [7, 8, 9])


class TestIndicators(unittest.TestCase):
    def test_atr_constant_range(self):
        d = [k(i, 100, 105, 95, 100) for i in range(20)]
        self.assertAlmostEqual(indicators.atr(d), 10.0)

    def test_volume(self):
        d = [dict(vq=10.0) for _ in range(14)] + [dict(vq=25.0)]
        self.assertAlmostEqual(indicators.volume_ratio(d), 2.5)
        self.assertTrue(indicators.volume_doubling([dict(vq=1), dict(vq=2), dict(vq=4)]))
        self.assertFalse(indicators.volume_doubling([dict(vq=1), dict(vq=2), dict(vq=3)]))


class TestDecide(unittest.TestCase):
    rules = {"min_score_enter": 3.0, "signal_candle_max_change": 0.15, "unlock_max_supply_pct": 0.005,
             "wait_min_days": 1, "wait_max_days": 2, "vol_ratio_min": 2.0, "max_drop_from_signal_close": 0.15}
    w = {"dated_announcement": 2.0, "volume_doubling": 1.5, "alert_team_transfer": -3.0, "top_gainer_24h": 0.5}

    def test_signal_candle_is_wait(self):
        c = dict(pair="XUSDT", change_24h=0.30, market_signal_types=["volume_doubling", "top_gainer_24h"],
                 market_alerts=[], news=[{"type": "dated_announcement"}], alerts=[])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "wait")

    def test_team_transfer_skip(self):
        c = dict(pair="XUSDT", change_24h=0.05, market_signal_types=["volume_doubling"], market_alerts=[],
                 news=[{"type": "dated_announcement"}], alerts=["alert_team_transfer"])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "skip")

    def test_enter(self):
        c = dict(pair="XUSDT", change_24h=0.05, market_signal_types=["volume_doubling"], market_alerts=[],
                 news=[{"type": "dated_announcement"}], alerts=[])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "enter")

    def test_wait_reevaluation(self):
        base = dict(age_days=1.0, vol_ratio_vs_pre_signal=2.5, drop_from_signal_close=-0.05, change_24h=0.02)
        self.assertEqual(cli.decide_wait(dict(base), self.rules)[1], "enter")
        self.assertEqual(cli.decide_wait(dict(base, drop_from_signal_close=-0.2), self.rules)[1], "wait")
        self.assertEqual(cli.decide_wait(dict(base, drop_from_signal_close=-0.2, age_days=2.0), self.rules)[1], "skip")
        self.assertEqual(cli.decide_wait(dict(base, unlock_supply_pct_7d=0.02), self.rules)[1], "skip")
        self.assertIsNone(cli.decide_wait(dict(base, age_days=0.3), self.rules)[1])


class TestSql(unittest.TestCase):
    def test_quoting(self):
        self.assertEqual(q("l'équipe"), "'l''équipe'")
        self.assertEqual(q(None), "null")
        self.assertEqual(qarr(["a", "b'c"]), "array['a','b''c']::text[]")

    def test_load_loose(self):
        payload = 'Below is <untrusted-data-x>\n[{"paper_state":{"a":1}}]\n</untrusted-data-x>'
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            f.write(payload)
        self.assertEqual(load_json_loose(f.name), {"a": 1})
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            json.dump({"result": payload}, f)
        self.assertEqual(load_json_loose(f.name), {"a": 1})


if __name__ == "__main__":
    unittest.main()
