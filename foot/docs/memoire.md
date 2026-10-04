# Mémoire du système (à lire en premier après une coupure)

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

Dernière mise à jour : 04/10/2026 (Phase 0, mise en place).

## Où est quoi

- Code : branche `claude/foot-paper-analysis` du dépôt `tapha10/projet-2`, dossier `foot/`.
- État de référence : Supabase, projet `foot-paper-analysis`, tables `foot_*` (**pas encore créé** : en attente
  d'une place libre sur l'offre gratuite). Ne jamais toucher aux autres projets, en particulier `crypto-paper-trading`.
- Guide des routines : `docs/routines.md`. Audit : `docs/audit.md`. Backtest : `docs/backtest.md`. Tests : `docs/tests.md`.

## Calendrier des phases

- Phase 0 : 04/10/2026 (audit, tables, tests).
- Phase 1 : 05–06/10/2026. Base historique **déjà constituée** le 04/10 : 40 118 matchs, 22 championnats, 2021-22 à 2026-27.
  Le premier combiné (05/10) est produit avec les modèles de départ et marqué « observation ».
- Phase 2 : à partir du 07/10/2026, jusqu'au 16e jour ou à 100 prédictions comptées.
- Activation : le jour où tous les tests sont verts **et** Supabase est en place ; puis 3 jours en lecture seule (`counted = false`).

## Modèle actif et règles actives

- **Modèle actif : M3-v1** (régression logistique L2 sur M0, M1, M2 et des variables de forme, de repos et d'enjeu).
  Il a remplacé M1-v1 avant toute prédiction réelle, selon la règle de la section 9 : 24 221 matchs hors échantillon,
  perte log nettement meilleure, calibration correcte, sur les 4 saisons.
- Observation en parallèle : M0 (marché), M1, M2, M3gbm, M4.
- Filtres : championnats de la liste config ; chaque équipe avec plus de 5 matchs joués (≥ 6, règle `strict`) ;
  côté le plus probable ; cote ≥ 1,70 (Avg, repli B365) ; valeur attendue > 0 % ; combiné des 5 meilleures valeurs
  (plus court si moins de sélections).

## Tests déjà faits (ne pas relancer à l'identique — voir `foot_experiments`)

| Test | Conclusion |
|---|---|
| M1, M2, M3gbm, M4 ont une perte log plus faible que le marché | infirmé |
| M3 a une perte log plus faible que le marché | inconclusif (gain minime, p = 0,07 non significatif) |
| Sélections M1 et M2 (cote ≥ 1,70, valeur > 0), règles strict et au_moins | infirmé (≈ 48,7 % pour un seuil de 52,5 %, ROI ≈ −7 %) |
| Sélections M3gbm et M4 | infirmé |
| Sélection M3 (≈ 310 matchs, 58,9 %, IC 53,3–64,2 %, seuil 55,3 %, ROI +6,7 %) | inconclusif (non robuste à la correction pour 10 variantes ; « toujours plus » fait aussi bien sur les mêmes matchs) |

## Leçons

1. Un modèle de buts non recalibré prend la marge du bookmaker pour de la valeur : M1 annonce 58 % et en obtient 49 %.
   Un candidat doit battre M0 en perte log hors échantillon avant d'être actif.
2. Toujours corriger les tests multiples avant de parler d'avantage.

## Hypothèses en file (par priorité)

1. M3 limité au côté « plus » (à valider en direct sur 2026-27).
2. Recalibration isotone de M1 contre le marché.
2. Apport des xG 2026-27.
3. Mouvement de cote entre instantanés.
3. Seuil de valeur optimal (0 %, 2 %, 4 %).
4. Re-sélection à T-75 min (exige une source de compositions).

## Limites connues

- Pas de compositions ni d'absences (aucune source gratuite et autorisée) : M2 ne voit que le repos et l'enjeu.
- `fixtures.csv` ne couvre pas tous les jours ; résultats publiés avec 1 à 3 jours de retard.
- M3 ne retient qu'environ 0,3 match par jour : le combiné de 5 sera souvent plus court, voire absent.
