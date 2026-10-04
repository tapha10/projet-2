"""Backtest sans regard vers le futur : modèles M0 à M4 et références, saison par saison.

- M1 : réajusté pour chaque (ligue, jour) sur les seuls matchs antérieurs à ce jour.
- M2, M3 : entraînés sur les saisons STRICTEMENT antérieures à la saison testée (fenêtre glissante).
- M4 : poids issus de la perte log des saisons antérieures.
- Cote utilisée : cote d'avant-match (colonnes non « C » de football-data), comme au verrouillage ;
  la cote de clôture sert uniquement à mesurer l'écart avec la clôture.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import load_config
from .features import match_features
from .models import (M2Adjust, M3Logistic, m0_prob, m1_walkforward, m4_combine, m4_weights)
from .selection import build_combo, combo_summary, evaluate_match
from .settle import settle_combo
from .stats import brier, ece, log_loss, wilson, paired_logloss_test

MODELS = ["p_m0", "p_m1", "p_m2", "p_m3", "p_m3gbm", "p_m4"]


def add_m0(df):
    df = df.copy()
    df["p_m0"] = [m0_prob(o, u) for o, u in zip(df.o_over_avg, df.o_under_avg)]
    df["p_m0_close"] = [m0_prob(o, u) for o, u in zip(df.c_over_avg, df.c_under_avg)]
    return df


def build_base(hist: pd.DataFrame, cfg=None, seasons_test=None, progress=False):
    """Variables + M0 + M1 pour tous les matchs des saisons testées (avec historique antérieur)."""
    cfg = cfg or load_config()
    feats = match_features(hist, cfg.get("poids_saison_precedente_demi_vie_matchs", 6))
    feats = add_m0(feats)
    targets = feats if seasons_test is None else feats[feats.season.isin(seasons_test)]
    m1 = m1_walkforward(hist, targets, cfg)
    out = feats.merge(m1, on="match_id", how="left")
    out["y"] = ((out.fthg + out.ftag) > 2.5).astype(float)
    out.loc[out.fthg.isna(), "y"] = np.nan
    return out


def add_learned_models(base: pd.DataFrame, min_train=2000):
    """M2, M3 (logistique et GBM) et M4, entraînés saison par saison sur le passé uniquement."""
    df = base.copy()
    for c in ["p_m2", "p_m3", "p_m3gbm", "p_m4"]:
        df[c] = np.nan
    seasons = sorted(df.season.dropna().unique())
    weights_log = {}
    for s in seasons:
        train = df[(df.season < s) & df.y.notna() & df.p_m1.notna() & df.p_m0.notna()]
        test_idx = df.index[(df.season == s) & df.p_m1.notna()]
        if len(train) < min_train or len(test_idx) == 0:
            continue
        m2 = M2Adjust().fit(train)
        df.loc[test_idx, "p_m2"] = m2.p_over(df.loc[test_idx])
        train = train.copy()
        train["p_m2"] = m2.p_over(train)  # en-échantillon pour M2 ; M3 l'utilise comme variable
        tr3 = train.dropna(subset=["p_m2"])
        sub = df.loc[test_idx]
        ok = sub.p_m0.notna()
        if ok.any():
            m3 = M3Logistic().fit(tr3)
            df.loc[sub.index[ok], "p_m3"] = m3.p_over(sub[ok])
            g = M3Logistic(kind="gbm").fit(tr3)
            df.loc[sub.index[ok], "p_m3gbm"] = g.p_over(sub[ok])
        # M4 : poids selon la perte log sur la saison précédente (hors échantillon)
        prev = df[(df.season < s) & df.y.notna()]
        ll = {}
        for m in ["p_m0", "p_m1", "p_m2", "p_m3"]:
            d = prev.dropna(subset=[m])
            ll[m] = log_loss(d[m], d.y) if len(d) > 500 else np.nan
        w = m4_weights(ll)
        weights_log[s] = w
        if w:
            sub = df.loc[test_idx]
            df.loc[test_idx, "p_m4"] = [m4_combine({k: r[k] for k in w}, w) for _, r in sub.iterrows()]
    return df, weights_log


def model_metrics(df: pd.DataFrame, models=MODELS, mask=None):
    rows = []
    d0 = df[df.y.notna()] if mask is None else df[mask & df.y.notna()]
    common = d0.dropna(subset=[m for m in models if m in d0])
    for m in models:
        if m not in common or common.empty:
            continue
        p, y = common[m], common.y
        hit = ((p >= 0.5) == (y == 1)).mean()
        rows.append({"modele": m, "n": len(common), "logloss": log_loss(p, y), "brier": brier(p, y),
                     "ece": ece(p, y), "precision_cote_forte": hit})
    return pd.DataFrame(rows)


def simulate_selection(df: pd.DataFrame, model: str, cfg, rule=None, odds_source="Avg",
                       seuil=None, cote_min=None):
    """Applique les filtres de la section 4 et règle chaque sélection à mise fixe (1 unité)."""
    cfg = dict(cfg)
    if seuil is not None:
        cfg["seuil_valeur"] = seuil
    if cote_min is not None:
        cfg["cote_min"] = cote_min
    recs = []
    for _, r in df[df.y.notna()].iterrows():
        e = evaluate_match(r, r[model], cfg, odds_source, rule)
        if not e["retenu"]:
            continue
        win = (e["side"] == "over") == (r.y == 1)
        close = r.c_over_avg if e["side"] == "over" else r.c_under_avg
        p_close = r.p_m0_close if e["side"] == "over" else (1 - r.p_m0_close if pd.notna(r.p_m0_close) else np.nan)
        recs.append({**e, "date": r.date, "league": r.league, "season": r.season, "y": r.y,
                     "win": float(win), "pnl": (e["odds"] - 1) if win else -1.0,
                     "close_odds": close, "clv": (e["odds"] / close - 1) if pd.notna(close) else np.nan,
                     "p_close": p_close, "referee": r.referee,
                     "p_m0_side": r.p_m0 if e["side"] == "over" else 1 - r.p_m0})
    return pd.DataFrame(recs)


def references(sel: pd.DataFrame, df: pd.DataFrame, seed=0):
    """Références sur les mêmes matchs que la sélection : hasard, toujours plus, toujours moins, favori du marché."""
    if sel.empty:
        return {}
    m = df.set_index("match_id").loc[sel.match_id]
    y = m.y.to_numpy()
    rng = np.random.default_rng(seed)
    over_odds, under_odds = m.o_over_avg.to_numpy(), m.o_under_avg.to_numpy()

    def roi(win, odds):
        return float(np.nanmean(np.where(win, odds - 1, -1.0)))

    rand = rng.random(len(y)) < 0.5
    fav_over = m.p_m0.to_numpy() >= 0.5
    out = {
        "modele": {"taux": float(sel.win.mean()), "roi": float(sel.pnl.mean())},
        "hasard": {"taux": float(np.mean(rand == (y == 1))),
                   "roi": roi(rand == (y == 1), np.where(rand, over_odds, under_odds))},
        "toujours_plus": {"taux": float(np.mean(y == 1)), "roi": roi(y == 1, over_odds)},
        "toujours_moins": {"taux": float(np.mean(y == 0)), "roi": roi(y == 0, under_odds)},
        "favori_marche": {"taux": float(np.mean(fav_over == (y == 1))),
                          "roi": roi(fav_over == (y == 1), np.where(fav_over, over_odds, under_odds))},
        "proba_marche_cote_choisie": float(np.nanmean(sel.p_m0_side)),
        "proba_modele_moyenne": float(sel.p.mean()),
    }
    return out


def selection_summary(sel: pd.DataFrame):
    if sel.empty:
        return {"n": 0}
    n, k = len(sel), int(sel.win.sum())
    lo, hi = wilson(k, n)
    p_be = float((1 / sel.odds).mean())
    return {"n": n, "gagnes": k, "taux": k / n, "ic95": (lo, hi), "seuil_equilibre_moyen": p_be,
            "roi": float(sel.pnl.mean()), "cote_moyenne": float(sel.odds.mean()),
            "clv_moyen": float(sel.clv.mean()) if sel.clv.notna().any() else None,
            "part_bat_cloture": float((sel.clv > 0).mean()) if sel.clv.notna().any() else None,
            "p_modele_moyenne": float(sel.p.mean())}


def simulate_combos(sel: pd.DataFrame, size=5, key="ev"):
    """Combiné quotidien à partir des sélections du jour."""
    rows = []
    for d, day in sel.groupby("date"):
        legs, notes = build_combo(day.to_dict("records"), size, key)
        if not legs:
            continue
        res = ["win" if l["win"] == 1 else "loss" for l in legs]
        outcome, pay = settle_combo(res, [l["odds"] for l in legs])
        summ = combo_summary(legs)
        rows.append({"date": d, "n": len(legs), "cote": summ["cote"], "p_est": summ["p_estimee"],
                     "outcome": outcome, "pnl": (pay - 1) if outcome == "win" else -1.0})
    return pd.DataFrame(rows)


def breakdown(sel: pd.DataFrame, by: str):
    if sel.empty:
        return pd.DataFrame()
    g = sel.groupby(by)
    out = g.agg(n=("win", "size"), taux=("win", "mean"), roi=("pnl", "mean"), cote=("odds", "mean"),
                p=("p", "mean"))
    ci = [wilson(int(s.win.sum()), len(s)) for _, s in g]
    out["ic_bas"] = [c[0] for c in ci]; out["ic_haut"] = [c[1] for c in ci]
    return out.reset_index()


def compare(df, a, b):
    d = df.dropna(subset=[a, b, "y"])
    return paired_logloss_test(d[a], d[b], d.y)
