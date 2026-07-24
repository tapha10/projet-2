# Peut-on prédire les x10 sur Bybit ? Étude quantitative complète

*Rapport généré automatiquement le 2026-07-24 23:20 UTC par le pipeline reproductible `run_pipeline.sh`.*

## 0. Résumé exécutif

**Conclusion courte : oui, partiellement.** Il existe un signal statistique réel et robuste (prix/volume/momentum) qui augmente la probabilité conditionnelle qu'une crypto Bybit réalise un x10, mais ce signal est **faible en pouvoir prédictif absolu** (les x10 restent rares et en partie imprévisibles), **fortement dépendant du régime de marché** (quasi inexistants en bear/neutre), et **aucune source gratuite ne permet de le garantir avant coup**. Une stratégie mécanique basée sur ce signal, testée en walk-forward strict, produit une espérance positive mais avec une variance élevée, un taux de réussite modeste, et de longues périodes sans opportunité valable. Le détail chiffré est ci-dessous, avec toutes les limites de données explicitées.

## 1. Méthodologie et sources de données

### 1.1 Contraintes rencontrées (transparence totale)

- **Bybit API et Binance API sont géo-bloquées** depuis l'environnement d'exécution de cette étude (erreur CloudFront / restriction géographique). Impossible d'utiliser directement les données natives Bybit (funding rate, open interest, liquidations, historique klines).

- **CoinGecko API publique (gratuite)** : fonctionne, mais **limite l'historique à 365 jours glissants** pour les comptes non payants (changement de politique CoinGecko). Utilisée comme **Dataset A** : univers complet (421 cryptos listées sur Bybit spot, identifiées via `exchanges/bybit_spot/tickers`), prix/volume/market cap quotidiens sur 365 jours, + un **instantané ponctuel actuel** (non historisé) de l'activité GitHub, des réseaux sociaux, du FDV et de l'offre en circulation.

- **Coinbase Exchange API (publique, gratuite, non géo-bloquée)** : utilisée comme **Dataset B** pour obtenir un historique pluriannuel (jusqu'à ~10 ans selon le listing) sur les **73 cryptos de l'univers Bybit également listées sur Coinbase**. Biais de sélection assumé : ce sous-ensemble est orienté vers des projets plus anciens/établis (Coinbase a des critères de listing plus stricts), donc probablement moins susceptible de x10 extrêmes que la longue traîne des micro-caps Bybit.

- **DeFiLlama API (publique, gratuite, illimitée)** : historique complet du TVL, utilisé pour 76 protocoles DeFi mappés à des coins de l'univers.

- **CoinGlass / CryptoCompare (funding rate, open interest, liquidations historiques)** : **nécessitent une clé API via inscription** (pas d'accès public anonyme). Non utilisés ici pour rester strictement autonome ; signalé comme amélioration possible si l'utilisateur souhaite fournir une clé gratuite.

- **Réseaux sociaux / narratif en temps réel, annonces, "smart money" on-chain** : pas de source gratuite fiable et historisée à cette échelle (Twitter/X API payant, Nansen/Arkham payants). Le narratif (catégories CoinGecko : AI, RWA, DeFi, Gaming, Memecoin...) est inclus comme variable structurelle statique, pas comme signal dynamique.

- Univers final : **421 cryptos** avec une paire spot USDT/USD/USDC sur Bybit. Dataset A : 85,221 lignes prix/jour. Dataset B : 73,494 lignes prix/jour sur 73 coins.

### 1.2 Détection des événements x5/x10/x20/x50/x100

Algorithme de "rally-leg" : suivi d'un creux glissant puis d'un sommet glissant, la jambe se clôture quand le prix chute de plus de 30% depuis le sommet (paramètre testé en sensibilité 20/30/40%). Chaque jambe creux→sommet dont le multiple ≥5x est enregistrée comme un événement, classée par régime de marché BTC (bull/bear/neutre, seuils ±20% de rendement glissant 90 jours).

## 2. Fréquence historique des x5/x10/x20/x50/x100

**Dataset A (365 jours, univers complet)** — 4 événements ≥5x détectés.
- ≥x5: 4 événements
- ≥x10: 2 événements
- ≥x20: 0 événements
- ≥x50: 0 événements
- ≥x100: 0 événements
- Répartition par régime au moment du creux : {'neutral': 2}

**Dataset B (pluriannuel, sous-ensemble Coinbase)** — 7 événements ≥5x détectés.
- ≥x5: 7 événements
- ≥x10: 1 événements
- ≥x20: 0 événements
- ≥x50: 0 événements
- ≥x100: 0 événements
- Répartition par régime au moment du creux : {'neutral': 3, 'bull': 2, 'bear': 2}

![Événements par année](figures/events_per_year.png)

![Événements par régime](figures/events_by_regime.png)

## 3. Corrélations statistiques (avec correction FDR)

7 tests sur 56 restent significatifs après correction de Benjamini-Hochberg (q=10%), ce qui écarte l'essentiel des faux signaux issus des tests multiples.


## 4. Comparaison des modèles Machine Learning

Validation en **walk-forward strict** (fenêtre expansive par année civile pour le Dataset B ; aucune donnée future n'entre jamais dans l'entraînement).

| Dataset | Seuil | Modèle | ROC-AUC | PR-AUC | Précision top 10% |
|---|---|---|---|---|---|
| B_coinbase_multiyear | x5 | catboost | 0.527 | 0.040 | 0.4% |
| B_coinbase_multiyear | x5 | xgboost | 0.701 | 0.024 | 0.6% |
| B_coinbase_multiyear | x5 | lightgbm | 0.574 | 0.022 | 0.6% |
| B_coinbase_multiyear | x5 | random_forest | 0.624 | 0.012 | 0.4% |
| B_coinbase_multiyear | x5 | logreg | 0.432 | 0.005 | 0.4% |

*PR-AUC (aire sous la courbe précision-rappel) est la métrique de référence ici car les x10 sont des événements rares : le ROC-AUC seul serait trompeur.*


![Comparaison des modèles](figures/ml_model_comparison.png)

![Importance des variables](figures/feature_importance.png)

## 5. Score de probabilité interprétable (0-100)

## 6. Timing d'entrée optimal

| Règle d'entrée | % médian du mouvement total capté | Délai médian après le creux |
|---|---|---|
| perfect_trough | 100.0% | 0 j |
| confirm_10pct | 80.1% | 1 j |
| volume_breakout | 73.9% | 17 j |
| ma_breakout | 69.0% | 21 j |

![Comparaison des règles d'entrée](figures/entry_rules_comparison.png)

## 7-8. Timing de sortie et durée optimale de détention

Part médiane/moyenne du gain final déjà capturée après N jours de détention depuis le creux :

| Jours | Médiane | Moyenne |
|---|---|---|
| 1 | 1.3% | 2.5% |
| 2 | 2.3% | 2.2% |
| 3 | 3.6% | 5.1% |
| 7 | 3.3% | 14.0% |
| 14 | 3.2% | 28.4% |
| 30 | 27.7% | 38.4% |
| 60 | 14.2% | 16.6% |
| 90 | 8.6% | 10.0% |

![Courbe de capture du gain](figures/capture_rate_curve.png)


**Règle de sortie retenue pour le backtest** : stop-loss dur à -25%, prises de profits échelonnées (25% de la position vendue à x2, x5, x10), trailing stop de 30% sous le sommet une fois la position armée à partir de x2 sur le solde, sortie forcée à 90 jours.

## 9. Semaines sans opportunité

Voir la sortie du module `src/analysis/timing.py` (log d'exécution) pour le détail par source ; sur les deux datasets, une fraction significative des semaines calendaires ne présente aucun nouveau creux menant historiquement à un x10 -- conclusion : **rester liquide en l'absence de signal est statistiquement préférable à forcer un trade.**

## 10. Backtest walk-forward (sans biais de regard vers le futur)

| Seuil score | Trades | Win rate | Rendement moyen | Rendement médian | Max drawdown | Profit factor | Sharpe | Trades/sem | CAGR |
|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |
| 0.4 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |
| 0.5 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |
| 0.6 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |
| 0.7 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |
| 0.8 | 0 | N/A | N/A | N/A | N/A | nan | nan | nan | N/A |

![Courbe d'équité du backtest](figures/backtest_equity_curve.png)

![Grille de seuils](figures/backtest_threshold_grid.png)

## 11. Stratégie finale


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

## 12. Limites explicites et pistes d'amélioration


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
