# foot — analyse plus/moins 2,5 buts (simulation papier)

> **Simulation uniquement** : mise fictive, aucun pari réel, aucun compte de bookmaker. Ce n'est pas un conseil
> de pari ; parier de l'argent réel comporte un risque de perte.

Chaque jour, le système évalue les matchs des championnats nationaux, garde ceux où le côté le plus probable
(plus ou moins 2,5 buts) a une cote d'au moins 1,70 et une valeur attendue positive, et construit un combiné de
jusqu'à 5 matchs. Il verrouille ensuite les prédictions (en ajout seulement, avec une empreinte), règle les
résultats et écrit des rapports. Il mesure enfin s'il bat le marché, sans présumer de la réponse.

- Démarrage après une coupure : `docs/memoire.md`
- Sources et interprétations : `docs/audit.md`
- Résultats du backtest : `docs/backtest.md`
- Tests : `docs/tests.md` (`python -m pytest -q tests`)
- Routines planifiées : `docs/routines.md`
- Schéma Supabase : `migrations/001_foot_init.sql`
- Rapports : `rapports/quotidien/`, `rapports/hebdo/`

```
cd foot
pip install -r requirements.txt
python -m pytest -q tests
python -m foot.cli audit
python -m foot.cli train --rebuild      # historique + backtest + modèles appris (environ 3 min)
python -m foot.phase1                   # backtest Phase 1 -> docs/backtest.md + mémoire
python -m foot.cli r1                   # prédictions et combiné du jour
```
