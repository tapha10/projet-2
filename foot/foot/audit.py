"""Audit des sources (section 5) : on teste l'accès, on n'insiste pas en cas de refus, on ne contourne rien."""
from __future__ import annotations

import os

import requests

from . import load_config
from .db import Store, now_utc

# usage : "oui" = utilisée ; "non" = exclue (motif dans notes) ; "clé" = utilisable si une clé est fournie
SOURCES = [
    {"source": "football-data.co.uk — saisons (mmz4281)", "url": "https://football-data.co.uk/mmz4281/2627/E0.csv",
     "usage": "oui", "coverage": "22 championnats européens ; résultats, tirs, arbitre, cotes 1X2/plus-moins 2,5 "
     "avant-match et clôture ; xG depuis 2026-27", "freshness": "mise à jour environ 2 fois par semaine",
     "limits": "pas de compositions ni d'absences ; résultats avec 1 à 3 jours de retard",
     "terms": "robots.txt : tout autorisé sauf robots d'entraînement d'IA ; usage non commercial, cache + délai"},
    {"source": "football-data.co.uk — fixtures.csv", "url": "https://football-data.co.uk/fixtures.csv",
     "usage": "oui", "coverage": "matchs à venir des 22 championnats avec cotes plus/moins 2,5",
     "freshness": "mis à jour avant les week-ends et les journées de semaine (heure de collecte non indiquée)",
     "limits": "certains jours sans matchs couverts ; cotes = instantané au moment de la publication",
     "terms": "idem"},
    {"source": "football-data.co.uk — new_league_fixtures.csv / new/*.csv",
     "url": "https://football-data.co.uk/new_league_fixtures.csv", "usage": "non",
     "coverage": "MLS, Brésil, Argentine, Japon, Scandinavie…", "freshness": "idem",
     "limits": "cotes 1X2 seulement, AUCUNE cote plus/moins 2,5 -> ligues non éligibles", "terms": "idem"},
    {"source": "OpenLigaDB (Bundesliga)", "url": "https://api.openligadb.de/getmatchdata/bl1/2026/1",
     "usage": "prévue", "coverage": "D1, D2 : calendrier et scores", "freshness": "quasi temps réel",
     "limits": "Allemagne seulement ; pas de cotes ; non branchée tant que la table de correspondance des "
     "noms d'équipes n'est pas faite", "terms": "API communautaire ouverte et gratuite"},
    {"source": "openfootball (GitHub)", "url": "https://raw.githubusercontent.com/openfootball/england/master/2026-27/1-premierleague.txt",
     "usage": "non", "coverage": "calendriers de plusieurs ligues", "freshness": "irrégulière",
     "limits": "scores pas toujours à jour ; format texte", "terms": "domaine public (CC0)"},
    {"source": "Open-Meteo (météo)", "url": "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.1&hourly=precipitation",
     "usage": "non", "coverage": "prévisions météo mondiales", "freshness": "horaire",
     "limits": "nécessite les coordonnées des stades (non disponibles pour l'instant)",
     "terms": "gratuit pour usage non commercial"},
    {"source": "Understat (xG)", "url": "https://understat.com/robots.txt", "usage": "non",
     "coverage": "xG 6 ligues", "freshness": "-", "limits": "-",
     "terms": "robots.txt : « Disallow: / » pour tous -> interdit, non utilisé"},
    {"source": "FBref (StatsBomb/Opta)", "url": "https://fbref.com/robots.txt", "usage": "non",
     "coverage": "xG, compositions", "freshness": "-", "limits": "accès refusé (403)",
     "terms": "refus d'accès -> non contourné"},
    {"source": "TheSportsDB", "url": "https://www.thesportsdb.com/robots.txt", "usage": "non",
     "coverage": "scores du jour", "freshness": "-", "limits": "-",
     "terms": "Content-Signal : ai-input=no -> exclu par prudence"},
    {"source": "ESPN API", "url": "https://site.api.espn.com/robots.txt", "usage": "non",
     "coverage": "scores, compositions", "freshness": "-", "limits": "API non documentée ; robots.txt refusé",
     "terms": "conditions non claires -> exclu"},
    {"source": "Sofascore / Flashscore / Transfermarkt", "url": "https://www.sofascore.com/robots.txt",
     "usage": "non", "coverage": "compositions, absences", "freshness": "-", "limits": "-",
     "terms": "conditions d'utilisation interdisant l'extraction automatisée -> exclu"},
    {"source": "The Odds API", "url": "https://api.the-odds-api.com/v4/sports", "usage": "clé",
     "env": "ODDS_API_KEY", "coverage": "cotes plus/moins de nombreuses ligues (dont MLS…)",
     "freshness": "temps réel", "limits": "offre gratuite : 500 requêtes/mois",
     "terms": "clé personnelle dans les variables d'environnement, jamais dans le dépôt"},
    {"source": "API-Football (api-sports.io)", "url": "https://v3.football.api-sports.io/status", "usage": "clé",
     "env": "API_FOOTBALL_KEY", "coverage": "compositions, absences, scores en direct, statistiques",
     "freshness": "temps réel", "limits": "offre gratuite : 100 requêtes/jour",
     "terms": "clé personnelle dans les variables d'environnement"},
    {"source": "football-data.org", "url": "https://api.football-data.org/v4/competitions/PL/matches",
     "usage": "clé", "env": "FOOTBALL_DATA_ORG_KEY", "coverage": "scores de 12 compétitions majeures",
     "freshness": "quasi temps réel", "limits": "offre gratuite : 10 requêtes/minute",
     "terms": "clé personnelle dans les variables d'environnement"},
]


def probe(src, cfg):
    headers = {"User-Agent": cfg["user_agent"]}
    key_env = src.get("env")
    if key_env and os.environ.get(key_env):
        if "api-sports" in src["url"]:
            headers["x-apisports-key"] = os.environ[key_env]
        elif "football-data.org" in src["url"]:
            headers["X-Auth-Token"] = os.environ[key_env]
    try:
        r = requests.get(src["url"], headers=headers, timeout=25)
        return r.status_code, None
    except requests.RequestException as e:
        return None, str(e)[:200]


def run_audit(store: Store, cfg=None, probe_fn=probe):
    cfg = cfg or load_config()
    out = []
    for s in SOURCES:
        code, err = probe_fn(s, cfg)
        key_missing = s.get("env") and not os.environ.get(s["env"])
        accessible = code is not None and 200 <= code < 400 and not key_missing
        notes = f"usage : {s['usage']}"
        if err:
            notes += f" ; erreur réseau : {err}"
        if key_missing:
            notes += f" ; clé absente (variable {s['env']} non définie)"
        row = {"source": s["source"], "url": s["url"], "checked_at": now_utc(), "accessible": int(accessible),
               "status_code": code, "freshness": s["freshness"], "coverage": s["coverage"],
               "limits": s["limits"], "terms": s["terms"], "notes": notes}
        store.insert("foot_source_audit", row)
        out.append(row)
    return out
