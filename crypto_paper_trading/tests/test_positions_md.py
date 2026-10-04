"""Section « Mes positions » du rapport : distances SL/TP, progression, latent, échéances."""
import unittest

from engine import cli, positions_md, stats

NOW = stats.parse_ts("2026-10-04T18:00:00+00:00")
POS = [dict(id=1, arm="A", pair="XUSDT", status="open", opened_at="2026-10-04T12:00:00+00:00", entry_price=1.0,
            stop_price=0.75, initial_stop_price=0.75, tp_price=1.4, size_usd=40, leverage=2, risk_usd=10,
            liquidation_price=0.51, max_hold_until="2026-10-14T12:00:00+00:00", highest_price=1.05, signal_id=9),
       dict(id=2, arm="B", pair="XUSDT", status="open", opened_at="2026-10-04T12:00:00+00:00", entry_price=1.0,
            stop_price=0.88, initial_stop_price=0.88, tp_price=1.4, size_usd=83.33, leverage=6, risk_usd=10,
            breakeven_trigger_price=1.15, liquidation_price=0.85, max_hold_until="2026-10-14T12:00:00+00:00",
            highest_price=1.05, signal_id=9)]
SIG = [dict(id=9, pair="XUSDT", decision="enter", decision_reason="score 3.5 >= seuil", detected_at="2026-10-04T12:00:00+00:00"),
       dict(id=10, pair="YUSDT", decision="wait", score=6, decision_reason="bougie du signal (+52%) : attendre",
            detected_at="2026-10-04T10:00:00+00:00", reevaluate_after="2026-10-05T10:00:00+00:00")]


class PositionsMd(unittest.TestCase):
    def test_positions(self):
        md = "\n".join(positions_md.positions_section(POS, SIG, {"XUSDT": 1.2}, NOW))
        self.assertIn("+20.0% depuis l'entrée", md)
        self.assertIn("| A (stop large) | 0.75 | -37.5% | 1.4000 | +16.7% | 50% |", md)
        self.assertIn("+8.00 $", md)                      # latent A : 40 x 20 %
        self.assertIn("stop remonté à l'entrée si le prix touche 1.1500", md)
        self.assertIn("perte maximale si tous les stops sont touchés ≈ 20.00 $", md)

    def test_waits_and_deadlines(self):
        w = "\n".join(positions_md.waits_section(SIG, NOW, {}))
        self.assertIn("| Y | 6 |", w)
        d = "\n".join(positions_md.deadlines_section(POS, SIG, lambda k: None, NOW))
        self.assertIn("réévaluation de Y", d)
        self.assertIn("sortie au plus tard de X (A, B)", d)

    def test_wait_ends_when_reevaluated(self):
        sig = SIG + [dict(id=11, pair="YUSDT", decision="enter", decision_reason="réévaluation", parent_signal_id=10,
                          detected_at="2026-10-05T10:00:00+00:00")]
        self.assertIn("Aucun signal en attente", "\n".join(positions_md.waits_section(sig, NOW, {})))

    def test_email_keeps_key_sections(self):
        md = "# T\n\n## En bref\n\nx\n\n## 2. Comparaison\n\ny\n\n## Mes positions ouvertes (détail)\n\nz\n"
        e = cli.email_md(md)
        self.assertIn("## Mes positions ouvertes", e)
        self.assertNotIn("2. Comparaison", e)


if __name__ == "__main__":
    unittest.main()
