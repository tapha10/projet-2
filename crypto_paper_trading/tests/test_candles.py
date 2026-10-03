"""Audit du suivi bougie par bougie : ordre stop / objectif, bougies traitées une seule fois,
bougie d'entrée, bougie en cours, funding réel, tranches et vérification de bout en bout."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import cli, market, simulate, tiers  # noqa: E402


def k(t, o, h, l, c):
    return dict(t=t, o=o, h=h, l=l, c=c, vq=0.0)


def ps_b(opened=0):
    """Bras B : entrée 100, stop 88, objectif 140, équilibre à +15 %."""
    return simulate.PosState(entry=100, size_usd=100, leverage=1, stop=88, initial_stop=88, tp=140,
                             opened_ts=opened, max_hold_ts=10 ** 8, be_trigger=115)


def minutes(t0, path):
    """Bougies 1 min à partir d'une liste de (haut, bas)."""
    return [k(t0 + 60 * i, (h + l) / 2, h, l, (h + l) / 2) for i, (h, l) in enumerate(path)]


def refine_from(fine):
    return lambda t0, t1: [r for r in fine if t0 <= r["t"] < t1]


class TestOrder(unittest.TestCase):
    def test_tp_first_in_minutes(self):
        ps = ps_b()
        big = k(0, 100, 145, 85, 120)                      # stop ET objectif dans la bougie 15 min
        fine = minutes(0, [(101, 99), (145, 120), (125, 85)] + [(120, 119)] * 12)
        r = simulate.step(ps, [big], refine=refine_from(fine))
        self.assertEqual((r["exit_reason"], r["exit_price"], r["exit_ts"]), ("tp", 140, 60))
        self.assertEqual(ps.audit[0][0], "1m")

    def test_stop_first_in_minutes(self):
        ps = ps_b()
        fine = minutes(0, [(101, 99), (100, 85), (145, 120)] + [(120, 119)] * 12)
        r = simulate.step(ps, [k(0, 100, 145, 85, 120)], refine=refine_from(fine))
        self.assertEqual((r["exit_reason"], r["exit_ts"]), ("sl", 60))

    def test_same_minute_stays_prudent(self):
        ps = ps_b()
        fine = minutes(0, [(145, 85)] + [(120, 119)] * 14)
        r = simulate.step(ps, [k(0, 100, 145, 85, 120)], refine=refine_from(fine))
        self.assertEqual(r["exit_reason"], "sl")
        self.assertIn("stop_et_objectif_meme_bougie", [a[0] for a in ps.audit])

    def test_no_fine_data_is_prudent(self):
        ps = ps_b()
        r = simulate.step(ps, [k(0, 100, 145, 85, 120)], refine=lambda a, b: [])
        self.assertEqual(r["exit_reason"], "sl")
        self.assertEqual(ps.audit[0][0], "prudent")
        ps = ps_b()

        def boom(a, b):
            raise market.DataError("indisponible")
        self.assertEqual(simulate.step(ps, [k(0, 100, 145, 85, 120)], refine=boom)["exit_reason"], "sl")

    def test_breakeven_inside_candle(self):
        """+16 % à la 3e minute puis retour à 99 : avec 1 min, sortie à l'équilibre (comme un vrai
        stop déplacé) ; sans 1 min, l'ordre est inconnu et la position reste ouverte."""
        fine = minutes(0, [(101, 100), (105, 101), (116, 105), (110, 104), (104, 99)] + [(100, 99.5)] * 10)
        big = k(0, 100, 116, 99, 100)
        ps = ps_b()
        r = simulate.step(ps, [big], refine=refine_from(fine))
        self.assertEqual((r["exit_reason"], r["exit_price"], r["exit_ts"]), ("breakeven", 100, 240))
        ps = ps_b()
        self.assertIsNone(simulate.step(ps, [big]))


class TestOncePerCandle(unittest.TestCase):
    def test_candle_not_reread(self):
        """Défaut d'origine : la bougie qui déclenchait l'équilibre était relue à la vérification
        suivante avec le stop déjà remonté, d'où une fausse sortie à l'équilibre."""
        ps = ps_b()
        candle = k(0, 100, 116, 97, 110)
        self.assertIsNone(simulate.step(ps, [candle]))
        self.assertEqual((ps.stop, ps.through), (100, 900))
        self.assertIsNone(simulate.step(ps, [candle, k(900, 110, 112, 108, 111)]))
        self.assertEqual(ps.through, 1800)

    def test_open_candle_waits(self):
        ps = ps_b()
        rows = [k(0, 100, 101, 99, 100), k(900, 100, 101, 80, 85)]   # 2e bougie encore en cours
        self.assertIsNone(simulate.step(ps, rows, now=1500))
        self.assertEqual(ps.through, 900)
        r = simulate.step(ps, rows, now=1800)                      # fermée : traitée
        self.assertEqual((r["exit_reason"], r["exit_ts"]), ("sl", 900))

    def test_no_gap_between_checks(self):
        """Découper le suivi en plusieurs vérifications donne exactement le même résultat."""
        rows = [k(900 * i, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(30)] + [k(27000, 130, 131, 100, 101)]
        one = ps_b()
        r1 = simulate.step(one, rows, now=10 ** 6)
        many = ps_b()
        r2 = None
        for now in (3000, 9000, 15000, 22000, 10 ** 6):
            r2 = simulate.step(many, rows, now=now) or r2
        self.assertEqual(r1, r2)
        self.assertEqual((one.stop, one.highest), (many.stop, many.highest))


class TestEntryCandle(unittest.TestCase):
    def test_prices_before_entry_ignored(self):
        """Entrée à 14:07 (t=420) : la chute à 85 à 14:02 précède l'entrée, elle ne compte pas."""
        fine = minutes(0, [(100, 100), (100, 100), (100, 85)] + [(100, 99)] * 12)
        ps = ps_b(opened=420)
        self.assertIsNone(simulate.step(ps, [k(0, 100, 100, 85, 100)], refine=refine_from(fine)))
        self.assertEqual(ps.through, 900)

    def test_prices_after_entry_count(self):
        fine = minutes(0, [(100, 99)] * 10 + [(100, 85)] + [(100, 99)] * 4)
        ps = ps_b(opened=420)
        r = simulate.step(ps, [k(0, 100, 100, 85, 100)], refine=refine_from(fine))
        self.assertEqual((r["exit_reason"], r["exit_ts"]), ("sl", 600))


class TestFunding(unittest.TestCase):
    def test_real_rates_between_entry_and_exit(self):
        rates = [(0, 0.5), (28800, 0.001), (57600, -0.0005), (86400, 0.9)]
        self.assertAlmostEqual(simulate.funding_cost(1000, 0, 86399, rates), 0.5)
        self.assertAlmostEqual(simulate.funding_cost(1000, 0, 86399, None, 0.0001), 1000 * 0.0001 * 3, places=3)
        ps = ps_b()
        r = simulate.pnl(ps, 140, 86399, "tp", 0.0, 0.0001, rates)
        self.assertAlmostEqual(r["funding_usd"], 0.05)                   # 100 USDT x (0,1 % - 0,05 %)
        self.assertAlmostEqual(r["pnl_usd"], 40 - 0.05)


class TestTranches(unittest.TestCase):
    def _pos(self):
        ts = {"P2": {"status": "unlocked", "risk_pct": 0.01}, "P3": {"status": "unlocked", "risk_pct": 0.01}}
        return tiers.new_pos(tiers.plan_t_position(100.0, 1000.0, 6.0, ts), 0)

    def test_target_first_in_minutes(self):
        pos = self._pos()
        a = pos["tranches"]["A"]["target"]
        fine = minutes(0, [(a + 0.5, 99), (a, 50)] + [(60, 55)] * 13)
        tiers.step_tranches(pos, [k(0, 100, a + 0.5, 50, 55)], 0.0, 900, refine=refine_from(fine))
        self.assertEqual(pos["tranches"]["A"]["exit_reason"], "tp")
        self.assertEqual(pos["tranches"]["B"]["exit_reason"], "breakeven")    # stop à l'entrée ensuite
        self.assertEqual(pos["audit"][0][0], "1m")

    def test_not_reread(self):
        pos = self._pos()
        a = pos["tranches"]["A"]["target"]
        candle = k(0, 100, a + 0.5, 99.5, a)
        tiers.step_tranches(pos, [candle], 0.0, 900)
        self.assertEqual(pos["stop_price"], 100.0)
        tiers.step_tranches(pos, [candle], 0.0, 900)                         # relue : ignorée
        self.assertEqual(pos["tranches"]["B"]["status"], "open")


class TestCheckEndToEnd(unittest.TestCase):
    """cmd_check avec un marché simulé : SQL produit, bougies 1 min, reprise sans relecture."""

    def run_check(self, pos_row, rows15, fine, now, rates):
        st = dict(config={"fee_rate_per_side": 0.00055, "funding_rate_8h_estimate": 0.0001,
                          "slippage_pct": 0.001, "data_sources": ["gate"]},
                  open_positions=[pos_row])
        d = tempfile.mkdtemp()
        sp, out = os.path.join(d, "s.json"), os.path.join(d, "o.sql")
        with open(sp, "w") as f:
            json.dump(st, f)
        with mock.patch.object(market, "candles", lambda *a, **kw: ([r for r in rows15 if r["t"] >= a[2] - 900], "test")), \
             mock.patch.object(market, "fine_candles", lambda p, t0, t1, s=None: ([r for r in fine if t0 <= r["t"] < t1], "test")), \
             mock.patch.object(market, "funding_history", lambda p, a, b: ([x for x in rates if a < x[0] <= b], "gate")), \
             mock.patch.object(cli, "now_ts", lambda: now):
            cli.cmd_check(type("A", (), dict(state=sp, out=out, tiers=False, daily=False))())
        with open(out) as f:
            return f.read()

    def test_check(self):
        row = dict(id=1, arm="B", pair="XUSDT", opened_at="1970-01-01T00:07:00+00:00", entry_price=100,
                   stop_price=88, initial_stop_price=88, tp_price=140, size_usd=100, leverage=1,
                   breakeven_trigger_price=115, max_hold_until="1970-02-01T00:00:00+00:00",
                   highest_price=100, mae_pct=0)
        rows15 = [k(0, 100, 101, 95, 100), k(900, 100, 145, 86, 120), k(1800, 120, 121, 119, 120)]
        fine = minutes(0, [(100, 99)] * 15) + minutes(900, [(101, 99), (145, 120), (125, 86)] + [(121, 119)] * 12)
        sql = self.run_check(row, rows15, fine, 2000, [(930, 0.002), (1000, 0.5)])
        self.assertIn("exit_reason='tp'", sql)                           # 1 min : objectif avant le stop
        self.assertIn("closed_at='1970-01-01T00:16:00+00:00'", sql)      # minute exacte de l'objectif
        self.assertIn("funding_usd=0.2,", sql)                           # seul le règlement d'avant la sortie
        self.assertIn("sim_through_at='1970-01-01T00:17:00+00:00'::timestamptz", sql)
        self.assertIn("rejouée(s) en 1 min", sql)
        # position restée ouverte : reprise exactement après la dernière bougie fermée
        rows15 = [k(0, 100, 116, 99, 110), k(900, 110, 111, 99, 100)]
        fine = minutes(0, [(100, 100)] * 7 + [(116, 110)] * 8)
        sql = self.run_check(dict(row, sim_through_at=None), rows15, fine, 1500, [])
        self.assertIn("stop_price=100", sql)
        self.assertIn("sim_through_at='1970-01-01T00:15:00+00:00'::timestamptz", sql)
        sql = self.run_check(dict(row, stop_price=100, highest_price=116, sim_through_at="1970-01-01T00:15:00+00:00"),
                             rows15, fine, 1900, [])
        self.assertIn("exit_reason='breakeven'", sql)                    # bougie 900 (99 <= 100), pas la 0
        self.assertIn("closed_at='1970-01-01T00:15:00+00:00'", sql)


if __name__ == "__main__":
    unittest.main()
