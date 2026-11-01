insert into foot_weekly_reports (week_start, phase, verdict, content, created_at) values ('2026-10-26', '2', 'insuffisant', '# Rapport hebdomadaire — semaine du 26/10 au 01/11/2026
_Simulation papier, pas un conseil de pari ; parier de l''argent réel comporte un risque de perte._

**Phase 2 — observation** · cumul compté : 0 prédictions

- Aucune prédiction réglée cette semaine.

## Modèles (hors échantillon)
| modèle | n | perte log | Brier | ECE |
|---|---|---|---|---|
| p_m0 | 136 | 0.6797 | 0.2434 | 0.054 |
| p_m1 | 136 | 0.7099 | 0.2575 | 0.076 |
| p_m2 | 136 | 0.7098 | 0.2575 | 0.075 |
| p_m3 | 136 | 0.6775 | 0.2423 | 0.086 |
| p_m3gbm | 136 | 0.6786 | 0.2429 | 0.073 |
| p_m4 | 136 | 0.6829 | 0.2449 | 0.026 |

## Leçons actives
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.
- Ne jamais calculer la valeur attendue avec un modèle non recalibré contre le marché ; un modèle candidat doit battre M0 en perte log hors échantillon avant d''être actif.
- Ne pas sélectionner un match sur une série ou un calendrier chargé ; seules des données que la cote n''a pas (compositions, absences de dernière minute) peuvent encore apporter quelque chose
- Toujours appliquer la correction de tests multiples (Bonferroni ou BH) au nombre de variantes essayées avant de parler d''avantage.

## Prochaine expérience
- M3 sélection ''plus'' uniquement

## Verdict
Échantillon insuffisant : il manque 100 prédictions comptées avant toute conclusion (seuil 100), 300 pour changer de modèle, 500 sur 2 mois pour conclure à l''absence d''avantage.', '2026-11-01T17:43:09.740865+00:00') on conflict (week_start) do update set phase=excluded.phase, verdict=excluded.verdict, content=excluded.content, created_at=excluded.created_at;
