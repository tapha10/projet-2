"""
Scraper pour footballpredictions.net (version FR).

Ce module ne récupère QUE des informations publiées par le site avant/après
un match (pronostics, cotes affichées, scores finaux tels qu'affichés par le
site). Il ne fabrique, n'estime, ni ne complète aucune donnée manquante.

Le site est une application server-rendered (le HTML statique contient déjà
les pronostics, contrairement à une hypothèse initiale de SPA pure côté
client) : un simple GET HTTP suffit, aucun rendu JavaScript n'est requis.

Limites connues (voir rapport.md, section F) :
- La page d'accueil FR n'expose que les pronostics du jour/week-end.
- Les pages "resultats-hier" / "il-y-a-2-jours" / "il-y-a-3-jours" sont les
  SEULES pages d'historique de résultats accessibles publiquement : le site
  ne propose aucune archive au-delà de 3 jours.
- robots.txt bloque explicitement le crawler d'Internet Archive
  (`User-agent: ia_archiver / Disallow: /`), donc la Wayback Machine ne
  contient pas d'historique exploitable de ces pages.
- Les marchés "plus/moins de 2,5 buts" et les probabilités en % ne sont pas
  systématiquement publiés sur chaque page de match (voir rapport.md).
- Aucune donnée SofaScore n'est intégrée : l'API publique de SofaScore
  renvoie 403 Forbidden aux requêtes non authentifiées de ce type.

Usage (collecte quotidienne, à programmer par cron pour accumuler un
historique réel au fil du temps) :
    python3 scraper.py --collect-today --out data/predictions_log.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE = "https://footballpredictions.net/fr"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 1.2  # politesse : évite de marteler le serveur

LISTING_PAGES = {
    "today": "football-pronostics-conseils-paris-gratuits",
    "hier": "football-resultats-hier?show_all=1",
    "j-2": "football-resultats-d-il-y-a-2-jours",
    "j-3": "football-resultats-d-il-y-a-3-jours",
}


@dataclass
class ListingMatch:
    source_page: str
    league: Optional[str]
    home_team: str
    away_team: str
    match_datetime: Optional[str]
    score_home: Optional[str]
    score_away: Optional[str]
    site_pick_1x2: Optional[str]
    site_marked_correct_icon: bool
    match_url: Optional[str]
    collected_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DetailMatch:
    match_url: str
    pick_1x2_text: Optional[str]
    odds_1x2_pick: Optional[float]
    pick_btts: Optional[str]
    odds_btts: Optional[float]
    pick_exact_score: Optional[str]
    odds_exact_score: Optional[float]
    pick_over_under_25: Optional[str]
    collected_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_listing_html(html: str, source_page: str) -> list[ListingMatch]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingMatch] = []
    current_league = None
    for el in soup.find_all(["h3", "div"]):
        if el.name == "h3":
            txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if txt:
                current_league = txt
            continue
        if "match-card" not in (el.get("class") or []):
            continue
        home_el = el.select_one(".home-team .team-label")
        away_el = el.select_one(".away-team .team-label")
        if not home_el or not away_el:
            continue
        date_el = el.select_one(".match-preview-date moment")
        scores = el.select(".match-preview-details .score")
        pred_el = el.select_one(".prediction-holder .prediction")
        link_el = el.select_one("a.preview-button")
        success_icon = el.select_one(".successfully-predicted, .successfully-predicted-wdw")
        pred_txt = None
        if pred_el:
            pred_txt = re.sub(r"\s+", " ", pred_el.get_text(" ", strip=True).replace("👉", "")).strip()
        rows.append(
            ListingMatch(
                source_page=source_page,
                league=current_league,
                home_team=home_el.get_text(strip=True),
                away_team=away_el.get_text(strip=True),
                match_datetime=date_el.get_text(strip=True) if date_el else None,
                score_home=scores[0].get_text(strip=True) if len(scores) >= 1 else None,
                score_away=scores[1].get_text(strip=True) if len(scores) >= 2 else None,
                site_pick_1x2=pred_txt,
                site_marked_correct_icon=bool(success_icon),
                match_url=link_el.get("href") if link_el else None,
            )
        )
    return rows


def _odds_after(text: str, anchor_pattern: str) -> Optional[float]:
    am = re.search(anchor_pattern, text)
    if not am:
        return None
    window = text[am.end(): am.end() + 400]
    nm = re.search(r"(\d+\.\d{2})\s*»", window)
    return float(nm.group(1)) if nm else None


def parse_detail_html(html: str, url: str) -> DetailMatch:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    m = re.search(
        r"Pronostics? à la fin du temps réglementaire\s*👉?\s*"
        r"(Victoire de [^.\d]+?|Match nul|Nul)(?=\s*Unavailable|\s*\d|\s*»|$)",
        text,
    )
    pick_1x2 = m.group(1).strip() if m else None

    m = re.search(r'Pronostics? "les deux équipes marquent"\s*👉?\s*(Oui|Non)', text)
    pick_btts = m.group(1) if m else None

    m = re.search(r"Pronostic score exact\s*👉?\s*(\d+-\d+)", text)
    pick_exact_score = m.group(1) if m else None

    m = re.search(
        r"Pronostics? (?:plus|moins) de 2[,.]5 buts\s*👉?\s*(Plus de 2,5 buts|Moins de 2,5 buts)",
        text,
    )
    pick_over_under_25 = m.group(1) if m else None

    return DetailMatch(
        match_url=url,
        pick_1x2_text=pick_1x2,
        odds_1x2_pick=_odds_after(text, r"temps réglementaire\s*👉?\s*(?:Victoire de [^.\d]+?|Match nul|Nul)"),
        pick_btts=pick_btts,
        odds_btts=_odds_after(text, r"les deux équipes marquent.\s*👉?\s*(?:Oui|Non)"),
        pick_exact_score=pick_exact_score,
        odds_exact_score=_odds_after(text, r"score exact\s*👉?\s*\d+-\d+"),
        pick_over_under_25=pick_over_under_25,
    )


def collect_listings(pages: dict[str, str] = LISTING_PAGES) -> list[ListingMatch]:
    all_rows: list[ListingMatch] = []
    for tag, path in pages.items():
        url = f"{BASE}/{path}"
        html = fetch(url)
        rows = parse_listing_html(html, tag)
        all_rows.extend(rows)
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_rows


def collect_details(urls: list[str]) -> list[DetailMatch]:
    out = []
    for url in urls:
        html = fetch(url)
        out.append(parse_detail_html(html, url))
        time.sleep(REQUEST_DELAY_SECONDS)
    return out


def append_csv(rows: list, path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys())
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-today", action="store_true",
                         help="Récupère les 4 pages de listing disponibles (aujourd'hui + 3 jours de résultats)")
    parser.add_argument("--collect-details", metavar="URLS_FILE",
                         help="Fichier texte (1 URL par ligne) de pages de match à détailler (cotes, score exact, BTTS)")
    parser.add_argument("--out", default="data/predictions_log.csv")
    parser.add_argument("--out-details", default="data/predictions_details_log.csv")
    args = parser.parse_args()

    if args.collect_today:
        rows = collect_listings()
        append_csv(rows, Path(args.out))
        print(f"{len(rows)} lignes ajoutées à {args.out}")

    if args.collect_details:
        urls = [l.strip() for l in Path(args.collect_details).read_text().splitlines() if l.strip()]
        rows = collect_details(urls)
        append_csv(rows, Path(args.out_details))
        print(f"{len(rows)} lignes ajoutées à {args.out_details}")


if __name__ == "__main__":
    main()
