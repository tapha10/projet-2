insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R3', '2026-10-06', '2026-10-06T08:18:41.454896+00:00', '2026-10-06T08:18:41.457749+00:00', 'succès', '{}', '{"resultats": 0, "combines_regles": 0}', '', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-05', '1', 0, '# Rapport du 06/10/2026 — matchs du 05/10
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
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose

## Combiné du jour
Pas de combiné aujourd''hui (aucune sélection éligible ou pas de matchs couverts par la source).

## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-06T08:18:42.408475+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
insert into foot_iteration_log (routine, run_day, started_at, finished_at, status, read_summary, changed_summary, why, details) values ('R1', '2026-10-06', '2026-10-06T08:19:36.753709+00:00', '2026-10-06T08:19:36.760837+00:00', 'succès', '{"matchs_du_jour_source": 0, "capture_cotes": "2026-10-06T08:19:36.060201+00:00"}', '{"predictions": 0, "selections": 0, "combine_principal_jambes": 0, "notes_combine": ["seulement 0 sélection(s) éligible(s) sur 5 demandées"]}', 'phase 1 ; modèle actif M3', '');
insert into foot_daily_reports (day, phase, n_predictions_cum, content, created_at) values ('2026-10-05', '1', 0, '# Rapport du 06/10/2026 — matchs du 05/10
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
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose

## Combiné du jour
Pas de combiné aujourd''hui : seulement 0 sélection(s) éligible(s) sur 5 demandées
## Limites
- Pas de source gratuite et autorisée pour les compositions et les absences : M2 n''utilise que le repos et l''enjeu.
- Résultats football-data publiés avec 1 à 3 jours de retard : certains matchs restent « en attente ».', '2026-10-06T08:18:42.408475+00:00') on conflict (day) do update set phase=excluded.phase, n_predictions_cum=excluded.n_predictions_cum, content=excluded.content, created_at=excluded.created_at;
