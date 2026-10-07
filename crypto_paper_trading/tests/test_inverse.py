"""Portefeuille S (stratégie inverse, démo) : stop/objectif d'un short, plafonds, SQL."""
import unittest

from engine import inverse
from engine.stats import parse_ts

T0 = parse_ts("2026-10-04T12:00:00+00:00")
SRC = dict(signal_id=1, pair="XUSDT", opened_at="2026-10-04T12:00:00+00:00", entry_price=1.0,
           position_ids=[1, 2])


def candles(*hl):   # (haut, bas) par bougie 15 min
    return [dict(t=T0 + 900 * i, o=(h + l) / 2, h=h, l=l, c=(h + l) / 2) for i, (h, l) in enumerate(hl)]


def sim(cs, trail=None, now=None):
    p = dict(inverse.DEFAULTS, tp_trail_pct=trail)
    row = inverse.new_row(SRC, [], p)
    closed = inverse.apply_sim(row, p, now or T0 + 900 * (len(cs) + 1), candles=cs, refine=lambda a, b: [], funding=[])
    return row, closed


class Inverse(unittest.TestCase):
    def test_levels(self):
        row = inverse.new_row(SRC, [], inverse.DEFAULTS)
        self.assertAlmostEqual(row["stop_price"] / row["entry_price"], 1.30)
        self.assertAlmostEqual(row["tp_price"] / row["entry_price"], 0.90)
        self.assertLess(row["tp_price"], row["entry_price"])
        self.assertLessEqual(row["leverage"], 2)
        self.assertAlmostEqual(row["size_usd"], 1000 * 0.01 / 0.30, places=2)

    def test_tp_gain(self):
        row, closed = sim(candles((1.01, 0.99), (1.0, 0.85)))
        self.assertTrue(closed)
        self.assertEqual(row["exit_reason"], "tp")
        self.assertGreater(row["pnl_usd"], 0)

    def test_stop_loss(self):
        row, closed = sim(candles((1.0, 0.99), (1.40, 1.0)))
        self.assertEqual(row["exit_reason"], "sl")
        self.assertLess(row["pnl_usd"], 0)
        self.assertLess(row["r_multiple"], 0)

    def test_stop_first_when_same_candle(self):
        row, closed = sim(candles((1.40, 0.80)))
        self.assertEqual(row["exit_reason"], "sl")

    def test_trailing_tp(self):
        row, closed = sim(candles((1.0, 0.85), (0.9, 0.70), (0.74, 0.69)), trail=0.10)
        self.assertFalse(closed)
        self.assertTrue(row["trailing_active"])
        row2, closed2 = sim(candles((1.0, 0.85), (0.9, 0.70), (0.74, 0.69), (0.90, 0.75)), trail=0.10)
        self.assertEqual(row2["exit_reason"], "trailing")
        self.assertGreater(row2["pnl_usd"], 0)

    def test_time_exit(self):
        row, closed = sim(candles(*[(1.0, 0.95)] * 700), now=T0 + 8 * 86400)
        self.assertEqual(row["exit_reason"], "time")

    def test_caps(self):
        p = inverse.DEFAULTS
        rows = [dict(pair=f"P{i}", opened_at="2026-10-04T08:00:00+00:00", status="open", closed_at=None,
                     pnl_usd=0) for i in range(3)]
        self.assertEqual(inverse.can_open(rows, T0, "NEW", p), "3 entrées par jour")
        self.assertEqual(inverse.can_open(rows[:1], T0, "P0", p), "même pair déjà ouvert")
        self.assertIsNone(inverse.can_open(rows[:1], T0, "NEW", p))

    def test_params_capped(self):
        p = inverse.params_of(dict(params=dict(leverage=9, risk_pct=0.5, max_open=99, max_per_day=99)))
        self.assertEqual((p["leverage"], p["risk_pct"], p["max_open"], p["max_per_day"]), (2.0, 0.01, 8, 3))

    def test_sql(self):
        row, _ = sim(candles((1.0, 0.85)))
        sql = inverse.to_sql([row], [], dict(opened=1, closed=1, updated=0, skipped=[], errors=[]))
        self.assertIn("insert into inverse_positions", sql)
        self.assertIn("on conflict (signal_id) do nothing", sql)
        self.assertNotIn("update positions", sql)
        self.assertTrue(sql.startswith("begin;") and sql.strip().endswith("commit;"))


if __name__ == "__main__":
    unittest.main()
