insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-10-29', '2026-10-29T09:16:08.522791+00:00', '2026-10-29T09:16:08.533350+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-28', '2', 0, '# Rapport du 29/10/2026 — matchs du 28/10
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-29T09:16:10.281948+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('e6cdf230b3fcb6e3', 'I1', '2627', '2026-10-29T17:30:00+00:00', 'Frosinone', 'Lecce', null, 'SCHEDULED', '2026-10-29T09:17:09.219744+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'over', 2.5, 1.44, 'football-data:avg', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'over', 2.5, 1.44, 'football-data:b365', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'over', 2.5, 1.48, 'football-data:max', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'under', 2.5, 2.67, 'football-data:avg', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'under', 2.5, 2.75, 'football-data:b365', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e6cdf230b3fcb6e3', 'under', 2.5, 2.75, 'football-data:max', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('e6cdf230b3fcb6e3', 'all-v1', '2026-10-29T09:17:05.110218+00:00', '2026-10-29T09:17:04.204397+00:00', '{"p_m0": 0.6496350364963503, "p_m1": 0.6502026936578652, "p_m2": 0.6517806157994612, "p_m3": 0.7060408463046736, "p_m3gbm": 0.6883042813048316, "p_m4": 0.6688510517355739, "m1_lh": 2.0402949246912594, "m1_la": 1.3081322117175938, "m1_rho": 0.03999999999999998, "o_over_avg": 1.44, "o_under_avg": 2.67, "o_over_b365": 1.44, "o_under_b365": 2.75, "h_played_season": 8.0, "a_played_season": 8.0, "h_ew_over": 0.6710117843403064, "a_ew_over": 0.5384037171851914, "h_ew_tot": 3.720169274831811, "a_ew_tot": 2.564986963888368, "h_ew_xgf": 1.6561906758725744, "a_ew_xgf": 1.4089927069557449, "h_rest_days": 4.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.21052631578947367}') on conflict do nothing;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('995253eab9205bc7', 'I1', '2627', '2026-10-29T19:45:00+00:00', 'Fiorentina', 'Atalanta', null, 'SCHEDULED', '2026-10-29T09:17:09.235257+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'over', 2.5, 1.59, 'football-data:avg', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'over', 2.5, 1.62, 'football-data:b365', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'over', 2.5, 1.62, 'football-data:max', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'under', 2.5, 2.27, 'football-data:avg', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'under', 2.5, 2.3, 'football-data:b365', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('995253eab9205bc7', 'under', 2.5, 2.38, 'football-data:max', '2026-10-29T09:17:04.204397+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('995253eab9205bc7', 'all-v1', '2026-10-29T09:17:05.110218+00:00', '2026-10-29T09:17:04.204397+00:00', '{"p_m0": 0.5880829015544041, "p_m1": 0.5057772977910653, "p_m2": 0.5073603616787707, "p_m3": 0.61882431917745, "p_m3gbm": 0.6233675323835948, "p_m4": 0.5679117047443699, "m1_lh": 1.2140128509115398, "m1_la": 1.4835470261141364, "m1_rho": 0.03999999999999998, "o_over_avg": 1.59, "o_under_avg": 2.27, "o_over_b365": 1.62, "o_under_b365": 2.3, "h_played_season": 8.0, "a_played_season": 8.0, "h_ew_over": 0.6489014735307399, "a_ew_over": 0.6184932537486539, "h_ew_tot": 2.8780040069403316, "a_ew_tot": 3.3730666288475337, "h_ew_xgf": 1.3880972952532487, "a_ew_xgf": 1.6641294363717316, "h_rest_days": 4.0, "a_rest_days": 4.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.21052631578947367}') on conflict do nothing;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-10-29', '2026-10-29T09:17:05.110255+00:00', '2026-10-29T09:17:09.250184+00:00', 'succès', '{"matchs_du_jour_source": 2, "capture_cotes": "2026-10-29T09:17:04.204397+00:00"}', '{"predictions": 0, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 2 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-28', '2', 0, '# Rapport du 29/10/2026 — matchs du 28/10
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-29T09:16:10.281948+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
