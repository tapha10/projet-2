"""Tests de la détection précoce (annonces d'exchanges, avant la hausse, modes) — hors réseau."""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from engine import announcements as A  # noqa: E402
from engine import cli, early, features  # noqa: E402

DAY = 86400


class TestAnnouncements(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(A.extract_symbols("World Premiere: Concrete (CT) Listed on KuCoin"), ["CT"])
        self.assertEqual(A.extract_symbols("Binance Futures Will Launch USDⓈ-Margined CTUSDT Perpetual Contract"), ["CT"])
        self.assertEqual(A.extract_symbols("OKX will launch GRVT/USD for spot trading"), ["GRVT"])
        self.assertEqual(A.extract_symbols("블라스트(BLAST) 거래유의종목 지정"), ["BLAST"])
        self.assertEqual(A.extract_symbols("Tether (USDT) maintenance"), [])

    def test_classify(self):
        self.assertEqual(A.classify("블라스트(BLAST) 거래유의종목 지정"), "warning")
        self.assertEqual(A.classify("샌드박스(SAND) 거래유의종목 지정 해제"), "warning_lifted")
        self.assertEqual(A.classify("달오픈네트워크(D), 훅트프로토콜(HOOK) 거래지원 종료"), "delisting")
        self.assertEqual(A.classify("에이셔(ASH) 원화 마켓 추가"), "listing")
        self.assertEqual(A.classify("CTUSDT now launched for futures trading and trading bots"), "perp")
        self.assertEqual(A.classify("World Premiere: Pheasant Network (PNT) Listed on KuCoin"), "listing")
        self.assertEqual(A.classify("Notice of Removal of Spot Trading Pairs", hint="delisting"), "delisting")
        self.assertEqual(A.classify("스타크넷(STRK) 입출금 일시 중지 안내"), "other")

    def test_recent_window_and_news(self):
        now = 1_800_000_000

        def fake():
            return [dict(exchange="x", title="Exchange lists Foo (FOO)", url="u1", published_at=now - 3600),
                    dict(exchange="x", title="Exchange lists Old (OLD)", url="u2", published_at=now - 72 * 3600),
                    dict(exchange="x", title="블라스트(BLAST) 거래유의종목 지정", url="u3", published_at=now - 7200)]

        items, err = A.recent(48, now=now, fetchers={"x": fake})
        self.assertEqual([i["symbols"] for i in items], [["FOO"], ["BLAST"]])
        g = A.by_pair(items, {"FOOUSDT", "BLASTUSDT"})
        self.assertEqual(sorted(g), ["BLASTUSDT", "FOOUSDT"])
        self.assertEqual(A.to_news(g["FOOUSDT"][0])["type"], "listing_or_perp")
        neg = A.to_news(g["BLASTUSDT"][0])
        self.assertEqual(neg["type"], "exchange_warning")          # pas de point de score
        self.assertTrue(neg["date_publication"].startswith("2027-01-15"))

    def test_source_error_isolated(self):
        def boom():
            raise RuntimeError("403")
        items, err = A.recent(48, now=1e9, fetchers={"down": boom})
        self.assertEqual(items, [])
        self.assertIn("down", err)


def daily(n, vq=1e6, close=1.0, rng=0.02):
    return [dict(t=i * DAY, o=close, h=close * (1 + rng), l=close * (1 - rng), c=close, vq=vq) for i in range(n)]


class TestPreMove(unittest.TestCase):
    rules = early.DEFAULTS["pre_move"]

    def test_accumulation_detected(self):
        ok, det = early.classify_pre_move(daily(30), dict(change_24h=0.02, quote_vol_24h=3e6), 0.25, self.rules)
        self.assertTrue(ok, det)
        self.assertAlmostEqual(det["vol_ratio"], 3.0)

    def test_price_already_moving_rejected(self):
        ok, _ = early.classify_pre_move(daily(30), dict(change_24h=0.12, quote_vol_24h=3e6), 0.25, self.rules)
        self.assertFalse(ok)

    def test_volume_too_low_rejected(self):
        ok, _ = early.classify_pre_move(daily(30), dict(change_24h=0.01, quote_vol_24h=1.5e6), 0.25, self.rules)
        self.assertFalse(ok)

    def test_needs_oi_or_compression(self):
        d = daily(20, rng=0.10) + daily(10, rng=0.10)      # pas de compression (ATR 7 = ATR 30)
        ok, det = early.classify_pre_move(d, dict(change_24h=0.0, quote_vol_24h=3e6), 0.05, self.rules)
        self.assertFalse(ok, det)
        tight = daily(23, rng=0.10) + daily(8, rng=0.01)   # volatilité comprimée
        ok, det = early.classify_pre_move(tight, dict(change_24h=0.0, quote_vol_24h=3e6), None, self.rules)
        self.assertTrue(ok, det)

    def test_7d_rise_rejected(self):
        d = daily(30)
        for i, x in enumerate(d[-7:]):
            x["c"] = 1.0 + 0.05 * (i + 1)
        ok, _ = early.classify_pre_move(d, dict(change_24h=0.02, quote_vol_24h=3e6), 0.25, self.rules)
        self.assertFalse(ok)

    def test_short_history(self):
        self.assertFalse(early.classify_pre_move(daily(10), dict(change_24h=0, quote_vol_24h=9e9), 1, self.rules)[0])

    def test_settings_merge(self):
        s = early.settings({"pre_move": {"min_vol_ratio": 3.0}})
        self.assertEqual(s["pre_move"]["min_vol_ratio"], 3.0)
        self.assertEqual(s["pre_move"]["max_candidates"], 8)
        self.assertEqual(early.DEFAULTS["pre_move"]["min_vol_ratio"], 2.0)   # défauts non modifiés


class TestDecideModes(unittest.TestCase):
    rules = {"min_score_enter": 3.0, "signal_candle_max_change": 0.15, "unlock_max_supply_pct": 0.005}
    w = {"volume_doubling": 1.5, "oi_rising": 1.0, "pre_move_accumulation": 2.0,
         "annonce_exchange_fraiche": 1.0, "listing_or_perp": 2.0, "alert_exchange_warning": -3.0}

    def test_mode_tags_do_not_change_score(self):
        c = dict(pair="X", change_24h=0.02, market_signal_types=["volume_doubling", "oi_rising"], market_alerts=[], news=[], alerts=[])
        c2 = dict(c, market_signal_types=c["market_signal_types"] + ["mode_momentum"])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[2], cli.decide_candidate(c2, self.rules, self.w)[2])

    def test_pre_move_can_enter(self):
        c = dict(pair="X", change_24h=0.02, market_signal_types=["oi_rising", "pre_move_accumulation", "mode_pre_move"],
                 market_alerts=[], news=[], alerts=[])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "enter")

    def test_pre_move_compression_only_is_not_enough(self):
        c = dict(pair="X", change_24h=0.02, market_signal_types=["pre_move_accumulation", "mode_pre_move"],
                 market_alerts=[], news=[], alerts=[])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "skip")

    def test_fresh_listing_announcement(self):
        c = dict(pair="X", change_24h=0.03, market_signal_types=["annonce_exchange_fraiche", "mode_announcement"],
                 market_alerts=[], news=[{"type": "listing_or_perp"}], alerts=[])
        types, alerts, sc, dec, _ = cli.decide_candidate(c, self.rules, self.w)
        self.assertEqual((sc, dec), (3.0, "enter"))

    def test_exchange_warning_skips(self):
        c = dict(pair="X", change_24h=0.02, market_signal_types=["volume_doubling", "oi_rising", "pre_move_accumulation"],
                 market_alerts=["alert_exchange_warning"], news=[{"type": "exchange_warning"}], alerts=[])
        self.assertEqual(cli.decide_candidate(c, self.rules, self.w)[3], "skip")


class TestScanMerge(unittest.TestCase):
    """early_candidates n'enlève ni ne modifie les candidats momentum (sauf alertes / annonces)."""

    def setUp(self):
        self.orig = (cli.market_profile, A.recent, early.pre_move_scan)
        cli.market_profile = lambda pair, t, s: dict(pair=pair, last=1.0, change_24h=t["change_24h"], quote_vol_24h=1e7,
                                                     vol_doubling=False, oi_change_3d=0.3, rsi14=50, breakout_20d=False,
                                                     peak_passed=False, atr14=0.05, data_source="test")
        now = time.time()
        A.recent = lambda hours: ([dict(exchange="okx", title="OKX lists Newc (NEWC)", url="u", published_at=now - 600,
                                        kind="listing", symbols=["NEWC"]),
                                   dict(exchange="bithumb", title="(MOMO) 거래유의종목 지정", url="u2",
                                        published_at=now - 600, kind="warning", symbols=["MOMO"])], {})
        early.pre_move_scan = lambda tick, excl, rules, src: ([("CALMUSDT", {"vol_ratio": 4.0})], 10)

    def tearDown(self):
        cli.market_profile, A.recent, early.pre_move_scan = self.orig

    def test_merge(self):
        mom = dict(pair="MOMOUSDT", market_signal_types=["top_gainer_24h", "mode_momentum"], market_alerts=[],
                   news=[], alerts=[], detection_modes=["momentum"])
        cands = [mom]
        by_pair = {p: dict(pair=p, change_24h=0.01, quote_vol_24h=1e7) for p in ("MOMOUSDT", "NEWCUSDT", "CALMUSDT")}
        errors = []
        log = cli.early_candidates({}, cands, list(by_pair.values()), by_pair, {}, set(), ("gate",), errors)
        pairs = {c["pair"]: c for c in cands}
        self.assertEqual(set(pairs), {"MOMOUSDT", "NEWCUSDT", "CALMUSDT"})
        self.assertEqual(pairs["MOMOUSDT"]["detection_modes"], ["momentum"])
        self.assertIn("alert_exchange_warning", pairs["MOMOUSDT"]["market_alerts"])
        self.assertEqual(pairs["NEWCUSDT"]["detection_modes"], ["announcement"])
        self.assertIn("annonce_exchange_fraiche", pairs["NEWCUSDT"]["market_signal_types"])
        self.assertEqual(pairs["NEWCUSDT"]["news"][0]["type"], "listing_or_perp")
        self.assertEqual(pairs["CALMUSDT"]["detection_modes"], ["pre_move"])
        self.assertIn("pre_move_accumulation", pairs["CALMUSDT"]["market_signal_types"])
        self.assertEqual(errors, [])

    def test_disabled(self):
        cands = []
        log = cli.early_candidates({"early_detection": {"enabled": False}}, cands, [], {}, {}, set(), (), [])
        self.assertEqual(log, {"enabled": False})
        self.assertEqual(cands, [])


class TestModeCriteria(unittest.TestCase):
    def test_modes(self):
        c = features.eval_criteria({"detection_mode": ["pre_move"]})
        self.assertTrue(c["mode_avant_hausse"])
        self.assertFalse(c["mode_momentum"])
        self.assertIsNone(features.eval_criteria({})["mode_annonce"])


if __name__ == "__main__":
    unittest.main()
