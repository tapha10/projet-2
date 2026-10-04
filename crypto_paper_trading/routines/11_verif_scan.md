# Passage vérification + analyse légère — 08:00 et 20:00 (Paris)

Remplace les anciens déclencheurs séparés de la routine 2 (08:00, 20:00) et de la routine 1b
(02:00, 06:00, 10:00, 18:00, 22:00).

Lis d'abord `crypto_paper_trading/routines/_contexte_commun.md` et applique-le (clone, mémoire).

## Étapes

0. **Mémoire** : `select paper_memory();`.
1. **Rattrapage du matin** : si l'heure de Paris est après 07:00 et que `routine5`, `routine6`,
   `routine7` ou `adaptation` est `false`, le passage de 05:30 n'a pas (entièrement) tourné : suis
   d'abord `routines/10_matin.md` (il saute ce qui est déjà fait). Si `cloture_hier` est `false`,
   le passage du matin s'en charge aussi.
2. **Routine 2 — vérification** : suis `routines/02_verification.md` (sans `--daily`).
3. **Routine 1b — analyse légère** : suis `routines/01b_analyse_intrajournee.md`.
   La règle d'**exploration** (GUARDRAILS section 8) s'applique automatiquement dans le moteur :
   après 7 jours sans aucune entrée dans un bras, une entrée à demi-risque au plus par passage sur
   un signal refusé seulement pour son score (score ≥ seuil − 1, aucune alerte).
4. Résumé en 4 lignes : positions vérifiées et clôtures, candidats, entrées (dont exploration), démo.
