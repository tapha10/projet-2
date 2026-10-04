"""Variables avant-match, sans regard vers le futur.

Règle anti-fuite : pour un match à la date D, seules les rencontres terminées à une date
strictement antérieure à D sont utilisées (les autres matchs du même jour sont ignorés).
Mélange début de saison : fenêtres glissantes « toutes saisons confondues » pondérées
exponentiellement ; les matchs de la saison précédente perdent naturellement du poids à
mesure que la saison avance (demi-vie configurable, en matchs).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def team_long(df: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par équipe et par match (matchs terminés uniquement)."""
    done = df.dropna(subset=["fthg", "ftag"])
    base = ["match_id", "league", "season", "date"]
    h = done[base].copy()
    h["team"], h["opp"], h["is_home"] = done.home, done.away, 1
    h["gf"], h["ga"], h["xgf"], h["xga"] = done.fthg, done.ftag, done.hxg, done.axg
    h["sf"], h["sa"] = done.hs, done.as_
    a = done[base].copy()
    a["team"], a["opp"], a["is_home"] = done.away, done.home, 0
    a["gf"], a["ga"], a["xgf"], a["xga"] = done.ftag, done.fthg, done.axg, done.hxg
    a["sf"], a["sa"] = done.as_, done.hs
    out = pd.concat([h, a], ignore_index=True)
    out["tot"] = out.gf + out.ga
    out["over"] = (out.tot > 2.5).astype(float)
    out["pts"] = np.select([out.gf > out.ga, out.gf == out.ga], [3, 1], 0)
    return out.sort_values(["team", "date"]).reset_index(drop=True)


def _ewm_prev(g: pd.Series, halflife: float) -> pd.Series:
    """Moyenne pondérée exponentielle des matchs PRÉCÉDENTS (décalage d'un match)."""
    return g.shift(1).ewm(halflife=halflife, min_periods=1, ignore_na=True).mean()


def team_state(df: pd.DataFrame, halflife: float = 6.0) -> pd.DataFrame:
    """État de chaque équipe AVANT chacun de ses matchs (index = match_id, team)."""
    tl = team_long(df)
    g = tl.groupby("team", sort=False)
    st = tl[["match_id", "team", "league", "season", "date", "is_home", "pts"]].copy()
    for c in ["gf", "ga", "xgf", "xga", "over", "tot", "sf", "sa"]:
        st[f"ew_{c}"] = g[c].transform(lambda s: _ewm_prev(s, halflife))
    st["n_hist"] = g.cumcount()
    # matchs joués dans la saison et le championnat en cours, avant ce match
    st["played_season"] = tl.groupby(["team", "league", "season"]).cumcount()
    st["prev_date"] = g["date"].shift(1)
    st["rest_days"] = (st.date - st.prev_date).dt.days
    # classement avant le match (points cumulés dans la saison/ligue, matchs précédents)
    st["pts_before"] = tl.groupby(["team", "league", "season"])["pts"].transform(
        lambda s: s.shift(1).fillna(0).cumsum())
    return st


def standings_context(st: pd.DataFrame) -> pd.DataFrame:
    """Enjeu approché : écart au leader et à la 3e place avant la fin (zone de relégation), avancement.

    Les totaux des autres équipes sont ceux connus au matin du jour du match (matchs des jours précédents).
    """
    st = st.copy()
    n_teams = st.groupby(["league", "season"])["team"].transform("nunique")
    total_games = 2 * (n_teams - 1)
    st["frac_season"] = st.played_season / total_games
    remaining = (total_games - st.played_season).clip(lower=0)
    gap_top = np.full(len(st), np.nan)
    gap_rel = np.full(len(st), np.nan)
    pos = {ix: k for k, ix in enumerate(st.index)}
    for _, grp in st.groupby(["league", "season"], sort=False):
        latest = {}
        for _, day in grp.sort_values("date").groupby("date", sort=True):
            vals = sorted(latest.values(), reverse=True)
            if len(vals) >= 4:
                for ix, pb in zip(day.index, day.pts_before):
                    gap_top[pos[ix]] = vals[0] - pb
                    gap_rel[pos[ix]] = pb - vals[-3]
            for t, pb, p in zip(day.team, day.pts_before, day.pts):
                latest[t] = pb + p
    st["gap_top"], st["gap_releg"] = gap_top, gap_rel
    max_gain = 3 * remaining
    st["nothing_to_play"] = ((st.gap_top > max_gain) & (st.gap_releg > max_gain)).astype(float)
    st.loc[st.gap_top.isna(), "nothing_to_play"] = np.nan
    return st


def match_features(df: pd.DataFrame, halflife: float = 6.0, with_context=True) -> pd.DataFrame:
    """Une ligne par match avec les variables domicile (h_) et extérieur (a_) connues avant le match.

    df doit contenir l'historique terminé ET éventuellement les matchs à venir (scores vides) :
    les matchs à venir reçoivent l'état issu des seuls matchs terminés antérieurs.
    """
    done = df.dropna(subset=["fthg", "ftag"])
    upcoming = df[df.fthg.isna() | df.ftag.isna()]
    st = team_state(done, halflife)
    if with_context:
        st = standings_context(st)
    cols = [c for c in st.columns if c.startswith("ew_")] + [
        "n_hist", "played_season", "rest_days", "pts_before"] + (
        ["frac_season", "gap_top", "gap_releg", "nothing_to_play"] if with_context else [])
    key = st.set_index(["match_id", "team"])[cols]
    out = df.copy()
    h = key.reindex(list(zip(out.match_id, out.home)))
    a = key.reindex(list(zip(out.match_id, out.away)))
    for c in cols:
        out[f"h_{c}"] = h[c].values
        out[f"a_{c}"] = a[c].values
    if len(upcoming):
        out = _fill_upcoming(out, done, st, cols, halflife)
    return out


def _fill_upcoming(out, done, st, cols, halflife):
    """Pour les matchs à venir : état après le dernier match terminé de chaque équipe (date < date du match)."""
    tl = team_long(done)
    for i in out.index[out.fthg.isna() | out.ftag.isna()]:
        row = out.loc[i]
        for side, team in (("h", row.home), ("a", row.away)):
            hist = tl[(tl.team == team) & (tl.date < row.date)]
            if hist.empty:
                continue
            for c in ["gf", "ga", "xgf", "xga", "over", "tot", "sf", "sa"]:
                s = hist[c]
                out.at[i, f"{side}_ew_{c}"] = s.ewm(halflife=halflife, ignore_na=True).mean().iloc[-1] \
                    if s.notna().any() else np.nan
            out.at[i, f"{side}_n_hist"] = len(hist)
            cur = hist[(hist.league == row.league) & (hist.season == row.season)]
            out.at[i, f"{side}_played_season"] = len(cur)
            out.at[i, f"{side}_rest_days"] = (row.date - hist.date.iloc[-1]).days
            out.at[i, f"{side}_pts_before"] = float(cur.pts.sum())
    return out


def eligible_played(row, min_matches=5, rule="strict"):
    """Filtre « plus de 5 matchs joués » : strict -> > min (>= 6) ; au_moins -> >= min."""
    h, a = row.get("h_played_season"), row.get("a_played_season")
    if h is None or a is None or pd.isna(h) or pd.isna(a):
        return False
    if rule == "strict":
        return h > min_matches and a > min_matches
    return h >= min_matches and a >= min_matches
