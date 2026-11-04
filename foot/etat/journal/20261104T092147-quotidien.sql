insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-11-04', '2026-11-04T09:19:00.586415+00:00', '2026-11-04T09:19:00.593035+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-11-03', '2', 0, '# Rapport du 04/11/2026 — matchs du 03/11
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-11-04T09:19:01.647943+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('9771592ac9851239', 'B1', '2627', '2026-11-04T19:30:00+00:00', 'Kortrijk', 'KV Mechelen', null, 'SCHEDULED', '2026-11-04T09:21:46.696563+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'over', 2.5, 1.77, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'over', 2.5, 1.8, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'over', 2.5, 1.8, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'under', 2.5, 1.96, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'under', 2.5, 2.0, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('9771592ac9851239', 'under', 2.5, 2.0, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('9771592ac9851239', 'all-v1', '2026-11-04T09:21:43.305066+00:00', '2026-11-04T09:21:42.974995+00:00', '{"p_m0": 0.5254691689008043, "p_m1": null, "p_m2": null, "p_m3": null, "p_m3gbm": null, "p_m4": 0.5254691689008043, "m1_lh": null, "m1_la": null, "m1_rho": null, "o_over_avg": 1.77, "o_under_avg": 1.96, "o_over_b365": 1.8, "o_under_b365": 2.0, "h_played_season": 9.0, "a_played_season": null, "h_ew_over": 0.5390166712291625, "a_ew_over": null, "h_ew_tot": 2.6144937004941293, "a_ew_tot": null, "h_ew_xgf": 1.078679718352176, "a_ew_xgf": null, "h_rest_days": 4.0, "a_rest_days": null, "h_nothing_to_play": 0.0, "a_nothing_to_play": null, "h_frac_season": 0.2647058823529412}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('68f766fdc896840f', 'E1', '2627', '2026-11-04T19:45:00+00:00', 'Cardiff', 'West Ham', 'E Duckworth', 'SCHEDULED', '2026-11-04T09:21:46.706897+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'over', 2.5, 1.38, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'over', 2.5, 1.4, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'over', 2.5, 1.42, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'under', 2.5, 2.91, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'under', 2.5, 3.0, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('68f766fdc896840f', 'under', 2.5, 3.0, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('68f766fdc896840f', 'all-v1', '2026-11-04T09:21:43.305066+00:00', '2026-11-04T09:21:42.974995+00:00', '{"p_m0": 0.6783216783216783, "p_m1": 0.7403054568398035, "p_m2": 0.7420186377244432, "p_m3": 0.717334617498425, "p_m3gbm": 0.6893796703393595, "p_m4": 0.7149343532200119, "m1_lh": 1.6400034782183535, "m1_la": 2.2177943476429274, "m1_rho": -0.04000000000000001, "o_over_avg": 1.38, "o_under_avg": 2.91, "o_over_b365": 1.4, "o_under_b365": 3.0, "h_played_season": 13.0, "a_played_season": 13.0, "h_ew_over": 0.6202754631767693, "a_ew_over": 0.7195909472116434, "h_ew_tot": 3.160249022522601, "a_ew_tot": 3.6529301158041663, "h_ew_xgf": 1.9010570839948788, "a_ew_xgf": 1.905807543037866, "h_rest_days": 4.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.2826086956521739}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('429e0166d9c67056', 'E1', '2627', '2026-11-04T19:45:00+00:00', 'Wrexham', 'Middlesbrough', 'O Langford', 'SCHEDULED', '2026-11-04T09:21:46.715180+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'over', 2.5, 1.61, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'over', 2.5, 1.62, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'over', 2.5, 1.65, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'under', 2.5, 2.23, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'under', 2.5, 2.3, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('429e0166d9c67056', 'under', 2.5, 2.3, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('429e0166d9c67056', 'all-v1', '2026-11-04T09:21:43.305066+00:00', '2026-11-04T09:21:42.974995+00:00', '{"p_m0": 0.5807291666666666, "p_m1": 0.5546015623767278, "p_m2": 0.5565008639777058, "p_m3": 0.5759081458010407, "p_m3gbm": 0.5862291661196442, "p_m4": 0.5698904927094472, "m1_lh": 1.261593880524506, "m1_la": 1.6408506674193477, "m1_rho": -0.04000000000000001, "o_over_avg": 1.61, "o_under_avg": 2.23, "o_over_b365": 1.62, "o_under_b365": 2.3, "h_played_season": 13.0, "a_played_season": 13.0, "h_ew_over": 0.48554842374939405, "a_ew_over": 0.7590037070198952, "h_ew_tot": 2.7517262284010693, "a_ew_tot": 3.5918186231907763, "h_ew_xgf": 1.0743936616478837, "a_ew_xgf": 2.2536155908533324, "h_rest_days": 5.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.2826086956521739}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('63b8ea9c52627edd', 'E1', '2627', '2026-11-04T20:00:00+00:00', 'Bristol City', 'Wolves', 'T Nield', 'SCHEDULED', '2026-11-04T09:21:46.725104+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'over', 2.5, 1.84, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'over', 2.5, 1.9, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'over', 2.5, 1.9, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'under', 2.5, 1.9, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'under', 2.5, 1.95, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('63b8ea9c52627edd', 'under', 2.5, 1.95, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('63b8ea9c52627edd', 'all-v1', '2026-11-04T09:21:43.305066+00:00', '2026-11-04T09:21:42.974995+00:00', '{"p_m0": 0.5080213903743315, "p_m1": 0.4644087233984372, "p_m2": 0.4662360575080836, "p_m3": 0.5149836381857656, "p_m3gbm": 0.4938343572774009, "p_m4": 0.4945033346171961, "m1_lh": 1.1214407257007806, "m1_la": 1.4107169227689027, "m1_rho": -0.04000000000000001, "o_over_avg": 1.84, "o_under_avg": 1.9, "o_over_b365": 1.9, "o_under_b365": 1.95, "h_played_season": 13.0, "a_played_season": 13.0, "h_ew_over": 0.4111495884733916, "a_ew_over": 0.5214932481972412, "h_ew_tot": 2.350987287275443, "a_ew_tot": 2.6107366850191873, "h_ew_xgf": 1.5799854616623978, "a_ew_xgf": 1.6778307350890884, "h_rest_days": 4.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.2826086956521739}') on conflict do nothing;
insert into foot_predictions (id, match_id, model, model_version, variant, side, prob, odds, odds_source, odds_captured_at, ev, selected, phase, counted, kickoff, locked_at, payload_hash, created_at) values ('63b8ea9c52627edd-M1-observation-20261104', '63b8ea9c52627edd', 'M1', 'M1-v1', 'observation', 'under', 0.535591, 1.9, 'avg', '2026-11-04T09:21:42.974995+00:00', 0.017623, true, '2', true, '2026-11-04T20:00:00+00:00', '2026-11-04T09:21:43.305066+00:00', '86e7fbb4ac681bef13d95175961dfdaca3c5cc8c2508ee5a3835d9fd7e6c3f21', '2026-11-04T09:21:43.305066+00:00') on conflict do nothing;
insert into foot_predictions (id, match_id, model, model_version, variant, side, prob, odds, odds_source, odds_captured_at, ev, selected, phase, counted, kickoff, locked_at, payload_hash, created_at) values ('63b8ea9c52627edd-M2-observation-20261104', '63b8ea9c52627edd', 'M2', 'M2-v1', 'observation', 'under', 0.533764, 1.9, 'avg', '2026-11-04T09:21:42.974995+00:00', 0.014151, true, '2', true, '2026-11-04T20:00:00+00:00', '2026-11-04T09:21:43.305066+00:00', '7f47851603b7332210b24b492ae9dabd1bb92b4ffaf4614b59d86d59a854c106', '2026-11-04T09:21:43.305066+00:00') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('d88037697d0d227d', 'E2', '2627', '2026-11-04T19:45:00+00:00', 'Oxford Utd', 'Reading', 'D Drysdale', 'SCHEDULED', '2026-11-04T09:21:46.736747+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'over', 2.5, 1.66, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'over', 2.5, 1.7, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'over', 2.5, 1.7, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'under', 2.5, 2.13, 'football-data:avg', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'under', 2.5, 2.1, 'football-data:b365', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('d88037697d0d227d', 'under', 2.5, 2.18, 'football-data:max', '2026-11-04T09:21:42.974995+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('d88037697d0d227d', 'all-v1', '2026-11-04T09:21:43.305066+00:00', '2026-11-04T09:21:42.974995+00:00', '{"p_m0": 0.5620052770448549, "p_m1": null, "p_m2": null, "p_m3": null, "p_m3gbm": null, "p_m4": 0.5620052770448549, "m1_lh": null, "m1_la": null, "m1_rho": null, "o_over_avg": 1.66, "o_under_avg": 2.13, "o_over_b365": 1.7, "o_under_b365": 2.1, "h_played_season": null, "a_played_season": 13.0, "h_ew_over": null, "a_ew_over": 0.46696394868066554, "h_ew_tot": null, "a_ew_tot": 2.5080274564606153, "h_ew_xgf": null, "a_ew_xgf": 1.7171038093742212, "h_rest_days": null, "a_rest_days": 4.0, "h_nothing_to_play": null, "a_nothing_to_play": 0.0, "h_frac_season": null}') on conflict do nothing;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-11-04', '2026-11-04T09:21:43.305094+00:00', '2026-11-04T09:21:46.745266+00:00', 'succès', '{"matchs_du_jour_source": 5, "capture_cotes": "2026-11-04T09:21:42.974995+00:00"}', '{"predictions": 2, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 2 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-11-03', '2', 0, '# Rapport du 04/11/2026 — matchs du 03/11
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-11-04T09:19:01.647943+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
