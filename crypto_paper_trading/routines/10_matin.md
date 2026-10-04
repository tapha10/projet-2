# Passage du matin — 05:30 tous les jours (Paris)

Remplace les anciens déclencheurs séparés des routines 5 (04:00), 6 (05:30), 7 (05:45),
3 (12:30) et, le dimanche, 5 (10:00), 6 (11:00), 7 (11:30). Les étapes s'enchaînent dans l'ordre,
dans le même passage : la routine 6 n'a donc plus à attendre la routine 5.

Lis d'abord `crypto_paper_trading/routines/_contexte_commun.md` et applique-le (clone, mémoire).

## Étapes

0. **Mémoire** : `select paper_memory();`. Note `rattrapage.dimanche`, `rattrapage.cloture_hier`,
   `rattrapage.rapport_manque` et ce qui est déjà fait aujourd'hui.
1. **Rattrapage de la clôture d'hier** (si `cloture_hier` est `false`) : suis
   `routines/02_verification.md` avec `--late-date <rattrapage.hier>` à la place de `--daily`
   (la base n'écrase jamais une clôture existante ; la ligne est marquée RATTRAPAGE).
2. **Routine 5** (sauter si `routine5` est `true`) : suis `routines/05_preparation_donnees.md`,
   avec `--weekly` le dimanche.
3. **Routine 6** (sauter si `routine6` est `true`) : suis `routines/06_paliers_criteres.md`,
   mode `weekly` le dimanche, sinon `daily`, tentative `1`. Si le moteur affiche `ATTENTE` (routine 5
   en échec), relance une fois avec `--attempt 2` dans ce même passage (pas de `send_later`).
4. **Routine 7, mode `daily`** (sauter si `routine7` est `true`) : suis `routines/07_chaines.md`
   (étapes communes). `ATTENTE` → relance une fois avec `--attempt 2` dans ce même passage.
   Le dimanche, enchaîne ensuite le mode `weekly` de la même routine.
5. **Routine 3 — adaptation** (sauter si `adaptation` est `true`) : suis `routines/03_adaptation.md`.
   Rappel : avec moins de 30 trades fermés dans un bras, le moteur complète l'échantillon par des
   **trades contrefactuels** (signaux refusés de plus de 10 jours, un par grappe) ; voir
   `GUARDRAILS.md` section 8.
6. **Rapport hebdomadaire en retard** (seulement si `rapport_manque` est `true`, c'est-à-dire que
   le rapport du dimanche n'a pas été produit) : suis `routines/04_rapport_hebdo.md` et indique dans
   l'objet du courriel « (rattrapage) ».
7. Résumé en français (8 lignes max) : étapes faites, sautées (déjà faites) ou en échec, décisions
   des routines 6 et 7 (ou constats en lecture seule), changements de l'adaptation. Démo uniquement.
