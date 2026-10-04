# Tests (section 12)

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

Commande : `cd foot && python -m pytest -q tests`. Résultat du 04/10/2026 : **44 tests, 44 réussis**.

## Correspondance avec la section 12

| Exigence | Test(s) |
|---|---|
| Retrait de la marge | `test_remove_margin_proportional`, `test_remove_margin_power_sums_to_one_and_shrinks_longshot`, `test_overround_and_invalid` |
| Cote d'un combiné et seuil d'équilibre (14,2 ; 7,0 % ; 7,8 % ; 16,8 %) | `test_combo_odds_and_breakeven`, `test_combo_summary` |
| Règlement plus/moins 2,5 (2 buts = moins, 3 = plus, temps réglementaire, annulé) | `test_settle[...]`, `test_settle_void_and_regular_time_only`, `test_settle_combo` |
| Championnat national uniquement | `test_national_league_filter` |
| Plus de 5 matchs joués (deux lectures) | `test_min_matches_filter_strict_and_at_least` |
| Cote ≥ 1,70 (et côté le plus probable écarté, jamais forcé) | `test_min_odds_filter`, `test_value_threshold`, `test_odds_fallback_b365` |
| Construction du combiné (5, un par rencontre, plus court si besoin, arbitre commun noté) | `test_build_combo_five_unique`, `test_build_combo_short_when_insufficient`, `test_build_combo_notes_shared_referee` |
| Wilson | `test_wilson` |
| Brier, perte log | `test_brier_logloss` |
| Aucune variable postérieure au verrouillage | `test_features_ignore_future`, `test_m1_ignores_same_day_and_future`, `test_prediction_after_kickoff_refused` |
| Prédiction verrouillée non modifiable (la tentative échoue) | `test_locked_prediction_cannot_be_modified`, `test_postgres_migration_has_append_only_triggers_and_rls` |
| Synthétique (a) un vrai signal est retrouvé | `test_real_signal_is_found` |
| Synthétique (b) 200 variables aléatoires non retenues | `test_200_random_variables_not_retained` (Benjamini-Hochberg) |
| Synthétique (c) « inconclusif » si l'échantillon est trop petit | `test_small_sample_inconclusive`, `test_edge_verdicts` |
| Migrations jouées deux fois sans perte ; schémas Postgres et SQLite identiques | `test_migrations_run_twice_without_loss`, `test_postgres_and_sqlite_schemas_match` |
| Cycle complet R1→R6 en mode sec sur 14 jours | `test_full_cycle_dry_replay_14_days` (synthétique) + rejeu réel ci-dessous |
| La mémoire empêche de relancer un test | `test_memory_prevents_rerun` |
| Reprise après coupure (état Supabase → base locale, `memoire.md`) | `test_restart_from_dump` |
| Verrou et routine en échec | `test_lock_prevents_concurrent_routines`, `test_failed_routine_logged` |
| Sources testées, échec géré sans fausser les données | `test_source_failures_handled`, `test_missing_source_data_stays_empty` + audit réel (`docs/audit.md`) |

## Rejeu réel en mode sec (12/09/2026 → 25/09/2026, 22 championnats)

- R1, R2, R3, R4 : 14 exécutions chacune, R6 : 1, toutes au statut « sec », aucune erreur.
- 401 matchs avec probabilités verrouillées (`foot_features`) ; 0 prédiction verrouillée après le coup d'envoi.
- Modèle actif M3 : 3 sélections en 14 jours, 2 combinés (2 jambes puis 1 jambe, avec le motif écrit).
- Observation : M1 et M2 50 sélections chacun, M3gbm 14.
- R5 : métriques en direct affichées ; changement de modèle refusé (57 < 300 comparaisons) ; combinés « non jugeables ».

## Liste détaillée


### Intégration et sources
- test_migrations_run_twice_without_loss ✅
- test_postgres_and_sqlite_schemas_match ✅
- test_full_cycle_dry_replay_14_days ✅
- test_memory_prevents_rerun ✅
- test_restart_from_dump ✅
- test_lock_prevents_concurrent_routines ✅
- test_failed_routine_logged ✅
- test_source_failures_handled ✅
- test_missing_source_data_stays_empty ✅

### Absence de fuite et données synthétiques
- test_features_ignore_future ✅
- test_m1_ignores_same_day_and_future ✅
- test_locked_prediction_cannot_be_modified ✅
- test_prediction_after_kickoff_refused ✅
- test_postgres_migration_has_append_only_triggers_and_rls ✅
- test_real_signal_is_found ✅
- test_200_random_variables_not_retained ✅
- test_small_sample_inconclusive ✅
- test_edge_verdicts ✅

### Unitaires
- test_remove_margin_proportional ✅
- test_remove_margin_power_sums_to_one_and_shrinks_longshot ✅
- test_overround_and_invalid ✅
- test_combo_odds_and_breakeven ✅
- test_settle[1-1-under-win] ✅
- test_settle[2-0-over-loss] ✅
- test_settle[2-1-over-win] ✅
- test_settle[3-0-under-loss] ✅
- test_settle[0-0-under-win] ✅
- test_settle[4-3-over-win] ✅
- test_settle_void_and_regular_time_only ✅
- test_settle_combo ✅
- test_national_league_filter ✅
- test_min_matches_filter_strict_and_at_least ✅
- test_min_odds_filter ✅
- test_value_threshold ✅
- test_odds_fallback_b365 ✅
- test_build_combo_five_unique ✅
- test_build_combo_short_when_insufficient ✅
- test_build_combo_notes_shared_referee ✅
- test_combo_summary ✅
- test_wilson ✅
- test_brier_logloss ✅
- test_bh_and_streak ✅
- test_poisson_over_probability ✅
- test_m0_and_m4 ✅

## Activation

Tous les tests sont verts. L'activation (routines planifiées) attend la création du projet Supabase : il faut une place libre sur l'offre gratuite. Après l'activation : 3 jours en lecture seule (`counted = false`).
