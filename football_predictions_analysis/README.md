# Backtest des pronostics footballpredictions.net (FR)

Voir `rapport.md` pour l'analyse complète (résumé exécutif, tableaux,
limites, conclusion honnête).

## Contenu

- `scraper.py` — collecte des pages FR du site (listing + pages de match
  individuelles). Aucune donnée n'est inventée : tout ce qui est écrit dans
  les CSV provient d'une réponse HTTP réelle horodatée.
- `stats.py` — boîte à outils statistique (IC de Wilson, ROI, drawdown,
  séries de pertes, split chronologique 60/20/20, validation glissante,
  modèle de Poisson).
- `run_analysis.py` — calcule les tableaux de résultats à partir des CSV
  de `data/` et les écrit dans `data/results/`.
- `data/predictions_log.csv` — 293 matchs terminés collectés le 26/07/2026
  (4 derniers jours disponibles publiquement sur le site), avec le
  pronostic 1N2 du site et le score final réel.
- `data/predictions_details_log.csv` — 40 matchs avec cotes réelles
  (1N2 / BTTS / score exact).
- `data/today_details.csv` — 10 matchs du jour avec pronostics et cotes
  (pour la section 11 du rapport), dont 8 exploitables.
- `data/results/*.csv` — tableaux produits par `run_analysis.py`.

## Pourquoi ce n'est pas (encore) le backtest de 6-12 mois demandé

Le site ne publie aucune archive de pronostics au-delà de 3 jours, et
`robots.txt` bloque explicitement Internet Archive (`ia_archiver`), donc
aucun historique long n'est reconstituible aujourd'hui. Voir la section 0
de `rapport.md` pour le détail technique complet des vérifications
effectuées.

## Construire le vrai historique

```bash
pip install requests beautifulsoup4
python3 scraper.py --collect-today --out data/predictions_log.csv
```

À exécuter une fois par jour (cron). Après 4-6 mois, `run_analysis.py`
pourra utiliser `stats.chronological_split` et `stats.walk_forward_folds`
pour un vrai backtest train/tune/test avec validation glissante.
