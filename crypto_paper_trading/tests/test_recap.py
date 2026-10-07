"""Tests du récapitulatif lisible et de la mise en forme HTML de l'e-mail."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mailfmt, recap  # noqa: E402


def sig(**kw):
    base = dict(pair="XUSDT", decision="skip", decision_reason="", alerts=[], signal_types=["mode_momentum"],
                score=1, evidence=[], detected_at="2026-10-03T17:34:35+00:00")
    base.update(kw)
    return base


class TestReasons(unittest.TestCase):
    def test_weak_score_lists_only_missing(self):
        t = recap.simple_reason(sig(decision_reason="score 2.5 < seuil 3",
                                    signal_types=["volume_doubling", "oversold_or_breakout"]))
        self.assertIn("2.5 point(s) sur 3", t)
        self.assertIn("annonce datée", t)
        self.assertNotIn("volume qui double", t)

    def test_penalty(self):
        t = recap.simple_reason(sig(decision_reason="score -1.0 < seuil 3", alerts=["alert_peak_passed"]))
        self.assertIn("pic déjà passé", t)

    def test_each_rule(self):
        cases = {
            "bougie du signal (+52% sur la journée ou 24 h) : ...": "+52 %",
            "alerte : unlock > 0,5 % de l'offre dans les 7 jours": "débloqués",
            "alerte : transferts de l'équipe / market maker vers les exchanges": "équipe",
            "alerte : mise sous surveillance ou fin de cotation annoncée par un exchange": "surveillance",
            "signal valide mais aucune place : bras A plein": "plafond",
            "conditions d'entrée non remplies : volume 1.2x < 2x": "Réévaluation",
        }
        for reason, expect in cases.items():
            self.assertIn(expect, recap.simple_reason(sig(decision_reason=reason)), reason)
        self.assertIn("ouverte", recap.simple_reason(sig(decision="enter", decision_reason="score 4 >= seuil")))

    def test_buckets_and_funnel(self):
        ss = [sig(pair="AUSDT", decision_reason="score 1.0 < seuil 3"),
              sig(pair="BUSDT", decision="wait", decision_reason="bougie du signal (+30%)"),
              sig(pair="CUSDT", decision="enter", decision_reason="ok", signal_types=["mode_pre_move", "pre_move_accumulation"],
                  evidence=[{"url": "https://x.y/z", "titre": "Annonce", "date_publication": "2026-10-03T10:00:00+00:00"}])]
        md = "\n".join(recap.funnel(ss, [], 0))
        self.assertIn("| avant la hausse | 1 | 1 | 0 | 0 |", md)
        self.assertIn("Signal trop faible (score < 3) | 1 | A", md)
        self.assertIn("[Annonce](https://x.y/z) 2026-10-03", md)
        self.assertLess(md.index("**C**"), md.index("**A**"))       # les entrées d'abord

    def test_empty_week(self):
        md = "\n".join(recap.funnel([], [], 0))
        self.assertIn("Aucun candidat cette semaine", md)
        b = "\n".join(recap.brief([], [], [], {"A": 1000.0}))
        self.assertIn("aucun signal détecté", b)

    def test_glance(self):
        arms = {"Bras A": dict(desc="r", open=0, closed_week=0, pnl_week=0.0, halted=False),
                "Bras B": dict(desc="r", open=1, closed_week=0, pnl_week=0.0, halted=False),
                "Bras C": dict(desc="r", open=0, closed_week=0, pnl_week=-50.0, halted=True)}
        md = "\n".join(recap.glance(arms, None, {"P2": {"n_events": 7}}, "raison X"))
        self.assertIn("💤 Aucune entrée : raison X", md)
        self.assertIn("✅ Actif", md)
        self.assertIn("⛔ Suspendu", md)
        self.assertIn("7/40", md)

    def test_criteria_fr(self):
        self.assertEqual(recap.crit_fr("btc_haussier & volume_x2"), "BTC haussier + volume x2")


class TestGoLiveGate(unittest.TestCase):
    def test_gate(self):
        good = [dict(r_multiple=1.0 if i % 3 else -1.0, pnl_usd=5.0 if i % 3 else -10.0,
                     closed_at=f"2026-10-{i % 28 + 1:02d}") for i in range(60)]
        few = good[:10]
        md = "\n".join(recap.go_live_gate({"A": good, "B": few}, [], 0, 13 * 7 * 86400, 0))
        self.assertIn("| A | 60/50 | 13.0/3 |", md)
        self.assertIn("✅ seuil atteint", md)
        self.assertIn("manque : 50 trades", md)
        md = "\n".join(recap.go_live_gate({"A": good}, [], 0, 2 * 7 * 86400, 2))
        self.assertIn("3 semaines", md)
        self.assertIn("aucun incident non expliqué", md)
        self.assertIn("n'autorise aucun passage au réel", md)
        bad_dd = [dict(by_arm={"A": {"drawdown": 0.2}})]
        self.assertIn("drawdown < 15 %", "\n".join(recap.go_live_gate({"A": good}, bad_dd, 0, 13 * 7 * 86400, 0)))


class TestMailFormat(unittest.TestCase):
    def test_convert(self):
        md = ("# Titre\n\n> **DÉMO** avertissement\n\n## Section\n\n- point **gras**\n- [lien](https://a.b)\n\n"
              "| A | B |\n|---|---|\n| 1 | <script> |\n\nTexte *italique* et `code`.")
        h = mailfmt.convert(md)
        for frag in ("<h1", "<h2", "<ul", "<strong>gras</strong>", 'href="https://a.b"', "<table", "<em>italique</em>",
                     "<code>", "border-left:4px solid", "<style>"):
            self.assertIn(frag, h)
        self.assertNotIn("<script>", h)                              # échappement HTML
        self.assertIn("&lt;script&gt;", h)


if __name__ == "__main__":
    unittest.main()
