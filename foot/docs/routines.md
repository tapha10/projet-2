# Guide d'exécution des routines (pour les sessions planifiées)

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

Chaque routine est une session Claude Code planifiée (heure de Paris), qui part d'un conteneur neuf.
L'état de référence est dans **Supabase** (tables `foot_*` du projet `foot-paper-analysis`). La base SQLite
locale n'est qu'une copie de travail reconstruite à chaque exécution.

## Préambule commun (toutes les routines)

1. `git fetch origin claude/foot-paper-analysis && git checkout claude/foot-paper-analysis && git pull origin claude/foot-paper-analysis`
2. `cd foot && pip install -q -r requirements.txt`
3. `python -m pytest -q tests` — **si un test échoue : ne rien exécuter**, faire `not-run` (étape 7) avec le motif, appliquer la boîte d'envoi, et s'arrêter.
4. **Verrou** : exécuter sur Supabase (outil SQL, projet foot-paper-analysis) la sortie de
   `python -m foot.cli lock-sql acquire <RX-AAAAMMJJHHMM>`. Si aucune ligne n'est renvoyée, une autre routine
   tourne : attendre environ 3 minutes (boucle d'attente, pas de `sleep` nu) et réessayer **une fois**. Toujours
   occupé : `not-run RX "verrou occupé"`, appliquer la boîte d'envoi, s'arrêter.
5. **État** : exécuter sur Supabase la requête de `python -m foot.cli state-query`. Enregistrer la valeur JSON de
   la colonne `state` dans `data/state/state.json`, puis lancer `python -m foot.cli state-load-json data/state/state.json`.
6. **Dépendance** : `python -m foot.cli gate RX`. En cas de blocage (la routine précédente a échoué) : attendre
   environ 5 minutes, recharger l'état (étape 5), relancer `gate` une fois. Toujours bloqué : `not-run RX "<motif>"`.
7. Après la commande de la routine : appliquer sur Supabase **tout** le contenu de `data/state/outbox.sql`
   (`python -m foot.cli outbox`), par blocs d'environ 200 lignes si nécessaire, puis `python -m foot.cli outbox --clear`.
8. Libérer le verrou : SQL de `python -m foot.cli lock-sql release <même identifiant>`.
9. Plus de **3 échecs** sur la même étape technique : s'arrêter et le signaler en détail (journal + rapport).

Dépendances vérifiées par `gate` : R2←R1, R4←R3, R5←R3, R6←R4. R1 et R3 ne dépendent que des tests et du verrou.

## Routines

| Routine | Heure (Paris) | Commande | Ensuite |
|---|---|---|---|
| R1 collecte et prédictions | tous les jours 10:00 | `python -m foot.cli r1` | Verrouille à la fin du calcul (avant 11:00). Ajoute le combiné du jour au rapport du matin. Commit + push de `foot/rapports/`. |
| R2 avant matchs | toutes les heures 12:00–22:00 | `python -m foot.cli r2 [--news fichier.json]` | Sans source de compositions accessible : journalise « aucune source ». Ne modifie jamais une prédiction verrouillée. |
| R3 résultats | 23:55 et 07:30 | `python -m foot.cli r3` | Règle les matchs (temps réglementaire) et les combinés ; classe les erreurs. |
| R4 rapport du lendemain | 08:15 | `python -m foot.cli r4` | Rapport dans `foot_daily_reports` et `foot/rapports/quotidien/` ; commit + push. Pas d'e-mail tant que `foot_config.notification_target` est vide. |
| R5 optimisation | 03:30 ; approfondie le dimanche 10:00 | `python -m foot.cli r5` (dimanche : `train --rebuild` puis `r5 --deep`) | Une seule idée à la fois : `exp-check` avant, `exp-record` après, `lesson` si une erreur est comprise. Mettre à jour `docs/memoire.md`. Changement de modèle : seulement si `should_switch` l'accepte, via une nouvelle version dans `foot_model_versions`. Commit + push. |
| R6 rapport hebdomadaire | dimanche 18:30 | `python -m foot.cli r6` | Rapport dans `foot_weekly_reports` et `foot/rapports/hebdo/` ; commit + push. |

Le dimanche, R1 (10:00) et R5 approfondie (10:00) se disputent le verrou : R1 passe en premier, R5 attend et réessaie.
La R5 approfondie fait aussi tourner `train --rebuild` (environ 3 minutes de calcul).

## Garde-fous rappelés

- Jamais de clé ni de mot de passe dans le dépôt ou les journaux. Jamais de contournement d'un refus d'accès.
- Aucune donnée inventée : une valeur manquante reste vide.
- `foot_predictions`, `foot_combos`, `foot_combo_legs` et `foot_features` sont en ajout seulement (déclencheurs Postgres).
- Aucun pari réel, aucun compte de bookmaker.
