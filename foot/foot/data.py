"""Données : téléchargement poli (cache, délai, user-agent) et normalisation des fichiers football-data.co.uk.

Source principale : https://www.football-data.co.uk (robots.txt : « User-agent: * Disallow: » ;
les robots d'entraînement d'IA sont exclus — ce système n'entraîne pas de modèle d'IA généraliste,
il télécharge quelques fichiers CSV pour une analyse statistique non commerciale, avec cache et délai).
Aucune donnée n'est inventée : une valeur absente reste vide (NaN).
"""
from __future__ import annotations

import hashlib
import io
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import ROOT, load_config

BASE = "https://football-data.co.uk"
RAW = ROOT / "data" / "raw"

COLMAP = {
    "Div": "league", "HomeTeam": "home", "AwayTeam": "away",
    "FTHG": "fthg", "FTAG": "ftag", "HTHG": "hthg", "HTAG": "htag", "Referee": "referee",
    "HxG": "hxg", "AxG": "axg", "HS": "hs", "AS": "as_", "HST": "hst", "AST": "ast",
    "HC": "hc", "AC": "ac", "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
    "Avg>2.5": "o_over_avg", "Avg<2.5": "o_under_avg",
    "B365>2.5": "o_over_b365", "B365<2.5": "o_under_b365",
    "Max>2.5": "o_over_max", "Max<2.5": "o_under_max",
    "AvgC>2.5": "c_over_avg", "AvgC<2.5": "c_under_avg",
    "B365C>2.5": "c_over_b365", "B365C<2.5": "c_under_b365",
    "AvgH": "o_h_avg", "AvgD": "o_d_avg", "AvgA": "o_a_avg",
    "AvgCH": "c_h_avg", "AvgCD": "c_d_avg", "AvgCA": "c_a_avg",
    # anciens noms (saisons <= 2018/19)
    "BbAv>2.5": "o_over_avg", "BbAv<2.5": "o_under_avg",
    "BbAvH": "o_h_avg", "BbAvD": "o_d_avg", "BbAvA": "o_a_avg",
}
NUMERIC = ["fthg", "ftag", "hthg", "htag", "hxg", "axg", "hs", "as_", "hst", "ast", "hc", "ac",
           "hy", "ay", "hr", "ar", "o_over_avg", "o_under_avg", "o_over_b365", "o_under_b365",
           "o_over_max", "o_under_max", "c_over_avg", "c_under_avg", "c_over_b365", "c_under_b365",
           "o_h_avg", "o_d_avg", "o_a_avg", "c_h_avg", "c_d_avg", "c_a_avg"]


class SourceError(RuntimeError):
    pass


_last_request = [0.0]


def fetch(url, cfg=None, timeout=40, retries=2):
    """GET poli : user-agent explicite, délai minimal entre requêtes, aucune tentative de contournement.

    Un 401/403/429 est traité comme un refus : on n'insiste pas.
    """
    cfg = cfg or load_config()
    wait = cfg.get("delai_entre_requetes_s", 1.5) - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": cfg["user_agent"]}, timeout=timeout)
            _last_request[0] = time.time()
            if r.status_code in (401, 403, 429, 451):
                raise SourceError(f"{url} : accès refusé ({r.status_code}) — non contourné")
            if r.status_code == 404:
                raise SourceError(f"{url} : introuvable (404)")
            r.raise_for_status()
            return r
        except SourceError:
            raise
        except requests.RequestException as e:  # réseau : on réessaie modestement
            last = e
            time.sleep(2 * (attempt + 1))
    raise SourceError(f"{url} : échec réseau ({last})")


def match_id(league, date, home, away):
    key = f"{league}|{pd.Timestamp(date).date().isoformat()}|{home}|{away}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _parse_dates(df):
    d = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    t = df["Time"] if "Time" in df.columns else pd.Series(["15:00"] * len(df), index=df.index)
    t = t.fillna("15:00").astype(str)
    # Heures football-data = heure du Royaume-Uni
    ko = pd.to_datetime(d.dt.strftime("%Y-%m-%d") + " " + t, errors="coerce")
    ko = ko.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="shift_forward")
    return d.dt.normalize(), ko


def normalize(raw: pd.DataFrame, season: str | None = None) -> pd.DataFrame:
    raw = raw.copy()
    raw.columns = [str(c).replace("\u00ef\u00bb\u00bf", "").replace("\ufeff", "").strip() for c in raw.columns]
    raw = raw.dropna(subset=["Div", "HomeTeam", "AwayTeam", "Date"], how="any")
    keep = {k: v for k, v in COLMAP.items() if k in raw.columns}
    df = raw[list(keep)].rename(columns=keep)
    df = df.loc[:, ~df.columns.duplicated()]
    for c in NUMERIC:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # contrôle qualité : cote impossible -> vide (jamais corrigée à la main)
    for c in [c for c in NUMERIC if c.startswith(("o_", "c_"))]:
        df.loc[(df[c] <= 1.01) | (df[c] > 100), c] = np.nan
    for pre in ("o", "c"):
        for src in ("avg", "b365"):
            a, b = f"{pre}_over_{src}", f"{pre}_under_{src}"
            if a in df and b in df:
                book = 1 / df[a] + 1 / df[b]
                bad = (book < 0.98) | (book > 1.25)
                df.loc[bad, [a, b]] = np.nan
    if "referee" not in df.columns:
        df["referee"] = None
    df["date"], df["kickoff"] = _parse_dates(raw)
    df["season"] = season
    df["match_id"] = [match_id(l, d, h, a) for l, d, h, a in
                      zip(df.league, df.date, df.home, df.away)]
    df["home"] = df["home"].astype(str).str.strip()
    df["away"] = df["away"].astype(str).str.strip()
    return df.reset_index(drop=True)


def season_csv(league, season, cfg=None, refresh=False):
    """Fichier d'une saison (cache local ; la saison courante est rafraîchie si demandé)."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{season}_{league}.csv"
    if refresh or not path.exists():
        r = fetch(f"{BASE}/mmz4281/{season}/{league}.csv", cfg)
        path.write_bytes(r.content)
    return path


def load_history(leagues=None, seasons=None, cfg=None, refresh_current=False, log=None):
    cfg = cfg or load_config()
    leagues = leagues or list(cfg["ligues"])
    seasons = seasons or cfg["saisons_historiques"]
    frames, missing = [], []
    for s in seasons:
        for lg in leagues:
            try:
                p = season_csv(lg, s, cfg, refresh=refresh_current and s == cfg["saison_courante"])
                raw = pd.read_csv(p, encoding="latin-1", on_bad_lines="skip")
                if len(raw):
                    frames.append(normalize(raw, s))
            except (SourceError, pd.errors.ParserError, KeyError, ValueError) as e:
                missing.append((lg, s, str(e)[:160]))
    if log is not None:
        log.extend(missing)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(df):
        df = df.drop_duplicates("match_id").sort_values(["kickoff", "league"]).reset_index(drop=True)
    return df


def load_fixtures(cfg=None, path=None):
    """Matchs à venir avec cotes (fixtures.csv). Retourne (df, heure_de_capture_utc)."""
    cfg = cfg or load_config()
    if path:
        content = Path(path).read_bytes()
    else:
        content = fetch(f"{BASE}/fixtures.csv", cfg).content
    captured = datetime.now(timezone.utc)
    raw = pd.read_csv(io.BytesIO(content), encoding="latin-1", on_bad_lines="skip")
    df = normalize(raw, cfg["saison_courante"])
    df = df[df.league.isin(cfg["ligues"])].reset_index(drop=True)
    return df, captured


def odds_for(row, side, source="Avg"):
    """Cote du côté choisi selon la source de référence, avec repli B365. Retourne (cote, source)."""
    order = [source.lower(), "b365"] if source.lower() != "b365" else ["b365", "avg"]
    for src in order:
        v = row.get(f"o_{side}_{src}")
        if v is not None and not pd.isna(v) and v > 1.0:
            return float(v), src
    return None, None
