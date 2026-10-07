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


def _trades(n, fall=0.20):
    out = []
    for i in range(n):
        t0 = T0 + i * 3600
        out.append(dict(signal_id=i, pair="X%dUSDT" % i, opened_at=inverse.datetime.fromtimestamp(t0, tz=inverse.timezone.utc).isoformat(),
                        entry_price=1.0, status="closed", closed_at="2026-10-10T00:00:00+00:00", r_multiple=0.3,
                        pnl_usd=3.0))
    return out


def _fall_candles(t):
    t0 = parse_ts(t["opened_at"])
    return [dict(t=t0 + 900 * k, o=1 - 0.01 * k, h=1 - 0.01 * k + 0.002, l=1 - 0.01 * k - 0.002, c=1 - 0.01 * k)
            for k in range(60)]


class Adapt(unittest.TestCase):
    NOW = T0 + 30 * 86400

    def test_stats_only_below_30(self):
        sql, msg, det = inverse.adapt(dict(params={}, inverse=_trades(12)), self.NOW, _fall_candles, lambda p: (lambda a, b: []))
        self.assertEqual(sql, [])
        self.assertIn("12/30", msg)

    def test_promotes_one_param_within_20pct(self):
        st = dict(params={}, inverse=_trades(40))
        sql, msg, det = inverse.adapt(st, self.NOW, _fall_candles, lambda p: (lambda a, b: []))
        self.assertTrue(det["promoted"], msg)
        (k, v), = det["candidate"].items()
        self.assertIn(k, inverse.TUNABLE)
        self.assertLessEqual(abs(v / inverse.DEFAULTS[k] - 1), 0.2001)
        self.assertTrue(any("update config set value" in x and "inverse_params" in x for x in sql))
        self.assertFalse(any("positions" in x.replace("inverse_positions", "") for x in sql))

    def test_waits_after_recent_change(self):
        st = dict(params={}, inverse=_trades(40), prev=dict(params=dict(inverse.DEFAULTS), changed_at=_trades(40)[30]["opened_at"]))
        sql, msg, det = inverse.adapt(st, self.NOW, _fall_candles, lambda p: (lambda a, b: []))
        self.assertEqual(sql, [])
        self.assertIn("attend", msg)

    def test_rollback_when_worse(self):
        tr = _trades(60)
        prev = dict(params=dict(inverse.DEFAULTS, tp_pct=0.10), changed_at=tr[30]["opened_at"])
        st = dict(params=dict(stop_pct=0.03), inverse=tr, prev=prev)   # stop trop serré : rebond de 5 % puis chute

        def bounce(t):
            cs = _fall_candles(t)
            cs[1] = dict(cs[1], h=1.05)
            return cs
        sql, msg, det = inverse.adapt(st, self.NOW, bounce, lambda p: (lambda a, b: []))
        self.assertTrue(det.get("rollback"), msg)
        self.assertTrue(any("inverse_params" in x for x in sql))


if __name__ == "__main__":
    unittest.main()
