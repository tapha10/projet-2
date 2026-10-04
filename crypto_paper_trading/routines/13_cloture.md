# Passage de clôture — 23:30 (Paris)

Remplace l'ancien déclencheur de la routine 2 de 23:30.

Lis d'abord `crypto_paper_trading/routines/_contexte_commun.md` et applique-le (clone, mémoire).

## Étapes

0. **Mémoire** : `select paper_memory();`.
1. **Routine 2 avec clôture du jour** : suis `routines/02_verification.md` **avec `--daily`**
   (ligne du jour dans `daily_results`, latent compris). Si ce passage est manqué, le passage du
   matin suivant écrit la clôture en rattrapage (`--late-date`).
2. Contrôle : `select date, equity, pnl_usd, n_open, n_closed from daily_results order by date desc limit 2;`
3. Résumé en 3 lignes : clôtures du jour, capital par bras, drawdown. Démo uniquement.
