insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-10-15', '2026-10-15T08:18:10.924263+00:00', '2026-10-15T08:18:10.933824+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-14', '2', 0, '# Rapport du 15/10/2026 — matchs du 14/10
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-15T08:18:13.019761+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_matches (match_id, league, season, kickoff, home, away, referee, status, created_at) values ('e22b79fab8d1a6e6', 'E2', '2627', '2026-10-15T19:00:00+00:00', 'Mansfield', 'Oxford', 'T Parsons', 'SCHEDULED', '2026-10-15T08:19:18.567547+00:00') on conflict do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'over', 2.5, 1.73, 'football-data:avg', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'over', 2.5, 1.75, 'football-data:b365', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'over', 2.5, 1.77, 'football-data:max', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'under', 2.5, 2.02, 'football-data:avg', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'under', 2.5, 2.05, 'football-data:b365', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_odds_snapshots (match_id, side, line, odds, source, captured_at) values ('e22b79fab8d1a6e6', 'under', 2.5, 2.05, 'football-data:max', '2026-10-15T08:19:09.589541+00:00') on conflict (match_id, side, line, source, captured_at) do nothing;
insert into foot_features (match_id, model_version, computed_at, data_cutoff, features) values ('e22b79fab8d1a6e6', 'all-v1', '2026-10-15T08:19:11.125123+00:00', '2026-10-15T08:19:09.589541+00:00', '{"p_m0": 0.5386666666666667, "p_m1": 0.5396907828220665, "p_m2": 0.540462499638268, "p_m3": 0.5366080600726264, "p_m3gbm": 0.5488319844693549, "p_m4": 0.5384844509570054, "m1_lh": 1.4378847192439002, "m1_la": 1.4006923732894967, "m1_rho": -0.020000000000000018, "o_over_avg": 1.73, "o_under_avg": 2.02, "o_over_b365": 1.75, "o_under_b365": 2.05, "h_played_season": 8.0, "a_played_season": 7.0, "h_ew_over": 0.6272924980435486, "a_ew_over": 0.6123073447436657, "h_ew_tot": 3.011836227101636, "a_ew_tot": 2.792625456397319, "h_ew_xgf": 1.3761117190562928, "a_ew_xgf": 1.2838210320746537, "h_rest_days": 5.0, "a_rest_days": 5.0, "h_nothing_to_play": 0.0, "a_nothing_to_play": 0.0, "h_frac_season": 0.17391304347826086}') on conflict do nothing;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-10-15', '2026-10-15T08:19:11.125161+00:00', '2026-10-15T08:19:18.630901+00:00', 'succès', '{"matchs_du_jour_source": 1, "capture_cotes": "2026-10-15T08:19:09.589541+00:00"}', '{"predictions": 0, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 2 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-14', '2', 0, '# Rapport du 15/10/2026 — matchs du 14/10
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
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-15T08:18:13.019761+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
