"""
Exécute l'analyse statistique sur les données réellement collectées
(data/predictions_log.csv et data/predictions_details_log.csv) et écrit des
tableaux de résultats dans data/results/.

Ce script ne fabrique aucune donnée : les matchs sans score final connu, ou
les pronostics dont le texte ne peut pas être associé sans ambiguïté à une
équipe, sont exclus et comptés séparément.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from stats import BetResult, evaluate_filter, wilson_confidence_interval, roi as roi_fn

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = DATA_DIR / "results"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def load_listing(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def finished_matches(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r["score_home"].isdigit() and r["score_away"].isdigit():
            out.append(r)
    return out


def actual_1x2(row: dict) -> str:
    h, a = int(row["score_home"]), int(row["score_away"])
    if h > a:
        return "home"
    if h < a:
        return "away"
    return "draw"


def pick_1x2_side(pick_text: str, home_team: str, away_team: str) -> str | None:
    if not pick_text:
        return None
    t = pick_text.strip().lower()
    if t in ("nul", "match nul"):
        return "draw"
    m = re.match(r"victoire de (.+)", t, re.IGNORECASE)
    if not m:
        return None
    who = norm(m.group(1))
    nh, na = norm(home_team), norm(away_team)
    if who == nh or who in nh or nh in who:
        return "home"
    if who == na or who in na or na in who:
        return "away"
    return None


def eval_1x2_cross_section(rows: list[dict]) -> tuple[list[BetResult], list[dict], int]:
    """Évalue le marché 1N2 sur les correspondances non-ambiguës uniquement.
    Retourne (paris, lignes utilisées, nb de lignes exclues pour ambiguïté)."""
    bets, used = [], []
    excluded = 0
    for r in rows:
        side = pick_1x2_side(r["site_pick_1x2"], r["home_team"], r["away_team"])
        if side is None:
            excluded += 1
            continue
        won = side == actual_1x2(r)
        bets.append(BetResult(won=won, odds=None, date=r["match_datetime"]))
        used.append(r)
    return bets, used, excluded


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    listing = finished_matches(load_listing(DATA_DIR / "predictions_log.csv"))
    print(f"Matchs terminés collectés (listing, marché 1N2 uniquement) : {len(listing)}")

    bets, used, excluded = eval_1x2_cross_section(listing)
    ev = evaluate_filter("1N2 - échantillon global (pilote, sans cotes)", bets)
    print(f"  -> exploitables: {ev.n}  exclus (texte de pronostic non résolu): {excluded}")
    print(f"  Taux de réussite: {ev.hit_rate:.1%}  IC95%: [{ev.ci_low:.1%}, {ev.ci_high:.1%}]")

    # Ventilation par championnat (n >= 5 seulement pour ne pas publier du bruit)
    by_league = defaultdict(list)
    for r, b in zip(used, bets):
        by_league[r["league"] or "Inconnu"].append(b)

    league_rows = []
    for league, lb in sorted(by_league.items(), key=lambda kv: -len(kv[1])):
        e = evaluate_filter(league, lb)
        league_rows.append({
            "championnat": league, "n": e.n, "gagnants": e.wins,
            "taux_reussite": f"{e.hit_rate:.1%}",
            "ic95_bas": f"{e.ci_low:.1%}", "ic95_haut": f"{e.ci_high:.1%}",
        })
    write_csv(RESULTS_DIR / "1x2_par_championnat.csv", league_rows,
               ["championnat", "n", "gagnants", "taux_reussite", "ic95_bas", "ic95_haut"])
    print(f"  -> {len(league_rows)} championnats écrits dans results/1x2_par_championnat.csv")

    # Favori à domicile vs favori à l'extérieur (proxy : le site pronostique le domicile ?)
    home_pick_bets = [b for r, b in zip(used, bets)
                       if pick_1x2_side(r["site_pick_1x2"], r["home_team"], r["away_team"]) == "home"]
    away_pick_bets = [b for r, b in zip(used, bets)
                       if pick_1x2_side(r["site_pick_1x2"], r["home_team"], r["away_team"]) == "away"]
    draw_pick_bets = [b for r, b in zip(used, bets)
                       if pick_1x2_side(r["site_pick_1x2"], r["home_team"], r["away_team"]) == "draw"]
    filt_rows = []
    for name, fb in [("Pronostic = victoire domicile", home_pick_bets),
                      ("Pronostic = victoire extérieur", away_pick_bets),
                      ("Pronostic = match nul", draw_pick_bets)]:
        e = evaluate_filter(name, fb)
        filt_rows.append({"regle": name, "n": e.n, "gagnants": e.wins,
                            "taux_reussite": f"{e.hit_rate:.1%}",
                            "ic95_bas": f"{e.ci_low:.1%}", "ic95_haut": f"{e.ci_high:.1%}"})
    write_csv(RESULTS_DIR / "1x2_par_type_de_pronostic.csv", filt_rows,
               ["regle", "n", "gagnants", "taux_reussite", "ic95_bas", "ic95_haut"])

    # --- Échantillon détaillé (cotes réelles) : 1N2, BTTS, score exact ---
    details = load_listing(DATA_DIR / "predictions_details_log.csv")
    listing_by_url = {r["match_url"]: r for r in listing}

    markets = {"1x2": [], "btts": [], "exact_score": []}
    for d in details:
        r = listing_by_url.get(d["match_url"])
        if not r:
            continue  # match pas dans l'échantillon "terminé" (ne devrait pas arriver)
        h, a = int(r["score_home"]), int(r["score_away"])

        # 1X2
        side = pick_1x2_side(d["pick_1x2_text"], r["home_team"], r["away_team"])
        odds = float(d["odds_1x2_pick"]) if d["odds_1x2_pick"] else None
        if side is not None:
            markets["1x2"].append(BetResult(won=(side == actual_1x2(r)), odds=odds, date=r["match_datetime"]))

        # BTTS
        if d["pick_btts"] in ("Oui", "Non"):
            actual_btts = "Oui" if (h > 0 and a > 0) else "Non"
            odds_b = float(d["odds_btts"]) if d["odds_btts"] else None
            markets["btts"].append(BetResult(won=(d["pick_btts"] == actual_btts), odds=odds_b, date=r["match_datetime"]))

        # Score exact
        if d["pick_exact_score"]:
            actual_score = f"{h}-{a}"
            odds_e = float(d["odds_exact_score"]) if d["odds_exact_score"] else None
            markets["exact_score"].append(BetResult(won=(d["pick_exact_score"] == actual_score), odds=odds_e, date=r["match_datetime"]))

    market_rows = []
    for name, bets_m in markets.items():
        e = evaluate_filter(name, bets_m)
        market_rows.append({
            "marche": name, "n": e.n, "gagnants": e.wins,
            "taux_reussite": f"{e.hit_rate:.1%}",
            "ic95_bas": f"{e.ci_low:.1%}", "ic95_haut": f"{e.ci_high:.1%}",
            "cote_moyenne": f"{e.avg_odds:.2f}" if e.avg_odds else "n/a",
            "roi": f"{e.roi:+.1%}" if e.roi is not None else "n/a",
            "drawdown_max": f"{e.max_drawdown:.2f}u" if e.max_drawdown is not None else "n/a",
            "plus_longue_serie_perdante": e.max_losing_streak,
        })
        print(f"[{name}] n={e.n} taux={e.hit_rate:.1%} cote_moy={e.avg_odds} roi={e.roi}")

    write_csv(RESULTS_DIR / "marches_echantillon_detaille.csv", market_rows,
               ["marche", "n", "gagnants", "taux_reussite", "ic95_bas", "ic95_haut",
                "cote_moyenne", "roi", "drawdown_max", "plus_longue_serie_perdante"])
    print("Résultats écrits dans data/results/")


if __name__ == "__main__":
    main()
