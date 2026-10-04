"""Modèles de probabilité « plus de 2,5 buts ».

M0 : cotes sans marge (référence).
M1 : Dixon-Coles (Poisson indépendant + correction des petits scores), forces d'attaque/défense
     pondérées dans le temps, avantage du terrain ; cible = mélange buts / xG si les xG existent.
M2 : M1 ajusté (repos, enjeu, absences chiffrées quand disponibles) — coefficients appris sur le passé.
M3 : régression logistique régularisée (puis gradient boosting en observation) sur M0/M1/M2 + variables.
M4 : combinaison pondérée (logits) selon la qualité récente mesurée (perte log).
Toute probabilité est P(plus de 2,5) ; P(moins) = 1 - P(plus).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson

from .odds import remove_margin

MAXG = 10


# ---------------------------------------------------------------- M0
def m0_prob(o_over, o_under, method="proportional"):
    if o_over is None or o_under is None or pd.isna(o_over) or pd.isna(o_under) or min(o_over, o_under) <= 1:
        return np.nan
    return remove_margin([o_over, o_under], method)[0]


# ---------------------------------------------------------------- M1
def dc_tau(x, y, lh, la, rho):
    t = np.ones_like(lh)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def p_over_from_lambdas(lh, la, rho=0.0, line=2.5):
    lh = np.atleast_1d(np.asarray(lh, float)); la = np.atleast_1d(np.asarray(la, float))
    g = np.arange(MAXG + 1)
    ph = poisson.pmf(g[None, :], lh[:, None])
    pa = poisson.pmf(g[None, :], la[:, None])
    mat = ph[:, :, None] * pa[:, None, :]
    # correction Dixon-Coles sur 0-0, 0-1, 1-0, 1-1
    mat[:, 0, 0] *= 1 - lh * la * rho
    mat[:, 0, 1] *= 1 + lh * rho
    mat[:, 1, 0] *= 1 + la * rho
    mat[:, 1, 1] *= 1 - rho
    mat = np.clip(mat, 0, None)
    mat /= mat.sum(axis=(1, 2), keepdims=True)
    tot = g[:, None] + g[None, :]
    under = mat[:, tot <= line].sum(axis=1)
    return 1 - under


class DixonColes:
    """Ajustement rapide (mises à jour multiplicatives de Maher, pondérées, avec rétrécissement)."""

    def __init__(self, half_life_days=180, xg_weight=0.5, shrink=3.0, iters=60):
        self.xi = np.log(2) / half_life_days
        self.xg_weight = xg_weight
        self.shrink = shrink
        self.iters = iters

    def fit(self, train: pd.DataFrame, ref_date):
        tr = train.dropna(subset=["fthg", "ftag"])
        teams = pd.Index(pd.unique(pd.concat([tr.home, tr.away])))
        self.teams = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = tr.home.map(self.teams).to_numpy(); ai = tr.away.map(self.teams).to_numpy()
        age = (pd.Timestamp(ref_date) - tr.date).dt.days.to_numpy()
        w = np.exp(-self.xi * age)
        gh = tr.fthg.to_numpy(float); ga = tr.ftag.to_numpy(float)
        if self.xg_weight > 0:
            xh = tr.hxg.to_numpy(float); xa = tr.axg.to_numpy(float)
            okx = ~np.isnan(xh) & ~np.isnan(xa)
            gh = np.where(okx, (1 - self.xg_weight) * gh + self.xg_weight * np.nan_to_num(xh), gh)
            ga = np.where(okx, (1 - self.xg_weight) * ga + self.xg_weight * np.nan_to_num(xa), ga)
        att = np.ones(n); dfn = np.ones(n)
        base_h = max(np.average(gh, weights=w), 0.1); base_a = max(np.average(ga, weights=w), 0.1)
        k = self.shrink
        for _ in range(self.iters):
            eh = base_h * dfn[ai]          # attente domicile hors attaque domicile
            ea = base_a * dfn[hi]
            num = np.bincount(hi, w * gh, n) + np.bincount(ai, w * ga, n) + k
            den = np.bincount(hi, w * eh, n) + np.bincount(ai, w * ea, n) + k
            att = num / den
            att /= att.mean()
            eh2 = base_h * att[hi]
            ea2 = base_a * att[ai]
            num = np.bincount(ai, w * gh, n) + np.bincount(hi, w * ga, n) + k
            den = np.bincount(ai, w * eh2, n) + np.bincount(hi, w * ea2, n) + k
            dfn = num / den
            dfn /= dfn.mean()
            lh = att[hi] * dfn[ai]; la = att[ai] * dfn[hi]
            base_h = np.sum(w * gh) / np.sum(w * lh); base_a = np.sum(w * ga) / np.sum(w * la)
        self.att, self.dfn, self.base_h, self.base_a = att, dfn, base_h, base_a
        # rho : vraisemblance pondérée sur les scores entiers, recherche sur grille
        lh = base_h * att[hi] * dfn[ai]; la = base_a * att[ai] * dfn[hi]
        x = tr.fthg.to_numpy(int); y = tr.ftag.to_numpy(int)
        best, self.rho = -np.inf, 0.0
        for rho in np.linspace(-0.2, 0.2, 21):
            t = dc_tau(x, y, lh, la, rho)
            if np.any(t <= 0):
                continue
            ll = np.sum(w * np.log(t))
            if ll > best:
                best, self.rho = ll, rho
        return self

    def lambdas(self, home, away):
        i, j = self.teams.get(home), self.teams.get(away)
        if i is None or j is None:
            return np.nan, np.nan
        return (self.base_h * self.att[i] * self.dfn[j], self.base_a * self.att[j] * self.dfn[i])

    def p_over(self, home, away):
        lh, la = self.lambdas(home, away)
        if np.isnan(lh):
            return np.nan
        return float(p_over_from_lambdas(lh, la, self.rho)[0])


def m1_walkforward(hist: pd.DataFrame, targets: pd.DataFrame, cfg) -> pd.DataFrame:
    """Probabilités M1 pour chaque match cible, ajusté uniquement sur les matchs antérieurs à sa date."""
    out = []
    window = pd.Timedelta(days=cfg.get("dc_fenetre_jours", 730))
    done = hist.dropna(subset=["fthg", "ftag"])
    for (lg, d), grp in targets.groupby(["league", "date"], sort=True):
        tr = done[(done.league == lg) & (done.date < d) & (done.date >= d - window)]
        if len(tr) < 60:
            continue
        m = DixonColes(cfg.get("dc_demi_vie_jours", 180), cfg.get("xg_weight", 0.5)).fit(tr, d)
        for _, r in grp.iterrows():
            lh, la = m.lambdas(r.home, r.away)
            p = np.nan if np.isnan(lh) else float(p_over_from_lambdas(lh, la, m.rho)[0])
            out.append({"match_id": r.match_id, "m1_lh": lh, "m1_la": la, "m1_rho": m.rho, "p_m1": p})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- M2
M2_COLS = ["rest_h_short", "rest_a_short", "ntp_h", "ntp_a", "frac_late", "abs_h", "abs_a"]


def m2_design(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["rest_h_short"] = (df.get("h_rest_days") <= 3).astype(float)
    X["rest_a_short"] = (df.get("a_rest_days") <= 3).astype(float)
    X["ntp_h"] = df.get("h_nothing_to_play", pd.Series(0, index=df.index)).fillna(0)
    X["ntp_a"] = df.get("a_nothing_to_play", pd.Series(0, index=df.index)).fillna(0)
    X["frac_late"] = (df.get("h_frac_season", pd.Series(0, index=df.index)).fillna(0) > 0.8).astype(float)
    # impact chiffré des absences (part des xG/buts de l'équipe absente) ; 0 si inconnu
    X["abs_h"] = df.get("abs_impact_h", pd.Series(0, index=df.index)).fillna(0)
    X["abs_a"] = df.get("abs_impact_a", pd.Series(0, index=df.index)).fillna(0)
    return X


class M2Adjust:
    """Multiplicateur du total de buts attendu : log(mu) = log(lh+la) + X·beta (Poisson avec décalage)."""

    def fit(self, df: pd.DataFrame, alpha=1.0):
        from sklearn.linear_model import PoissonRegressor
        d = df.dropna(subset=["m1_lh", "m1_la", "fthg", "ftag"])
        mu = (d.m1_lh + d.m1_la).to_numpy()
        y = (d.fthg + d.ftag).to_numpy(float)
        X = m2_design(d).to_numpy()
        reg = PoissonRegressor(alpha=alpha / max(len(d), 1) * 100, max_iter=300)
        reg.fit(X, y / mu, sample_weight=mu)   # équivalent à un décalage log(mu)
        self.coef = reg.coef_
        self.intercept = reg.intercept_
        return self

    def p_over(self, df: pd.DataFrame) -> np.ndarray:
        X = m2_design(df).to_numpy()
        mult = np.exp(X @ self.coef + self.intercept)
        lh = df.m1_lh.to_numpy() * mult; la = df.m1_la.to_numpy() * mult
        out = np.full(len(df), np.nan)
        ok = ~np.isnan(lh) & ~np.isnan(la)
        if ok.any():
            out[ok] = p_over_from_lambdas(lh[ok], la[ok], df.m1_rho.to_numpy()[ok].mean())
        return out


# ---------------------------------------------------------------- M3
def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


M3_FEATURES = ["lg_m0", "lg_m1", "lg_m2", "ew_over", "ew_tot", "ew_xg_tot", "rest_min",
               "ntp_any", "frac_season", "line_move"]


def m3_design(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["lg_m0"] = logit(df.p_m0)
    X["lg_m1"] = logit(df.p_m1)
    X["lg_m2"] = logit(df.get("p_m2", df.p_m1))
    X["ew_over"] = (df.h_ew_over + df.a_ew_over) / 2
    X["ew_tot"] = (df.h_ew_tot + df.a_ew_tot) / 2
    X["ew_xg_tot"] = (df.h_ew_xgf + df.h_ew_xga + df.a_ew_xgf + df.a_ew_xga) / 2
    X["rest_min"] = np.minimum(df.h_rest_days, df.a_rest_days).clip(upper=14)
    X["ntp_any"] = np.maximum(df.get("h_nothing_to_play", 0), df.get("a_nothing_to_play", 0))
    X["frac_season"] = df.get("h_frac_season", np.nan)
    X["line_move"] = np.nan  # mouvement de cote : disponible seulement en temps réel (snapshots)
    return X


class M3Logistic:
    def __init__(self, C=0.5, kind="logistic"):
        self.C, self.kind = C, kind

    def fit(self, df: pd.DataFrame, features=None):
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        self.features = features or M3_FEATURES
        X = m3_design(df)[self.features]
        X = X.loc[:, X.notna().any()]
        self.features = list(X.columns)
        y = ((df.fthg + df.ftag) > 2.5).astype(int)
        if self.kind == "gbm":
            from sklearn.ensemble import HistGradientBoostingClassifier
            clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                 l2_regularization=1.0, min_samples_leaf=80)
            self.pipe = make_pipeline(SimpleImputer(strategy="median"), clf)
        else:
            from sklearn.linear_model import LogisticRegression
            self.pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                      LogisticRegression(C=self.C, max_iter=500))
        self.pipe.fit(X, y)
        return self

    def p_over(self, df):
        return self.pipe.predict_proba(m3_design(df)[self.features])[:, 1]


# ---------------------------------------------------------------- M4
def m4_weights(recent_logloss: dict, temperature=50.0):
    """Poids softmax(-T * perte log récente) ; un modèle sans mesure récente est exclu."""
    keys = [k for k, v in recent_logloss.items() if v is not None and not np.isnan(v)]
    if not keys:
        return {}
    ll = np.array([recent_logloss[k] for k in keys])
    w = np.exp(-temperature * (ll - ll.min()))
    w /= w.sum()
    return dict(zip(keys, w))


def m4_combine(probs: dict, weights: dict):
    z = 0.0; tot = 0.0
    for k, w in weights.items():
        p = probs.get(k)
        if p is None or np.isnan(p):
            continue
        z += w * logit(p); tot += w
    return float(sigmoid(z / tot)) if tot > 0 else np.nan
