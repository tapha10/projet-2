# Passage de l'après-midi — 14:00 (Paris)

Remplace les anciens déclencheurs séparés de la routine 1 (14:00), de la routine 7 `decide`
(14:20) et de la routine 2 (14:30).

Lis d'abord `crypto_paper_trading/routines/_contexte_commun.md` et applique-le (clone, mémoire).

## Étapes

0. **Mémoire** : `select paper_memory();`. Si `adaptation` est `false` (passage du matin manqué),
   suis d'abord `routines/10_matin.md` (il saute ce qui est déjà fait).
1. **Routine 1 — analyse et entrées** : suis `routines/01_analyse_entrees.md` (recherche web complète).
2. **Routine 7, mode `decide`** : suis `routines/07_chaines.md` (étapes communes, mode 14:20).
   Exploration des chaînes : si aucune étape n'a été ouverte depuis 7 jours après la fin de la
   lecture seule, le moteur peut ouvrir une étape 1 à demi-risque sur un signal refusé seulement
   pour son score (une par passage).
3. **Routine 2 — vérification** : suis `routines/02_verification.md` (sans `--daily`).
4. Résumé en 5 lignes : candidats, entrées par bras (dont exploration), chaînes, clôtures. Démo.
