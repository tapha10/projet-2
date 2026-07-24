# Étude : peut-on prédire les x10 sur Bybit ?

Pipeline reproductible de collecte de données, détection d'événements, analyse
statistique, machine learning, scoring et backtest pour étudier la
prédictibilité des multiplications de prix (x5 à x100) sur les cryptomonnaies
listées sur Bybit, à partir de sources de données 100% gratuites.

## Lancer l'étude complète

```bash
python3 -m venv ../.venv        # si pas déjà fait
source ../.venv/bin/activate
pip install -r requirements.txt
./run_pipeline.sh
```

Le pipeline est **résumable** (les collecteurs sautent les coins déjà
récupérés) et **incrémental** (relancer plus tard récupère les 365 derniers
jours à jour + poursuit l'historique Coinbase).

## Structure

```
src/
  collectors/     # CoinGecko (univers Bybit + prix 365j + snapshot dev/social),
                  # Coinbase (historique pluriannuel), DeFiLlama (TVL)
  db/             # schéma SQLite + connexion
  features/       # régime de marché, détection d'événements x5-x100,
                  # feature engineering point-in-time (Dataset A et B)
  analysis/       # corrélations statistiques (FDR), timing entrée/sortie/durée
  ml/             # entraînement/comparaison des modèles, score interprétable,
                  # scoring walk-forward hors échantillon
  backtest/       # moteur de backtest sans biais de regard vers le futur
  report/         # génération des figures et du rapport final
data/
  db/crypto_x10.sqlite      # base de données (prix, TVL, événements, régime...)
  processed/*.parquet       # panels de features/labels prêts pour le ML
reports/
  final_report.md           # rapport scientifique complet
  figures/*.png
  *.csv                     # tous les résultats intermédiaires (traçabilité)
```

## Sources de données utilisées (et pourquoi)

| Source | Usage | Limite gratuite |
|---|---|---|
| CoinGecko API publique | Univers Bybit, prix/volume/mcap 365j, instantané dev/social/FDV | Historique plafonné à 365 jours ; dev/social non historisés |
| Coinbase Exchange API | Historique OHLCV pluriannuel (sous-ensemble cross-listé) | ~209/421 coins seulement |
| DeFiLlama API | TVL historique complet | Couvre ~76 coins DeFi |
| Bybit / Binance API natives | *Non utilisées* | Géo-bloquées depuis cet environnement |
| CoinGlass (funding/OI/liquidations) | *Non utilisé* | Nécessite une inscription/clé API |

Voir `reports/final_report.md`, section "Limites explicites" pour le détail
complet et les pistes d'amélioration si l'utilisateur peut fournir des clés
API gratuites supplémentaires (CoinGlass) ou un accès non géo-bloqué à
l'API Bybit native.

## Reproductibilité

Toute la méthodologie (détection d'événements, découpage walk-forward,
paramètres de la stratégie) est documentée en commentaires dans le code
source correspondant, pas seulement dans le rapport, pour que l'étude soit
auditable et modifiable.
