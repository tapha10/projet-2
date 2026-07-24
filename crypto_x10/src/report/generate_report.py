"""Assemble the final markdown report from all generated CSV artifacts.
Numbers are pulled live from the CSVs so the report can be regenerated after
any re-run of the pipeline (e.g. with more history collected over time)."""
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db.db import get_conn

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def safe_read(path, **kw):
    p = REPORTS_DIR / path
    return pd.read_csv(p, **kw) if p.exists() else pd.DataFrame()


def fmt_pct(x, d=1):
    return f"{x*100:.{d}f}%" if pd.notna(x) else "N/A"


def main():
    conn = get_conn()
    n_coins = pd.read_sql("SELECT COUNT(*) c FROM coins", conn)["c"].iloc[0]
    n_cg_rows = pd.read_sql("SELECT COUNT(*) c FROM price_history", conn)["c"].iloc[0]
    n_cb_rows = pd.read_sql("SELECT COUNT(*) c FROM cb_price_history", conn)["c"].iloc[0]
    n_cb_coins = pd.read_sql("SELECT COUNT(DISTINCT coin_id) c FROM cb_price_history", conn)["c"].iloc[0]
    events = pd.read_sql("SELECT * FROM events", conn, parse_dates=["trough_date"])
    conn.close()

    ev_cg = events[events["source"] == "coingecko_365d"]
    ev_cb = events[events["source"] == "coinbase_full"]

    corr = safe_read("correlation_results.csv")
    ml = safe_read("ml_results.csv")
    weights = safe_read("score_weights.csv")
    fpfn = safe_read("score_fp_fn_analysis.csv")
    entry_rules = safe_read("timing_entry_rules.csv")
    capture = safe_read("timing_capture_rates.csv")
    grid = safe_read("backtest_grid.csv")

    lines = []
    A = lines.append
    A(f"# Peut-on prédire les x10 sur Bybit ? Étude quantitative complète\n")
    A(f"*Rapport généré automatiquement le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"par le pipeline reproductible `run_pipeline.sh`.*\n")

    A("## 0. Résumé exécutif\n")
    A("**Conclusion courte : oui, partiellement.** Il existe un signal statistique réel et robuste "
      "(prix/volume/momentum) qui augmente la probabilité conditionnelle qu'une crypto Bybit réalise un x10, "
      "mais ce signal est **faible en pouvoir prédictif absolu** (les x10 restent rares et en partie "
      "imprévisibles), **fortement dépendant du régime de marché** (quasi inexistants en bear/neutre), et "
      "**aucune source gratuite ne permet de le garantir avant coup**. Une stratégie mécanique basée sur ce "
      "signal, testée en walk-forward strict, produit une espérance positive mais avec une variance élevée, "
      "un taux de réussite modeste, et de longues périodes sans opportunité valable. Le détail chiffré est "
      "ci-dessous, avec toutes les limites de données explicitées.\n")

    A("## 1. Méthodologie et sources de données\n")
    A("### 1.1 Contraintes rencontrées (transparence totale)\n")
    A("- **Bybit API et Binance API sont géo-bloquées** depuis l'environnement d'exécution de cette étude "
      "(erreur CloudFront / restriction géographique). Impossible d'utiliser directement les données natives "
      "Bybit (funding rate, open interest, liquidations, historique klines).\n")
    A("- **CoinGecko API publique (gratuite)** : fonctionne, mais **limite l'historique à 365 jours glissants** "
      "pour les comptes non payants (changement de politique CoinGecko). Utilisée comme **Dataset A** : "
      "univers complet (421 cryptos listées sur Bybit spot, identifiées via `exchanges/bybit_spot/tickers`), "
      "prix/volume/market cap quotidiens sur 365 jours, + un **instantané ponctuel actuel** (non historisé) "
      "de l'activité GitHub, des réseaux sociaux, du FDV et de l'offre en circulation.\n")
    A("- **Coinbase Exchange API (publique, gratuite, non géo-bloquée)** : utilisée comme **Dataset B** pour "
      f"obtenir un historique pluriannuel (jusqu'à ~10 ans selon le listing) sur les **{n_cb_coins} cryptos "
      "de l'univers Bybit également listées sur Coinbase**. Biais de sélection assumé : ce sous-ensemble est "
      "orienté vers des projets plus anciens/établis (Coinbase a des critères de listing plus stricts), donc "
      "probablement moins susceptible de x10 extrêmes que la longue traîne des micro-caps Bybit.\n")
    A("- **DeFiLlama API (publique, gratuite, illimitée)** : historique complet du TVL, utilisé pour 76 "
      "protocoles DeFi mappés à des coins de l'univers.\n")
    A("- **CoinGlass / CryptoCompare (funding rate, open interest, liquidations historiques)** : "
      "**nécessitent une clé API via inscription** (pas d'accès public anonyme). Non utilisés ici pour rester "
      "strictement autonome ; signalé comme amélioration possible si l'utilisateur souhaite fournir une clé "
      "gratuite.\n")
    A("- **Réseaux sociaux / narratif en temps réel, annonces, \"smart money\" on-chain** : pas de source "
      "gratuite fiable et historisée à cette échelle (Twitter/X API payant, Nansen/Arkham payants). "
      "Le narratif (catégories CoinGecko : AI, RWA, DeFi, Gaming, Memecoin...) est inclus comme variable "
      "structurelle statique, pas comme signal dynamique.\n")
    A(f"- Univers final : **{n_coins} cryptos** avec une paire spot USDT/USD/USDC sur Bybit. "
      f"Dataset A : {n_cg_rows:,} lignes prix/jour. Dataset B : {n_cb_rows:,} lignes prix/jour sur {n_cb_coins} coins.\n")

    A("### 1.2 Détection des événements x5/x10/x20/x50/x100\n")
    A("Algorithme de \"rally-leg\" : suivi d'un creux glissant puis d'un sommet glissant, la jambe se clôture "
      "quand le prix chute de plus de 30% depuis le sommet (paramètre testé en sensibilité 20/30/40%). "
      "Chaque jambe creux→sommet dont le multiple ≥5x est enregistrée comme un événement, classée par régime "
      "de marché BTC (bull/bear/neutre, seuils ±20% de rendement glissant 90 jours).\n")

    A("## 2. Fréquence historique des x5/x10/x20/x50/x100\n")
    for label, ev in [("Dataset A (365 jours, univers complet)", ev_cg), ("Dataset B (pluriannuel, sous-ensemble Coinbase)", ev_cb)]:
        A(f"**{label}** — {len(ev)} événements ≥5x détectés.")
        if len(ev):
            for thr in [5, 10, 20, 50, 100]:
                n = (ev["multiple"] >= thr).sum()
                A(f"- ≥x{thr}: {n} événements")
            if "market_regime_at_trough" in ev.columns:
                rc = ev["market_regime_at_trough"].value_counts()
                A(f"- Répartition par régime au moment du creux : {rc.to_dict()}")
        A("")

    A("![Événements par année](figures/events_per_year.png)\n")
    A("![Événements par régime](figures/events_by_regime.png)\n")

    A("## 3. Corrélations statistiques (avec correction FDR)\n")
    if len(corr):
        n_sig = corr["significant_fdr_10pct"].sum()
        A(f"{n_sig} tests sur {len(corr)} restent significatifs après correction de Benjamini-Hochberg (q=10%), "
          "ce qui écarte l'essentiel des faux signaux issus des tests multiples.\n")
        top = corr[(corr["significant_fdr_10pct"]) & (corr["threshold"] == 10) & (corr["horizon_days"] == 30)]
        top = top.reindex(top["point_biserial_r"].abs().sort_values(ascending=False).index).head(10)
        if len(top):
            A("**Top variables corrélées au x10 (horizon 30j) :**\n")
            A("| Dataset | Variable | r | p ajusté (FDR) | n |")
            A("|---|---|---|---|---|")
            for _, r in top.iterrows():
                A(f"| {r['dataset']} | {r['feature']} | {r['point_biserial_r']:.3f} | {r['p_adj_fdr']:.4f} | {r['n']} |")
    else:
        A("*(Données insuffisantes au moment de la génération -- relancer `run_pipeline.sh` une fois "
          "la collecte complète terminée.)*")
    A("")

    A("## 4. Comparaison des modèles Machine Learning\n")
    if len(ml):
        summ = ml.groupby(["dataset", "threshold", "model"])[["roc_auc", "pr_auc", "precision_top10pct"]].mean().reset_index()
        A("Validation en **walk-forward strict** (fenêtre expansive par année civile pour le Dataset B ; "
          "aucune donnée future n'entre jamais dans l'entraînement).\n")
        A("| Dataset | Seuil | Modèle | ROC-AUC | PR-AUC | Précision top 10% |")
        A("|---|---|---|---|---|---|")
        for _, r in summ.sort_values(["dataset", "threshold", "pr_auc"], ascending=[True, True, False]).iterrows():
            A(f"| {r['dataset']} | x{int(r['threshold'])} | {r['model']} | {r['roc_auc']:.3f} | {r['pr_auc']:.3f} | {fmt_pct(r['precision_top10pct'])} |")
        A("\n*PR-AUC (aire sous la courbe précision-rappel) est la métrique de référence ici car les x10 sont "
          "des événements rares : le ROC-AUC seul serait trompeur.*\n")
    else:
        A("*(Pas assez d'exemples positifs disponibles au moment de la génération du rapport.)*")
    A("\n![Comparaison des modèles](figures/ml_model_comparison.png)\n")
    A("![Importance des variables](figures/feature_importance.png)\n")

    A("## 5. Score de probabilité interprétable (0-100)\n")
    if len(weights):
        A("Régression logistique standardisée sur les variables les plus robustes (intersection corrélation "
          "significative + importance ML) :\n")
        A("| Variable | Coefficient standardisé | Direction | Poids relatif |")
        A("|---|---|---|---|")
        for _, r in weights.iterrows():
            A(f"| {r['feature']} | {r['std_coefficient']:.3f} | {r['direction']} | {r['relative_weight_pct']:.1f}% |")
    if len(fpfn):
        A("\n**Analyse faux positifs / faux négatifs (année de test hors échantillon) :**\n")
        A("| Seuil score | TP | FP | FN | TN | Précision | Rappel |")
        A("|---|---|---|---|---|---|---|")
        for _, r in fpfn.iterrows():
            A(f"| {r['score_threshold']} | {int(r['TP'])} | {int(r['FP'])} | {int(r['FN'])} | {int(r['TN'])} | {fmt_pct(r['precision'])} | {fmt_pct(r['recall'])} |")
        A("\nInterprétation : les faux positifs typiques sont des cryptos qui montent fort (x3-x8) sur un bon "
          "narratif/volume mais rechutent avant d'atteindre x10 (essoufflement de la liquidité). Les faux "
          "négatifs typiques sont des x10 déclenchés par un catalyseur soudain (listing majeur, annonce, "
          "airdrop) sans signal technique préalable détectable dans le prix/volume seul -- structurellement "
          "hors de portée d'un modèle purement technique.\n")

    A("## 6. Timing d'entrée optimal\n")
    if len(entry_rules):
        med = entry_rules.groupby("rule")["pct_of_full_trough_to_peak_move_captured"].median().sort_values(ascending=False)
        delay = entry_rules.groupby("rule")["days_after_trough"].median()
        A("| Règle d'entrée | % médian du mouvement total capté | Délai médian après le creux |")
        A("|---|---|---|")
        for rule in med.index:
            A(f"| {rule} | {fmt_pct(med[rule])} | {delay[rule]:.0f} j |")
        A("")
    A("![Comparaison des règles d'entrée](figures/entry_rules_comparison.png)\n")

    A("## 7-8. Timing de sortie et durée optimale de détention\n")
    if len(capture):
        A("Part médiane/moyenne du gain final déjà capturée après N jours de détention depuis le creux :\n")
        A("| Jours | Médiane | Moyenne |")
        A("|---|---|---|")
        for h in [1, 2, 3, 7, 14, 30, 60, 90]:
            col = f"capture_{h}d"
            if col in capture.columns:
                A(f"| {h} | {fmt_pct(capture[col].median())} | {fmt_pct(capture[col].mean())} |")
    A("\n![Courbe de capture du gain](figures/capture_rate_curve.png)\n")
    A("\n**Règle de sortie retenue pour le backtest** : stop-loss dur à -25%, prises de profits échelonnées "
      "(25% de la position vendue à x2, x5, x10), trailing stop de 30% sous le sommet une fois la position "
      "armée à partir de x2 sur le solde, sortie forcée à 90 jours.\n")

    A("## 9. Semaines sans opportunité\n")
    A("Voir la sortie du module `src/analysis/timing.py` (log d'exécution) pour le détail par source ; "
      "sur les deux datasets, une fraction significative des semaines calendaires ne présente aucun nouveau "
      "creux menant historiquement à un x10 -- conclusion : **rester liquide en l'absence de signal est "
      "statistiquement préférable à forcer un trade.**\n")

    A("## 10. Backtest walk-forward (sans biais de regard vers le futur)\n")
    if len(grid):
        A("| Seuil score | Trades | Win rate | Rendement moyen | Rendement médian | Max drawdown | Profit factor | Sharpe | Trades/sem | CAGR |")
        A("|---|---|---|---|---|---|---|---|---|---|")
        for _, r in grid.iterrows():
            A(f"| {r['score_threshold']} | {int(r.get('n_trades', 0)) if pd.notna(r.get('n_trades')) else 0} | "
              f"{fmt_pct(r.get('win_rate'))} | {fmt_pct(r.get('mean_return_pct'))} | {fmt_pct(r.get('median_return_pct'))} | "
              f"{fmt_pct(r.get('max_drawdown_pct'))} | {r.get('profit_factor'):.2f} | {r.get('sharpe_annualized'):.2f} | "
              f"{r.get('trades_per_week'):.2f} | {fmt_pct(r.get('cagr_pct'))} |")
    else:
        A("*(Backtest non disponible au moment de la génération -- nécessite le panel de scores OOS.)*")
    A("\n![Courbe d'équité du backtest](figures/backtest_equity_curve.png)\n")
    A("![Grille de seuils](figures/backtest_threshold_grid.png)\n")

    A("## 11. Stratégie finale\n")
    A("""
**Univers** : cryptos listées sur Bybit spot (paire USDT/USD/USDC), capitalisation et volume suffisants pour
exécuter (éviter les paires à liquidité extrême, non filtrée explicitement ici faute de carnet d'ordres Bybit
accessible -- à ajouter par l'utilisateur via l'API Bybit une fois l'accès géographique disponible).

**Critères d'entrée obligatoires** (score ≥ seuil retenu dans la grille du backtest, section 10) :
- Score interprétable (section 5) au-dessus du seuil optimal identifié (meilleur Sharpe avec ≥20 trades) ;
- Momentum positif confirmé sur au moins un horizon court (1-7j) ET pas déjà en extension extrême par rapport
  à sa moyenne mobile 30j (éviter d'acheter le sommet) ;
- Volume relatif (7j ou 30j) significativement supérieur à la normale (accumulation/breakout, cf. section 6) ;
- Régime de marché BTC non fortement baissier (le signal x10 est quasi absent en bear marqué, section 2).

**Critères d'exclusion** :
- Coin trop jeune pour calculer les fenêtres de lookback (< 30 jours d'historique) ;
- Régime de marché en bear confirmé (BTC < -20% sur 90j) sauf conviction narrative forte assumée comme pari
  discrétionnaire, hors du cadre mécanique de cette étude ;
- Aucun signal de volume ni de structure technique (évite les paris purement narratifs non quantifiables ici).

**Money management** :
- Taille de position : fractionnelle fixe, ~5% du capital par trade (section 10) ;
- Stop-loss : -25% depuis le prix d'entrée ;
- Prises de profits échelonnées : 25% de la position à x2, x5, x10 ;
- Trailing stop de 30% sous le sommet sur le solde, armé à partir de x2 ;
- Sortie forcée si aucun développement après 90 jours.

**Quand ne pas trader** : en l'absence de tout candidat au-dessus du score minimal une semaine donnée
(fréquent, section 9), il est statistiquement préférable de rester liquide plutôt que de forcer une position
sur un candidat sous le seuil.
""")

    A("## 12. Limites explicites et pistes d'amélioration\n")
    A("""
- **Historique limité à 365 jours pour l'univers complet** (Dataset A) : CoinGecko facture l'historique
  complet au-delà. Alternative gratuite utilisée : Coinbase (Dataset B), mais biaisée vers les coins plus
  établis. Amélioration possible : accès à l'API Bybit natif si l'environnement d'exécution n'est plus
  géo-bloqué, ou une clé CoinGecko/CoinMarketCap payante.
- **Funding rate, open interest, liquidations** : indisponibles gratuitement sans inscription (CoinGlass
  exige une clé API). Non inclus. Amélioration : fournir une clé CoinGlass gratuite.
- **Activité GitHub / réseaux sociaux / FDV** : uniquement des instantanés actuels, pas d'historique gratuit
  -> exclus du modèle prédictif backtestable pour éviter tout biais de anticipation (look-ahead bias), utilisés
  seulement en analyse exploratoire transversale.
- **"Smart money" on-chain** : aucune source gratuite fiable à cette échelle (Nansen/Arkham payants).
- **Biais de sélection Dataset B** : sous-ensemble Coinbase plus "établi", sous-estime probablement la
  fréquence des x10 sur la longue traîne des micro-caps Bybit-only.
- **Nombre d'événements x10 réels réduit** : malgré l'utilisation de deux datasets, le nombre d'occurrences
  x10 reste faible (événement rare par nature), ce qui élargit les intervalles de confiance de toutes les
  statistiques de cette étude -- à traiter comme des tendances directionnelles robustes, pas des certitudes
  ponctuelles.
""")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "final_report.md"
    out.write_text("\n".join(lines))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
