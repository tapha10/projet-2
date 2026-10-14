insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-10-14', '2026-10-14T08:17:56.796259+00:00', '2026-10-14T08:17:56.800441+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-13', '2', 0, '# Rapport du 14/10/2026 — matchs du 13/10
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 2 — observation** · prédictions comptées cumulées : **0** · échantillon insuffisant

## Hier, match par match
Aucune sélection hier.

## Cumul (prédictions comptées)
- Précision : — sur 0 (IC 95 % 0.0 %–100.0 %) ; seuil d''équilibre moyen — ; ROI simulé —
- Références sur les mêmes matchs : toujours plus — · toujours moins — · favori du marché — · hasard 50 % (attendu)

## Erreurs d''hier
Aucune.

## Leçons ajoutées
Aucune.

## Combiné du jour
Pas de combiné aujourd''hui (aucune sélection éligible ou pas de matchs couverts par la source).

## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-14T08:17:58.061563+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('bfe65d8c34d4839d', 'E1', '2627', '2026-10-14T18:45:00+00:00', 'Norwich', 'Southampton', 'S Martin', 'SCHEDULED', '2026-10-14T08:18:56.208333+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'over', 2.5, 1.48, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'over', 2.5, 1.5, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'over', 2.5, 1.54, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'under', 2.5, 2.54, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'under', 2.5, 2.63, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('bfe65d8c34d4839d', 'under', 2.5, 2.63, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('bfe65d8c34d4839d', 'all-v1', '2026-10-14T08:18:52.775772+00:00', '2026-10-14T08:18:52.147284+00:00', '{"p_m0": 0.6318407960199005, "p_m1": 0.6457502017007435, "p_m2": 0.6427807537709468, "p_m3": 0.6410088256427382, "p_m3gbm": 0.6089672771990587, "p_m4": 0.6393643140598176, "m1_lh": 1.5419259641437197, "m1_la": 1.7839892506239263, "m1_rho": -0.08000000000000002, "o_over_avg": 1.48, "o_under_avg": 2.54, "o_over_b365": 1.5, "o_under_b365": 2.63, "h_played_season": 9.0, "a_played_season": 9.0, "h_ew_over": 0.7607232775969783, "a_ew_over": 0.6719914961721534, "h_ew_tot": 3.6676239145342713, "a_ew_tot": 3.2305986689024113, "h_ew_xgf": 1.4295965311619656, "a_ew_xgf": 1.6275137589724302, "h_rest_days": 4.0, "a_rest_days": 3.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.1956521739130435}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('8c454dd5fe0ada46', 'E1', '2627', '2026-10-14T18:45:00+00:00', 'Portsmouth', 'Sheffield United', 'O Langford', 'SCHEDULED', '2026-10-14T08:18:56.220423+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'over', 2.5, 1.88, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'over', 2.5, 1.91, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'over', 2.5, 1.93, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'under', 2.5, 1.85, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'under', 2.5, 1.91, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('8c454dd5fe0ada46', 'under', 2.5, 1.91, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('8c454dd5fe0ada46', 'all-v1', '2026-10-14T08:18:52.775772+00:00', '2026-10-14T08:18:52.147284+00:00', '{"p_m0": 0.4959785522788205, "p_m1": 0.4906227723329022, "p_m2": 0.492687246418427, "p_m3": 0.48352792366358005, "p_m3gbm": 0.49979790475882974, "p_m4": 0.4902766408553377, "m1_lh": 1.3383350247538344, "m1_la": 1.297877530158665, "m1_rho": -0.08000000000000002, "o_over_avg": 1.88, "o_under_avg": 1.85, "o_over_b365": 1.91, "o_under_b365": 1.91, "h_played_season": 8.0, "a_played_season": 9.0, "h_ew_over": 0.4348352106653468, "a_ew_over": 0.7041322083737341, "h_ew_tot": 2.507349122800566, "a_ew_tot": 2.8317937365117225, "h_ew_xgf": 1.3119337887619509, "a_ew_xgf": 0.9017058897953909, "h_rest_days": 3.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.17391304347826086}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('9b1b2dd91811ad60', 'E1', '2627', '2026-10-14T18:45:00+00:00', 'QPR', 'Derby', 'M Corlett', 'SCHEDULED', '2026-10-14T08:18:56.231005+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'over', 2.5, 1.76, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'over', 2.5, 1.8, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'over', 2.5, 1.8, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'under', 2.5, 1.98, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'under', 2.5, 2.0, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9b1b2dd91811ad60', 'under', 2.5, 2.0, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('9b1b2dd91811ad60', 'all-v1', '2026-10-14T08:18:52.775772+00:00', '2026-10-14T08:18:52.147284+00:00', '{"p_m0": 0.5294117647058824, "p_m1": 0.5070632442105434, "p_m2": 0.5078263756432675, "p_m3": 0.5489331392312038, "p_m3gbm": 0.5490021534357327, "p_m4": 0.5280907563863964, "m1_lh": 1.4920746150986897, "m1_la": 1.2107350950425917, "m1_rho": -0.08000000000000002, "o_over_avg": 1.76, "o_under_avg": 1.98, "o_over_b365": 1.8, "o_under_b365": 2.0, "h_played_season": 9.0, "a_played_season": 9.0, "h_ew_over": 0.48750757678253465, "a_ew_over": 0.5182329271037448, "h_ew_tot": 2.4351114071026303, "a_ew_tot": 2.5709596847115366, "h_ew_xgf": 1.5296758141257436, "a_ew_xgf": 0.9767865716660733, "h_rest_days": 5.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.1956521739130435}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('0e7dbf8a3a68fb8e', 'E1', '2627', '2026-10-14T19:00:00+00:00', 'Lincoln', 'West Ham', 'R Madley', 'SCHEDULED', '2026-10-14T08:18:56.240079+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'over', 2.5, 1.64, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'over', 2.5, 1.67, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'over', 2.5, 1.67, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'under', 2.5, 2.18, 'football-data:avg', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'under', 2.5, 2.2, 'football-data:b365', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('0e7dbf8a3a68fb8e', 'under', 2.5, 2.2, 'football-data:max', '2026-10-14T08:18:52.147284+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('0e7dbf8a3a68fb8e', 'all-v1', '2026-10-14T08:18:52.775772+00:00', '2026-10-14T08:18:52.147284+00:00', '{"p_m0": 0.5706806282722513, "p_m1": 0.5475499627078192, "p_m2": 0.5483229731332303, "p_m3": 0.5877195408369297, "p_m3gbm": 0.5971566088878885, "p_m4": 0.568296407775022, "m1_lh": 1.2268719008724205, "m1_la": 1.6452149186370624, "m1_rho": -0.08000000000000002, "o_over_avg": 1.64, "o_under_avg": 2.18, "o_over_b365": 1.67, "o_under_b365": 2.2, "h_played_season": 9.0, "a_played_season": 9.0, "h_ew_over": 0.5060278239545228, "a_ew_over": 0.6923358941832102, "h_ew_tot": 2.419742551461939, "a_ew_tot": 3.46221092580674, "h_ew_xgf": 1.3498467560459086, "a_ew_xgf": 2.1852838557130148, "h_rest_days": 4.0, "a_rest_days": 5.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.1956521739130435}') on conflict do nothing;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-10-14', '2026-10-14T08:18:52.775800+00:00', '2026-10-14T08:18:56.248908+00:00', 'succès', '{"matchs_du_jour_source": 4, "capture_cotes": "2026-10-14T08:18:52.147284+00:00"}', '{"predictions": 0, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 2 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-13', '2', 0, '# Rapport du 14/10/2026 — matchs du 13/10
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 2 — observation** · prédictions comptées cumulées : **0** · échantillon insuffisant

## Hier, match par match
Aucune sélection hier.

## Cumul (prédictions comptées)
- Précision : — sur 0 (IC 95 % 0.0 %–100.0 %) ; seuil d''équilibre moyen — ; ROI simulé —
- Références sur les mêmes matchs : toujours plus — · toujours moins — · favori du marché — · hasard 50 % (attendu)

## Erreurs d''hier
Aucune.

## Leçons ajoutées
Aucune.

## Combiné du jour
Pas de combiné aujourd''hui : seulement 0 sélection(s) éligible(s) sur 5 demandées
## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-14T08:17:58.061563+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
