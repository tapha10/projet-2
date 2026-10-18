insert into foot_weekly_reports (week_start, phase, verdict, content, created_at) values ('2026-10-12', '2', 'insuffisant', '# Rapport hebdomadaire — semaine du 12/10 au 18/10/2026
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 2 — observation** · cumul compté : 0 prédictions

- Aucune prédiction réglée cette semaine.

## Modèles (hors échantillon)
| modèle | n | perte log | Brier | ECE |
|---|---|---|---|---|
| p_m0 | 45 | 0.6733 | 0.2402 | 0.043 |
| p_m1 | 45 | 0.7063 | 0.2562 | 0.110 |
| p_m2 | 45 | 0.7061 | 0.2562 | 0.110 |
| p_m3 | 45 | 0.6663 | 0.2368 | 0.054 |
| p_m3gbm | 45 | 0.6740 | 0.2407 | 0.078 |
| p_m4 | 45 | 0.6767 | 0.2418 | 0.060 |

## Leçons actives
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.
- Ne jamais calculer la valeur attendue avec un modèle non recalibré contre le marché ; un modèle candidat doit battre M0 en perte log hors échantillon avant d''être actif.
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.

## Prochaine expérience
- M3 sélection ''plus'' uniquement

## Verdict
Échantillon insuffisant : il manque 100 prédictions comptées avant toute conclusion (seuil 100), 300 pour changer de modèle, 500 sur 2 mois pour conclure à l''absence d''avantage.', '2026-10-18T16:45:59.025985+00:00') on conflict (week_start) do update set phase=excluded.phase, verdict=excluded.verdict, content=excluded.content, created_at=excluded.created_at;
