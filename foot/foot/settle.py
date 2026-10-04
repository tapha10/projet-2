"""Règlement plus/moins 2,5 buts (temps réglementaire uniquement)."""

LINE = 2.5


def total_goals(home_goals, away_goals):
    if home_goals is None or away_goals is None:
        return None
    return int(home_goals) + int(away_goals)


def settle_side(side, home_goals, away_goals, status="FT"):
    """Retourne 'win', 'loss' ou 'void'.

    Les buts doivent être ceux du temps réglementaire (90 min + arrêts de jeu) ;
    prolongations et tirs au but exclus. Match reporté/annulé/abandonné -> 'void'.
    """
    if status in ("POSTPONED", "CANCELLED", "ABANDONED", "VOID"):
        return "void"
    tg = total_goals(home_goals, away_goals)
    if tg is None:
        raise ValueError("score manquant pour un match terminé")
    over = tg > LINE
    if side == "over":
        return "win" if over else "loss"
    if side == "under":
        return "win" if not over else "loss"
    raise ValueError(side)


def settle_combo(leg_results, leg_odds):
    """Combiné : perdu si une jambe perd ; jambes annulées retirées (cote recalculée)."""
    if any(r == "loss" for r in leg_results):
        return "loss", 0.0
    live = [o for r, o in zip(leg_results, leg_odds) if r == "win"]
    if not live:
        return "void", 1.0
    pay = 1.0
    for o in live:
        pay *= o
    return "win", pay
