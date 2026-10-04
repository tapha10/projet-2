# Guide d'exécution des routines (pour les sessions planifiées)

> **Mode économe (actif depuis le 04/10/2026)** : pour limiter la consommation de l'abonnement, il n'y a plus que
> 2 routines. Chacune lance une seule commande, qui enchaîne les étapes ci-dessous :
> - tous les jours à 10:00 : `bash foot/routine.sh quotidien` (R3 résultats -> R4 rapport -> R1 prédictions et combiné) ;
> - le dimanche à 18:30 : `bash foot/routine.sh hebdo` (R5 approfondie avec réentraînement -> R6 rapport hebdomadaire).
>
> R2 (compositions toutes les heures) est suspendue : aucune source de compositions autorisée n'existe pour l'instant.
> La R5 quotidienne est suspendue : trop peu de données nouvelles chaque jour. On les rétablit si une clé API est ajoutée.
> Le détail ci-dessous reste valable pour une exécution manuelle ou pour le mode Supabase.

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

Chaque routine est une session Claude Code planifiée (heure de Paris), qui part d'un conteneur neuf.
L'état de référence est dans **Supabase** (tables `foot_*` du projet `foot-paper-analysis`). La base SQLite
locale n'est qu'une copie de travail reconstruite à chaque exécution.

## Deux modes d'état (`python -m foot.cli mode`)

- **`git`** (repli, actif tant que le projet Supabase n'existe pas) : l'état se reconstruit en rejouant le journal
  SQL versionné `foot/etat/journal/*.sql` (un fichier par exécution, donc pas de conflit git).
- **`supabase`** (cible) : l'état de référence est dans les tables `foot_*` du projet Supabase `foot-paper-analysis`.
  Le journal git continue d'être écrit, comme copie d'audit.

## Préambule commun (toutes les routines)

1. `git fetch origin claude/foot-paper-analysis && git checkout claude/foot-paper-analysis && git pull origin claude/foot-paper-analysis`
2. `cd foot && pip install -q -r requirements.txt`
3. `python -m pytest -q tests`. **Si un test échoue**, ne rien exécuter : faire `python -m foot.cli not-run RX "tests en échec : <détail>"`,
   passer aux étapes 8 et 9, puis s'arrêter.
4. Lire le mode (`python -m foot.cli mode`).
   - Mode `supabase` : prendre le **verrou** en exécutant sur Supabase (outil SQL, projet foot-paper-analysis) la sortie de
     `python -m foot.cli lock-sql acquire RX-AAAAMMJJHHMM`. Si aucune ligne n'est renvoyée, une autre routine tourne :
     attendre environ 3 minutes (boucle d'attente, pas de `sleep` nu) et réessayer **une fois**. Toujours occupé :
     `not-run RX "verrou occupé"`, étapes 8 et 9, arrêt.
   - Mode `git` : pas de verrou partagé. Les fichiers de journal par exécution évitent les conflits.
5. **État**.
   - Mode `supabase` : exécuter sur Supabase la requête de `python -m foot.cli state-query`, enregistrer la valeur JSON
     de la colonne `state` dans `data/state/state.json`, puis lancer `python -m foot.cli state-load-json data/state/state.json`.
   - Mode `git` : `python -m foot.cli state-from-journal`.
6. **Dépendance** : `python -m foot.cli gate RX`. Si elle bloque (la routine précédente a échoué) : attendre environ 5 minutes,
   faire `git pull`, recharger l'état (étape 5), relancer `gate` une fois. Toujours bloquée : `not-run RX "<motif>"`, étapes 8 et 9.
7. Lancer la commande de la routine (tableau ci-dessous).
8. Mode `supabase` uniquement : appliquer sur Supabase **tout** le contenu de `data/state/outbox.sql`
   (`python -m foot.cli outbox`), par blocs d'environ 200 lignes si nécessaire.
9. Dans les deux modes : `python -m foot.cli journal-write RX`, puis
   `git add etat rapports docs models_store && git commit -m "RX AAAA-MM-JJ" && git push -u origin claude/foot-paper-analysis`
   (en cas de refus : `git pull --rebase origin claude/foot-paper-analysis`, puis repousser ; jusqu'à 4 essais).
   Mode `supabase` : libérer le verrou avec le SQL de `python -m foot.cli lock-sql release <même identifiant>`.
10. Plus de **3 échecs** sur la même étape technique : s'arrêter et le signaler en détail (journal + résumé final).

## Passage au mode Supabase (une seule fois, dès qu'une place est libre)

1. Créer le projet `foot-paper-analysis` (organisation de l'utilisateur, région eu-west-3). Ne toucher à aucun autre projet.
2. Appliquer `migrations/001_foot_init.sql`, puis vérifier les alertes de sécurité.
3. Appliquer **dans l'ordre** tous les fichiers `etat/journal/*.sql` (ils sont rejouables : `on conflict do nothing`).
4. Écrire `supabase` dans `etat/MODE`, mettre à jour `docs/memoire.md`, commit + push.

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
