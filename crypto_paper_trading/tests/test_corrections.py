"""Corrections du 04/10/2026 : sortir des cercles vicieux « pas de trade, pas d'apprentissage »."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import cli, cli7  # noqa: E402

DAY = 86400


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class TestExploration(unittest.TestCase):
    def test_arms_after_7_days_without_entry(self):
        now = 100 * DAY
        st = dict(last_entry={"A": iso(now - 2 * DAY)})
        cfg = {"demo_started_at": iso(now - 10 * DAY)}
        arms, _ = cli.exploration_arms(st, cfg, now)
        self.assertEqual(arms, {"B", "C"})                 # A a une entrée récente
        arms, _ = cli.exploration_arms(dict(last_entry={}), {"demo_started_at": iso(now - 3 * DAY)}, now)
        self.assertEqual(arms, set())                       # démo trop récente

    def test_pick_only_score_refusals_without_alert(self):
        rules = {"min_score_enter": 3}
        ds = [dict(decision="skip", reason="score 2.5 < seuil 3", score=2.5, alerts=[]),
              dict(decision="skip", reason="score 2.8 < seuil 3", score=2.8, alerts=["alert_unlock_7d"]),
              dict(decision="wait", reason="bougie du signal (+52%)", score=6, alerts=[]),
              dict(decision="skip", reason="score 1.5 < seuil 3", score=1.5, alerts=[])]
        d = cli.pick_exploration(ds, rules, {"A"})
        self.assertIs(d, ds[0])
        self.assertEqual(d["decision"], "enter")
        self.assertTrue(d["explore"])
        self.assertEqual(ds[2]["decision"], "wait")          # jamais la bougie du signal
        self.assertIsNone(cli.pick_exploration([dict(ds[3])], rules, {"A"}))   # trop loin du seuil
        self.assertIsNone(cli.pick_exploration(ds, rules, set()))

    def test_no_exploration_if_real_entry(self):
        ds = [dict(decision="enter", reason="ok", score=4, alerts=[]),
              dict(decision="skip", reason="score 2.5 < seuil 3", score=2.5, alerts=[])]
        self.assertIsNone(cli.pick_exploration(ds, {"min_score_enter": 3}, {"A"}))


class TestCounterfactualLearning(unittest.TestCase):
    def test_signals_older_than_10_days_one_per_event(self):
        now = 100 * DAY
        sig = lambda i, pair, age: dict(id=i, pair=pair, detected_at=iso(now - age * DAY), price_at_detection=1.0,
                                       metrics={"atr14": 0.05}, is_reference=False)
        h = dict(signals=[sig(1, "AUSDT", 20), sig(2, "AUSDT", 18), sig(3, "BUSDT", 12), sig(4, "CUSDT", 5),
                          sig(5, "DUSDT", 30)])
        rows = cli.counterfactual_trades(h, "A", {5}, now)
        self.assertEqual(sorted(r["signal_id"] for r in rows), [1, 3])   # 2 = même hausse que 1 ; 4 trop récent
        self.assertTrue(all(r["counterfactual"] for r in rows))


class TestChainExploration(unittest.TestCase):
    def test_after_7_days_without_step(self):
        now = 100 * DAY
        data = dict(config={"chain_readonly_until": iso(now - 8 * DAY)}, steps=[])
        self.assertTrue(cli7.chain_exploration(data, now))
        data["steps"] = [dict(decided_at=iso(now - DAY))]
        self.assertFalse(cli7.chain_exploration(data, now))


if __name__ == "__main__":
    unittest.main()
