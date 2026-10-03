"""Tests obligatoires de l'addendum 2ter (hors réseau).
python3 -m unittest tests.test_2ter -v   (depuis crypto_paper_trading/)"""
import json
import os
import random
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from engine import cli2ter, discovery, dryrun, features, tiers  # noqa: E402

DAY = 86400


def k(t, o, h, l, c, vq=1.0):
    return dict(t=t, o=o, h=h, l=l, c=c, vq=vq)


# ================================================================ UNITAIRES
class TestRiskExample(unittest.TestCase):
    def test_r_size_margin_liquidation(self):
        # 100 € de risque, stop 5 % : notionnel 2 000 € ; +30 % = 600 € = 6 R
        risk_eur, sd = 100.0, 0.05
        notional = risk_eur / sd
        self.assertAlmostEqual(notional, 2000.0)
        gain = notional * 0.30
        self.assertAlmostEqual(gain, 600.0)
        self.assertAlmostEqual(tiers.r_multiple(gain, risk_eur), 6.0)
        lev = tiers.leverage_for(sd)
        self.assertEqual(lev, 3)                              # plafond 3x
        self.assertAlmostEqual(notional / lev, 666.6667, places=3)  # marge
        liq = tiers.liquidation_price(100.0, lev)
        self.assertAlmostEqual(liq, 100 * (1 - 1 / 3 + 0.01))
        self.assertGreaterEqual(1 - liq / 100, 3 * sd)       # liquidation >= 3x le stop

    def test_plan_t_position(self):
        p = tiers.plan_t_position(100.0, 1000.0, 5.0, {})
        self.assertAlmostEqual(p["risk_usd"], 10.0, places=4)      # 1 % de 1 000
        self.assertLessEqual(p["size_usd"], 250.0)                  # <= 25 % du capital
        self.assertLessEqual(p["leverage"], 3)
        self.assertTrue(0.08 <= p["stop_dist"] <= 0.12)
        self.assertGreaterEqual(1 - p["liquidation_price"] / 100, 3 * p["stop_dist"])


class TestTranches(unittest.TestCase):
    def test_shares_sum_to_100(self):
        for st in ({}, {"P2": {"status": "unlocked", "risk_pct": 0.0025}},
                   {"P2": {"status": "unlocked", "risk_pct": 0.01}, "P3": {"status": "unlocked", "risk_pct": 0.005}}):
            for split in tiers.SPLITS.values():
                alloc = tiers.live_allocation(st, split)
                self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)
        self.assertEqual(tiers.live_allocation({}), {"A": 1.0, "B": 0.0, "C": 0.0})
        self.assertAlmostEqual(tiers.live_allocation({"P2": {"status": "unlocked", "risk_pct": 0.0025}})["B"], 0.075)

    def _pos(self):
        ts = {"P2": {"status": "unlocked", "risk_pct": 0.01}, "P3": {"status": "unlocked", "risk_pct": 0.01}}
        plan = tiers.plan_t_position(100.0, 1000.0, 6.0, ts)   # stop 9 %
        return tiers.new_pos(plan, 0)

    def test_stop_to_entry_after_A_and_sum(self):
        pos = self._pos()
        sd = pos["stop_dist"]
        a_target = 100 * (1 + 2.5 * sd)
        tiers.step_tranches(pos, [k(0, 100, a_target + 0.1, 99, a_target)], 0.0, 3600)
        self.assertEqual(pos["tranches"]["A"]["exit_reason"], "tp")
        tiers.step_tranches(pos, [k(3600, a_target, a_target, a_target - 1, a_target - 0.5)], 0.0, 3600)
        self.assertAlmostEqual(pos["stop_price"], 100.0)            # stop du solde à l'entrée
        self.assertAlmostEqual(pos["tranches"]["B"]["stop"], 100.0)
        tiers.step_tranches(pos, [k(7200, 101, 101, 99, 99.5)], 0.0, 3600)
        self.assertEqual(pos["tranches"]["B"]["exit_reason"], "breakeven")
        res = tiers.settle(pos, 0.0005, 0.0)
        self.assertAlmostEqual(sum(res["per_tranche"].values()), res["pnl_usd"], places=5)
        self.assertGreater(res["pnl_usd"], 0)                       # A gagnée, solde à l'équilibre

    def test_stop_first_same_candle(self):
        pos = self._pos()
        tiers.step_tranches(pos, [k(0, 100, 200, 50, 120)], 0.0, 3600)
        self.assertTrue(all(d["exit_reason"] == "sl" for d in pos["tranches"].values() if d["share"] > 0))


class TestNoLookahead(unittest.TestCase):
    def test_features_ignore_future_and_open_candles(self):
        rnd = random.Random(3)
        dec = 60 * DAY + 14 * 3600
        daily = [k(i * DAY, 1 + rnd.random(), 2.5, 0.5, 1 + rnd.random(), rnd.uniform(1, 5)) for i in range(60)]
        hourly = [k(dec - (72 - i) * 3600, 1.5, 1.6, 1.4, 1.5 + i / 1000) for i in range(72)]
        btc = [k(i * DAY, 100, 101, 99, 100 + i) for i in range(60)]
        f1 = features.compute_features(dec, daily, hourly, btc, None, 0.0001, {}, 0.1)
        future_d = daily + [k(60 * DAY, 9, 99, 0.1, 50, 1e9), k(61 * DAY, 50, 99, 0.1, 80, 1e9)]
        future_h = hourly + [k(dec, 9, 99, 0.1, 50), k(dec - 1800, 9, 99, 0.1, 50)]
        f2 = features.compute_features(dec, future_d, future_h, btc + [k(60 * DAY, 1, 1e6, 1, 1e6)], None, 0.0001, {}, 0.1)
        self.assertEqual(f1, f2)
        self.assertLessEqual(f1["last_closed_daily_ts"] + DAY, dec)
        self.assertLessEqual(f1["last_closed_hourly_ts"] + 3600, dec)


class TestEvents(unittest.TestCase):
    def test_cluster_10_days(self):
        rows = [dict(pair="A", ts=0), dict(pair="A", ts=5 * DAY), dict(pair="A", ts=9.9 * DAY),
                dict(pair="A", ts=10 * DAY), dict(pair="B", ts=1 * DAY)]
        ev = features.cluster_events(rows)
        self.assertEqual(len(ev), 3)
        self.assertEqual(len([e for e in ev if e["pair"] == "A"][0]["members"]), 3)


class TestMultipleTesting(unittest.TestCase):
    def test_bh(self):
        p = [0.01, 0.04, 0.03, 0.20]
        adj = discovery.benjamini_hochberg(p)
        # triées : 0,01 (rang 1), 0,03 (2), 0,04 (3), 0,20 (4) ; BH monotone depuis le bas
        self.assertAlmostEqual(adj[3], 0.20)                 # 0,20 x 4/4
        self.assertAlmostEqual(adj[1], 0.04 * 4 / 3)         # 0,0533
        self.assertAlmostEqual(adj[2], 0.04 * 4 / 3)         # min(0,03 x 4/2 = 0,06 ; 0,0533)
        self.assertAlmostEqual(adj[0], 0.04)                 # min(0,01 x 4/1 = 0,04 ; 0,0533)

    def _t(self, **kw):
        base = dict(n_with=40, lift=0.15, lo80=0.02, p_adj=0.05, valid_lift=0.05)
        base.update(kw)
        return base

    def test_retention_thresholds(self):
        self.assertTrue(discovery.retained(self._t()))
        self.assertFalse(discovery.retained(self._t(n_with=29)))
        self.assertFalse(discovery.retained(self._t(lift=0.099)))
        self.assertFalse(discovery.retained(self._t(lo80=0.0)))
        self.assertFalse(discovery.retained(self._t(p_adj=0.2)))
        self.assertFalse(discovery.retained(self._t(valid_lift=-0.01)))


class TestUnlockRules(unittest.TestCase):
    def ev(self, n, wins, r_win=6.0, r_loss=-1.0, slip_pen=0.05):
        out = []
        for i in range(n):
            w = i < wins
            r = r_win if w else r_loss
            out.append(dict(win=w, r=r, r_slip2=r - slip_pen))
        return out

    def test_39_events_not_enough(self):
        ok, det = tiers.evaluate_unlock("P2", self.ev(39, 20), {})
        self.assertFalse(ok)
        self.assertTrue(any("39" in r for r in det["reasons"]))

    def test_40_events_good(self):
        ok, det = tiers.evaluate_unlock("P2", self.ev(40, 20), {})
        self.assertTrue(ok, det)

    def test_exact_breakeven_rejected(self):
        n = 70
        wins = round(n * tiers.BREAKEVEN["P2"])            # 10/70 = 14,3 % = équilibre
        ok, det = tiers.evaluate_unlock("P2", self.ev(n, wins), {})
        self.assertFalse(ok)

    def test_slippage_x2_kills_expectancy(self):
        evs = self.ev(60, 30, r_win=1.0, r_loss=-1.0, slip_pen=0.5)    # espérance 0 -> -0,5 avec glissement x2
        ok, det = tiers.evaluate_unlock("P2", evs, {})
        self.assertFalse(ok)
        self.assertTrue(any("glissement" in r for r in det["reasons"]))

    def test_demote(self):
        bad = self.ev(40, 2)                                # 5 % < 14 %
        self.assertTrue(tiers.evaluate_demote("P2", bad)[0])
        self.assertFalse(tiers.evaluate_demote("P2", bad[:39])[0])     # 39 événements : pas assez
        self.assertFalse(tiers.evaluate_demote("P2", self.ev(40, 8))[0])

    def test_risk_ramp(self):
        self.assertEqual(tiers.next_risk_step(0.0025, 3.0, 15), 0.005)
        self.assertEqual(tiers.next_risk_step(0.0025, 2.9, 15), 0.0025)
        self.assertEqual(tiers.next_risk_step(0.0025, 3.0, 14), 0.0025)
        self.assertEqual(tiers.next_risk_step(0.005, 4, 20), 0.01)

    def test_labels(self):
        self.assertEqual(tiers.tier_label("P2", "shadow", 10), "inconclusif")
        self.assertEqual(tiers.tier_label("P2", "shadow", 120, best_hi=0.10), "impossible avec ces données")
        self.assertEqual(tiers.tier_label("P2", "shadow", 99, best_hi=0.10), "ombre")
        self.assertEqual(tiers.tier_label("P2", "unlocked", 0), "débloqué")


class TestGuardrailsT(unittest.TestCase):
    def plan(self, **kw):
        p = tiers.plan_t_position(100.0, 1000.0, 6.0, {})
        p["pair"] = "XUSDT"
        p.update(kw)
        return p

    def test_ok(self):
        self.assertEqual(tiers.check_t_guardrails(self.plan(), 1000, [], 0, 0), [])

    def test_refusals(self):
        self.assertIn("risque > 1 % du capital", tiers.check_t_guardrails(self.plan(risk_usd=11), 1000, [], 0, 0))
        self.assertIn("levier > 3x", tiers.check_t_guardrails(self.plan(leverage=4), 1000, [], 0, 0))
        self.assertIn("position > 25 % du capital", tiers.check_t_guardrails(self.plan(size_usd=251), 1000, [], 0, 0))
        self.assertIn("liquidation < 3x la distance du stop",
                      tiers.check_t_guardrails(self.plan(stop_price=70.0), 1000, [], 0, 0))
        many = [dict(pair=f"P{i}", size_usd=10) for i in range(8)]
        self.assertIn("déjà 8 positions ouvertes", tiers.check_t_guardrails(self.plan(), 1000, many, 0, 0))
        self.assertIn("déjà 3 entrées aujourd'hui", tiers.check_t_guardrails(self.plan(), 1000, [], 3, 0))
        big = [dict(pair=f"P{i}", size_usd=240) for i in range(6)]
        self.assertIn("notionnel total > 150 % du capital", tiers.check_t_guardrails(self.plan(), 1000, big, 0, 0))
        self.assertIn("pair déjà ouvert (pas de moyenne à la baisse)",
                      tiers.check_t_guardrails(self.plan(), 1000, [dict(pair="XUSDT", size_usd=10)], 0, 0))
        self.assertIn("drawdown > 15 % : entrées suspendues", tiers.check_t_guardrails(self.plan(), 1000, [], 0, 0.16))


# ================================================================ INTÉGRATION
class TestNonRegression(unittest.TestCase):
    def test_arms_abc_identical(self):
        import baseline_2ter
        with open(baseline_2ter.PATH) as f:
            before = json.load(f)
        self.assertEqual(baseline_2ter.compute(), before)


def synth_events(n, seed, lift_true=0.25, n_random=0):
    rnd = random.Random(seed)
    ev = []
    for i in range(n):
        good = rnd.random() < 0.5
        crit = {"vrai_critere": good}
        crit.update({f"aleatoire_{j}": rnd.random() < 0.5 for j in range(n_random)})
        p = 0.15 + (lift_true if good else 0.0)
        out = {}
        for tier in ("P1", "P2", "P3", "P4"):
            w = rnd.random() < p
            out[tier] = dict(win=w, r=6.0 if w else -1.0, r_slip2=5.9 if w else -1.05, complete=True)
        ev.append(dict(ts=i * DAY, pair=f"X{i}", criteria=crit, outcomes=out))
    return ev


class TestSyntheticDiscovery(unittest.TestCase):
    def test_true_criterion_found(self):
        tests = discovery.analyse(synth_events(400, 1), ("P2",), with_pairs=False)
        ret = [t["criterion"] for t in tests if t["retained"]]
        self.assertEqual(ret, ["vrai_critere"])

    def test_200_random_criteria_not_retained(self):
        evs = synth_events(400, 2, lift_true=0.0, n_random=200)
        for e in evs:
            e["criteria"].pop("vrai_critere")
        tests = discovery.analyse(evs, ("P2",), with_pairs=False)
        self.assertEqual(len(tests), 200)
        self.assertEqual([t for t in tests if t["retained"]], [])

    def test_unlock_then_demote_when_edge_disappears(self):
        evs = synth_events(600, 4, lift_true=0.35)
        tests = discovery.analyse(evs, ("P2",), with_pairs=False)
        state, dec = discovery.decide_tiers(evs, {"P2": {"status": "shadow", "risk_pct": 0}}, tests, 600 * DAY)
        self.assertEqual(state["P2"]["status"], "unlocked", dec)
        # l'avantage disparaît : 40 derniers événements filtrés presque tous perdants
        rnd = random.Random(9)
        late = []
        for i in range(120):
            w = rnd.random() < 0.03
            late.append(dict(ts=(600 + i) * DAY, pair=f"L{i}", criteria={"vrai_critere": True},
                             outcomes={"P2": dict(win=w, r=6.0 if w else -1.0, r_slip2=5.9 if w else -1.05, complete=True)}))
        state2, dec2 = discovery.decide_tiers(evs + late, state, tests, 720 * DAY)
        self.assertEqual(state2["P2"]["status"], "shadow", dec2)
        self.assertTrue(any(d["action"] == "demote" for d in dec2))

    def test_read_only_never_changes_state(self):
        evs = synth_events(600, 4, lift_true=0.35)
        tests = discovery.analyse(evs, ("P2",), with_pairs=False)
        st0 = {"P2": {"status": "shadow", "risk_pct": 0}}
        state, dec = discovery.decide_tiers(evs, st0, tests, 600 * DAY, read_only=True)
        self.assertEqual(state["P2"]["status"], "shadow")
        self.assertTrue(any(d["action"] == "unlock" for d in dec))


class TestCycleDryRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db, cls.order = dryrun.run(14)

    def test_no_lock_conflict_and_order(self):
        self.assertEqual(self.db.lock_events, [])
        for day in range(14):
            names = [o[2] for o in self.order if o[0] == day]
            self.assertLess(names.index("R5"), names.index("R6"))
            self.assertLess(names.index("R6"), names.index("R3"))
            self.assertLess(names.index("R3"), names.index("R1"))
            self.assertLess(names.index("R1"), names.index("R2", names.index("R1")))

    def test_iteration_log_rows(self):
        by = {}
        for row in self.db.log:
            by.setdefault(row["routine"], []).append(row)
        self.assertGreaterEqual(len(by["routine5"]), 14)
        self.assertGreaterEqual(len(by["routine6"]), 14)
        self.assertTrue(all(r["change"]["status"] == "ok" for r in by["routine6"]))
        self.assertEqual(len(by["analyse"]), 14)
        self.assertEqual(len(by["verification"]), 56)

    def test_read_only_first_7_days(self):
        start = datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        for row in self.db.log:
            if row["routine"] == "routine6":
                t = datetime.fromisoformat(row["created_at"]).timestamp()
                self.assertEqual(row["change"]["read_only"], t < start + 7 * DAY)
        self.assertTrue(all(d["read_only"] for d in self.db.decisions if d["ts"] < start + 7 * DAY))

    def test_tier_positions_respect_guardrails(self):
        for p in self.db.positions:
            self.assertLessEqual(p["leverage"], 3)
            self.assertLessEqual(p["risk_usd"], 0.01 * p["equity_at_entry"] * 1.0001)
            self.assertLessEqual(p["size_usd"], 0.25 * p["equity_at_entry"] * 1.0001)
            self.assertGreaterEqual(1 - p["liquidation_price"] / p["entry_price"], 3 * p["stop_dist"] * 0.9999)


class TestRoutine6Waits(unittest.TestCase):
    def test_waits_then_not_run(self):
        now = datetime(2026, 9, 7, 5, 30, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        data = dict(config={}, signals=[], features=[], shadow_trades=[], entry_filters=[], last_r5=None)
        self.assertEqual(cli2ter.r6_compute(data, now, "daily", 1)["status"], "wait")
        res = cli2ter.r6_compute(data, now, "daily", 2)
        self.assertEqual(res["status"], "not_run")
        sql = cli2ter.r6_sql(res)
        self.assertEqual(len(sql), 1)
        self.assertIn("non exécutée", sql[0])

    def test_failed_r5_blocks(self):
        now = datetime(2026, 9, 6, 11, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()   # dimanche 11:00
        last = dict(created_at=datetime(2026, 9, 6, 10, 0, tzinfo=ZoneInfo("Europe/Paris")).isoformat(),
                    change={"status": "error"})
        data = dict(config={}, signals=[], features=[], shadow_trades=[], entry_filters=[], last_r5=last)
        self.assertEqual(cli2ter.r6_compute(data, now, "weekly", 1)["status"], "wait")

    def test_runs_after_r5_ok_daily_and_sunday(self):
        for hh, mode, r5h in ((5, "daily", 4), (11, "weekly", 10)):
            now = datetime(2026, 9, 6, hh, 30 if mode == "daily" else 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
            last = dict(created_at=datetime(2026, 9, 6, r5h, 5, tzinfo=ZoneInfo("Europe/Paris")).isoformat(),
                        change={"status": "ok"})
            data = dict(config={}, signals=[], features=[], shadow_trades=[], entry_filters=[], last_r5=last)
            self.assertEqual(cli2ter.r6_compute(data, now, mode, 1)["status"], "ok")

    def test_dryrun_with_r5_failure(self):
        db, _ = dryrun.run(3, r5_fail_day=1)
        r6 = [r for r in db.log if r["routine"] == "routine6"]
        self.assertEqual(r6[1]["change"]["status"], "not_run")
        self.assertEqual(r6[0]["change"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
