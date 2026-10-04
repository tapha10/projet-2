"""Tests du prompt 3 (routine 7, chaînes de victoires) : unitaires, exemple chiffré, données
synthétiques, non-régression. Détail et résultats : docs/tests_3.md."""
import json
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from engine import chains as C  # noqa: E402

DAY = 86400


def synth_events(n, p_win, seed=1, stop=None, r=None, crit_lift=None, n_pairs=400, spacing_h=6, score=(3, 5),
                 random_crit=False, hold_h=24):
    """Flux d'événements iid : pour chaque couple (stop, R) de la grille, victoire avec p_win
    (ou p_win + lift si le critère X est présent). Une victoire rapporte R (moins 0,05 R de frais),
    une perte coûte -1,05 R."""
    rng = random.Random(seed)
    evs = []
    for i in range(n):
        ts = i * spacing_h * 3600.0
        x = rng.random() < 0.5
        crit = {"X": x}
        if random_crit:
            crit["aleatoire"] = rng.random() < 0.5
        outs = {}
        u = rng.random()           # même tirage pour toute la grille : un événement gagne ou perd
        for s in C.GRID_STOPS:
            for rr in C.GRID_R:
                pw = p_win
                if crit_lift and x and s <= 0.05:
                    pw = min(0.99, p_win + crit_lift)
                win = u < pw
                outs[C.gkey(s, rr)] = dict(win=win, reason="tp" if win else "sl", r=(rr - 0.05) if win else -1.05,
                                         r2=(rr - 0.1) if win else -1.1, exit_ts=ts + hold_h * 3600, complete=True)
        base = rng.randint(*score)
        evs.append(dict(id=i, ts=ts, pair=f"P{i % n_pairs}", base_score=base, score=base, crit=crit,
                        outcomes=outs, regime=rng.choice(["calme", "haussier", "baissier"]), vol24h=1e9))
    return evs


class TestArithmetic(unittest.TestCase):
    def test_reference_example(self):
        led = C.chain_ledger(100, 3, 5)
        self.assertEqual(led["risks"], [100, 300, 900, 2700, 8100])
        self.assertEqual(led["gains"], [300, 900, 2700, 8100, 24300])
        self.assertEqual(led["total"], 36300)
        self.assertEqual(led["fail_balance"], [-100, 0, 300, 1200, 3900])

    def test_positions_of_example(self):
        a = C.step_size(100, 0.10, 3, 10000, 3)                 # étape 1 : stop 10 %, objectif +30 %
        self.assertAlmostEqual(a["size"], 1000)
        self.assertAlmostEqual(a["tp_pct"], 0.30)
        b = C.step_size(300, 0.05, 3, 10300, 3)                 # étape 2 : risque 300, stop 5 %, +15 %
        self.assertAlmostEqual(b["size"], 6000)
        self.assertAlmostEqual(b["tp_pct"], 0.15)
        self.assertAlmostEqual(b["size"] * b["tp_pct"], 900)

    def test_stop_is_target_over_3(self):
        for s in (0.05, 0.10, 0.15):
            self.assertAlmostEqual(C.step_size(10, s, 3, 1000, 3)["tp_pct"], 3 * s)

    def test_stop_cap(self):
        self.assertIn("refused", C.step_size(10, 0.16, 3, 1000, 3))

    def test_leverage_reduces_risk_not_stop(self):
        # étape 5 de l'exemple : risque 8 100, stop 10 % -> 81 000 sur un capital de 22 000 = 3,7x > 3x
        x = C.step_size(8100, 0.10, 3, 22000, 3)
        self.assertTrue(x["reduced"])
        self.assertAlmostEqual(x["size"], 66000)
        self.assertAlmostEqual(x["risk"], 6600)                 # risque réduit, stop inchangé
        self.assertLessEqual(x["leverage"], 3 + 1e-9)

    def test_liquidation_twice_the_stop(self):
        x = C.step_size(1000, 0.15, 3, 1000, 7)                 # 7x demandé, stop 15 %
        liq = 1 / x["lev_cap"] - 0.01
        self.assertGreaterEqual(liq + 1e-9, 2 * (0.15 + 0.001))

    def test_liquidity_cap(self):
        x = C.step_size(1000, 0.05, 3, 1e6, 3, vol24h=5e6)      # 0,1 % de 5 M = 5 000
        self.assertAlmostEqual(x["size"], 5000)
        self.assertIn("liquidité", x["reason"])


def ev_one(ts, pair, score, win, stop=0.10, r=3, hold_h=1):
    outs = {C.gkey(s, rr): dict(win=win, reason="tp" if win else "sl", r=rr if win else -1.0,
                                r2=rr if win else -1.0, exit_ts=ts + hold_h * 3600, complete=True)
            for s in C.GRID_STOPS for rr in C.GRID_R}
    return dict(id=int(ts), ts=ts, pair=pair, score=score, outcomes=outs, vol24h=1e12)


class TestChainRules(unittest.TestCase):
    def p(self, **kw):
        return C.variant(max_open_chains=1, **kw)

    def test_risk_next_equals_previous_gain_and_stop_on_loss(self):
        evs = [ev_one(i * 7200, f"P{i}", 9, w) for i, w in enumerate([True, True, False, True])]
        res = C.run_chains(evs, self.p(), capital=10000)
        st = res["steps"]
        self.assertAlmostEqual(st[0]["risk"], 100)
        self.assertAlmostEqual(st[1]["risk"], st[0]["pnl"])     # risque k+1 = gain k
        self.assertAlmostEqual(st[2]["risk"], st[1]["pnl"])
        first = res["chains"][0]
        self.assertEqual(first.state, "échouée")
        self.assertEqual(first.level, 2)
        self.assertAlmostEqual(first.balance, 300)              # échec à l'étape 3 : +300
        self.assertAlmostEqual(st[3]["risk"], 0.01 * 10300)     # nouvelle chaîne : 1 % du capital (10 300)

    def test_full_chain_banks_36300(self):
        evs = [ev_one(i * 7200, f"P{i}", 9, True) for i in range(5)]
        res = C.run_chains(evs, self.p(stops=[0.10] * 5, max_leverage=100.0), capital=10000)
        c = res["chains"][0]
        self.assertEqual(c.state, "réussie")
        self.assertAlmostEqual(c.bank, 36300)

    def test_reinvest_share(self):
        evs = [ev_one(i * 7200, f"P{i}", 9, w) for i, w in enumerate([True, False])]
        res = C.run_chains(evs, self.p(reinvest=0.5), capital=10000)
        c = res["chains"][0]
        self.assertAlmostEqual(res["steps"][1]["risk"], 150)
        self.assertAlmostEqual(c.bank, 150)
        self.assertAlmostEqual(c.balance, 300 - 150)

    def test_gating_by_level(self):
        # niveau 3 exige un score >= 4 : le signal de score 3 est ignoré, celui de score 4 est pris
        evs = [ev_one(0, "A", 3, True), ev_one(7200, "B", 3, True), ev_one(14400, "C", 3, True),
               ev_one(21600, "D", 4, False)]
        res = C.run_chains(evs, self.p(), capital=10000)
        self.assertEqual([s["pair"] for s in res["steps"]], ["A", "B", "D"])
        self.assertEqual(res["steps"][2]["gate"], 4)

    def test_secure_after_wait(self):
        evs = [ev_one(0, "A", 9, True), ev_one(5 * DAY, "B", 0, True)]
        res = C.run_chains(evs, self.p(option="secure", wait_days=3), capital=10000)
        c = res["chains"][0]
        self.assertEqual(c.state, "sécurisée")
        self.assertAlmostEqual(c.bank, 300)

    def test_no_same_pair_twice(self):
        evs = [ev_one(0, "A", 9, True, hold_h=48), ev_one(3600, "A", 9, True)]
        res = C.run_chains(evs, C.variant(max_open_chains=3), capital=10000)
        self.assertEqual(len(res["steps"]), 1)                 # pas de moyenne à la baisse / doublon

    def test_independent_events(self):
        evs = [ev_one(i * 7200, "SAME", 9, True) for i in range(5)]
        res = C.run_chains(evs, self.p(stops=[0.10] * 5, max_leverage=100.0), capital=10000)
        self.assertEqual(C.independent_wins(res["chains"][0]), 1)   # une seule hausse : 1 victoire indépendante


class TestSynthetic(unittest.TestCase):
    def test_a_p70_gives_17pc(self):
        evs = synth_events(6000, 0.70, seed=3)
        p = C.variant(stops=[0.10] * 5, gating=[0] * 5, max_leverage=100.0)
        s = C.summarize(C.run_chains(evs, p), p)
        self.assertGreater(s["n_chains"], 500)
        self.assertAlmostEqual(s["p_full"], 0.7 ** 5, delta=0.03)  # 16,8 %
        mc = C.monte_carlo({k: (int(700 * 0.7), 700) for k in range(1, 6)}, p, seed=2)
        self.assertAlmostEqual(mc["p_full"], 0.168, delta=0.02)

    def test_b_real_criterion_found_and_raises_threshold(self):
        # X relève P(victoire) de 30 % à 75 % aux étapes à stop 5 % (niveaux 2 à 5) ; 8 000 événements,
        # sinon la validation (30 % récents, ~15 étapes de niveau 4) n'a pas la puissance de conclure.
        evs = synth_events(8000, 0.30, seed=5, crit_lift=0.45, score=(3, 5))
        kept, rep = C.criterion_search(evs, 0.05, 3)
        self.assertIn("X", kept)
        rs = C.rescore(evs, kept)
        p = C.variant(gating=[3, 3, 4, 5, 5])
        prop = C.propose_gating(rs, p)
        self.assertIsNotNone(prop["change"], prop["reason"])
        self.assertEqual(prop["change"]["delta"], 1)          # le système monte un seuil
        self.assertEqual(prop["change"]["level"], 4)          # niveau 4 : 5 -> 6 (seul X passe)

    def test_c_random_criterion_not_retained(self):
        hits = 0
        for i in range(200):
            evs = synth_events(300, 0.35, seed=1000 + i, random_crit=True)
            kept, _ = C.criterion_search(evs, 0.05, 3)
            hits += "aleatoire" in kept
        self.assertLessEqual(hits, 2, f"critère aléatoire retenu {hits}/200 fois")

    def test_d_no_hot_hand_without_streak_effect(self):
        evs = synth_events(4000, 0.5, seed=11)
        hh = C.hot_hand(evs)
        self.assertGreater(hh["p_value"], 0.05, hh)
        self.assertIn("aucun effet", hh["conclusion"])

    def test_breakeven_r3(self):
        self.assertAlmostEqual(C.breakeven(C.variant())["p_step"], 0.25, places=3)


class TestNonRegression3(unittest.TestCase):
    def test_routines_1_to_6_identical(self):
        import baseline_3
        with open(baseline_3.PATH) as f:
            before = json.load(f)
        self.assertEqual(json.loads(json.dumps(baseline_3.compute())), before)


if __name__ == "__main__":
    unittest.main()
