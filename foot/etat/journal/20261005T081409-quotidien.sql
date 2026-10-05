insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-10-05', '2026-10-05T08:11:25.144076+00:00', '2026-10-05T08:11:25.152580+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-04', '1', 0, '# Rapport du 05/10/2026 — matchs du 04/10
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 1 — base historique** · prédictions comptées cumulées : **0** · échantillon insuffisant

## Hier, match par match
Aucune sélection hier.

## Cumul (prédictions comptées)
- Précision : — sur 0 (IC 95 % 0.0 %–100.0 %) ; seuil d''équilibre moyen — ; ROI simulé —
- Références sur les mêmes matchs : toujours plus — · toujours moins — · favori du marché — · hasard 50 % (attendu)

## Erreurs d''hier
Aucune.

## Leçons ajoutées
- Ne jamais calculer la valeur attendue avec un modèle non recalibré contre le marché ; un modèle candidat doit battre M0 en perte log hors échantillon avant d''être actif.
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.

## Combiné du jour
Pas de combiné aujourd''hui (aucune sélection éligible ou pas de matchs couverts par la source).

## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-05T08:11:26.148448+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('7ed8074d1b2db111', 'SP2', '2627', '2026-10-05T18:30:00+00:00', 'Cordoba', 'Tenerife', null, 'SCHEDULED', '2026-10-05T08:14:09.124340+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'over', 2.5, 1.82, 'football-data:avg', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'over', 2.5, 1.88, 'football-data:b365', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'over', 2.5, 1.88, 'football-data:max', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'under', 2.5, 1.89, 'football-data:avg', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'under', 2.5, 1.93, 'football-data:b365', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('7ed8074d1b2db111', 'under', 2.5, 1.93, 'football-data:max', '2026-10-05T08:14:06.059788+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('7ed8074d1b2db111', 'all-v1', '2026-10-05T08:14:06.282288+00:00', '2026-10-05T08:14:06.059788+00:00', '{"p_m0": 0.5094339622641508, "p_m1": 0.4726341764385087, "p_m2": 0.47321564006189454, "p_m3": 0.5104358639815982, "p_m3gbm": 0.5031450799369916, "p_m4": 0.4961388231098965, "m1_lh": 1.4865634608010385, "m1_la": 1.0779845956957617, "m1_rho": -0.020000000000000018, "o_over_avg": 1.82, "o_under_avg": 1.89, "o_over_b365": 1.88, "o_under_b365": 1.93, "h_played_season": 7.0, "a_played_season": 7.0, "h_ew_over": 0.7120025125624266, "a_ew_over": 0.2529642298761299, "h_ew_tot": 3.2752173606508532, "a_ew_tot": 2.143165818304419, "h_ew_xgf": 1.4307888293411526, "a_ew_xgf": 0.8595850581779587, "h_rest_days": 8.0, "a_rest_days": 9.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.16666666666666666}') on conflict do nothing;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-10-05', '2026-10-05T08:14:06.282313+00:00', '2026-10-05T08:14:09.134245+00:00', 'succès', '{"matchs_du_jour_source": 1, "capture_cotes": "2026-10-05T08:14:06.059788+00:00"}', '{"predictions": 0, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 1 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-04', '1', 0, '# Rapport du 05/10/2026 — matchs du 04/10
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 1 — base historique** · prédictions comptées cumulées : **0** · échantillon insuffisant

## Hier, match par match
Aucune sélection hier.

## Cumul (prédictions comptées)
- Précision : — sur 0 (IC 95 % 0.0 %–100.0 %) ; seuil d''équilibre moyen — ; ROI simulé —
- Références sur les mêmes matchs : toujours plus — · toujours moins — · favori du marché — · hasard 50 % (attendu)

## Erreurs d''hier
Aucune.

## Leçons ajoutées
- Ne jamais calculer la valeur attendue avec un modèle non recalibré contre le marché ; un modèle candidat doit battre M0 en perte log hors échantillon avant d''être actif.
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.

## Combiné du jour
Pas de combiné aujourd''hui : seulement 0 sélection(s) éligible(s) sur 5 demandées
## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-05T08:11:26.148448+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
