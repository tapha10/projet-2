# Tests de l'addendum 2ter — résultats (03/10/2026)

**Verdict : tous les tests sont verts.** Un écart avec le test manuel (rejeu historique) est
expliqué en section 4 ; il ne vient pas du moteur.

Commandes : `python3 -m unittest tests.test_2ter -v` (31 tests) et
`python3 -m unittest tests.test_engine` (25 tests d'origine), depuis `crypto_paper_trading/`.

## 1. Tests unitaires (`tests/test_2ter.py`)

| Test | Résultat | Détail |
|---|---|---|
| R, taille, marge, liquidation (exemple chiffré) | réussi | 100 € de risque, stop 5 % → notionnel 2 000 € ; +30 % = 600 € = **6 R** ; levier plafonné à 3x, marge 666,67 €, liquidation à −32,3 % (≥ 3 x 5 %) |
| Plan de position T | réussi | risque 10 USDT (1 %), position ≤ 25 %, levier ≤ 3x, stop 8-12 %, liquidation ≥ 3x le stop |
| Tranches : somme = 100 % | réussi | toutes découpes x états de paliers ; 0,25 % de risque → tranche B = 7,5 % |
| Stop du solde à l'entrée après la tranche A ; gains par tranche = total | réussi | B sort ensuite à l'équilibre ; somme des tranches = PnL total |
| Stop d'abord dans la même bougie | réussi | toutes les tranches sortent au stop |
| Aucun regard vers le futur | réussi | ajout de bougies futures et d'une bougie en cours (énormes) : critères strictement identiques |
| Événements indépendants | réussi | même pair à moins de 10 jours = un événement (10,0 j = nouvel événement) |
| Benjamini-Hochberg | réussi (2e essai) | voir section 3 |
| Seuils de rétention | réussi | 29 événements, lift 0,099, borne basse 0, p corrigée 0,2 ou validation négative → refusé |
| Déblocage : 39 événements | réussi | refusé (« 39 événements < 40 ») |
| Déblocage : taux d'équilibre exact | réussi | 10/70 = équilibre P2 → refusé |
| Déblocage : glissement x2 | réussi | espérance négative avec glissement x2 → refusé |
| Retour en ombre | réussi | borne haute 80 % < équilibre sur 40 événements → ombre ; 39 → non |
| Montée du risque | réussi | 0,25 → 0,5 % seulement après ≥ 3 semaines **et** ≥ 15 événements |
| Libellés débloqué / ombre / inconclusif / impossible | réussi | « impossible » seulement à partir de 100 événements |
| Garde-fous T (code) | réussi | refus : risque, levier, taille 25 %, total 150 %, liquidation, 8 positions, 3 entrées/jour, pair déjà ouvert, drawdown 15 % |

## 2. Tests d'intégration

| Test | Résultat | Détail |
|---|---|---|
| Migration 004 jouée deux fois | réussi | 2e passage sans erreur ; empreintes MD5 identiques avant/après pour `signals` (13), versions A/B/C, `positions`, `iteration_log`, `weekly_reports`, `daily_results`, 17 clés de `config` ; 4 versions de paliers, pas de doublon |
| Garde-fous T **en base** (transaction annulée) | réussi | entrée valide acceptée ; refus : levier 4x, taille 26 %, liquidation < 3x stop, risque 12 USDT, doublon de pair, version à 5x |
| **Non-régression A/B/C** | réussi | rejeu de 120 trajectoires x 3 bras identique à `tests/baseline_before_2ter.json` (taille, levier, sortie, R, PnL) |
| Synthétique (a) vrai critère +25 pts | réussi | seul `vrai_critere` est retenu (lift ≈ +0,25) |
| Synthétique (b) 200 critères aléatoires | réussi | **0** retenu sur 200 |
| Synthétique (c) avantage qui disparaît | réussi | P2 débloqué, puis repasse en ombre (`demote`) quand l'avantage disparaît |
| Lecture seule | réussi | une décision de déblocage est enregistrée mais l'état ne change pas |
| Cycle complet 14 jours en mode sec (`engine/dryrun.py`) | réussi | 116 étapes dans l'ordre R5 → R6 → R3 → R1 → R2 ; **0 conflit de verrou** ; `iteration_log` : 16 R5, 16 R6 (dont 2 dimanches complets), 14 R3, 14 R1, 56 R2 ; R6 en lecture seule les 7 premiers jours ; positions T conformes aux garde-fous |
| Routine 6 à 05:30 et dimanche 11:00 | réussi | tourne si R5 a réussi ; **attend** si R5 absente ou en échec (tentative 1), puis « non exécutée » avec la raison (tentative 2) ; cycle sec avec R5 en échec le jour 2 → R6 « not_run » ce jour-là |
| Mode sec sur les vraies données | réussi | R5 sur les 13 signaux réels : 52 trades d'ombre, 13 instantanés rattrapés sans regard vers le futur ; `decide --tiers` : position T 108,46 USDT x3, risque 10 USDT, blocs A/B/C identiques avec ou sans `--tiers` ; `check --tiers` : sortie par tranches, R = −1,015 |

## 3. Échecs rencontrés et corrections (règle d'arrêt respectée)

1. `test_bh` — échec au 1er essai : **erreur dans la valeur attendue du test**, pas dans le code.
   BH impose la monotonie : la p ajustée de 0,03 vaut min(0,03 x 4/2 ; 0,04 x 4/3) = 0,0533, pas 0,04.
   Attendus corrigés avec le calcul détaillé ; réussi au 2e essai.
2. `test_tier_positions_respect_guardrails` — échec au 1er essai : le test comparait le risque à
   10 USDT fixes, alors que le capital T était passé à 1 004,21 USDT après des gains (risque 10,04 =
   1 % du capital au moment de l'entrée, conforme). Le test vérifie désormais 1 % / 25 % du capital
   **à l'entrée** et ajoute le contrôle de la liquidation ; réussi au 2e essai.

Aucun test n'a été affaibli ni contourné ; aucun test n'a échoué trois fois.

## 4. Rejeu historique VELVET, PUMP, COTI (`tests/replay_history_2ter.py`, réseau)

Fichier `base_gainers_2026-10-03.xlsx` non fourni : le rejeu porte sur les 3 paires citées
(Gate.io, bougies 1 h, 150 derniers jours ; stop 5 % / +30 %, 10 jours, stop d'abord).

| Paire | Entrées | Objectif | Stop | Temps | R moyen |
|---|---|---|---|---|---|
| VELVET — entrée chaque jour | 140 | 22 % | 75 % | 3 % | +0,59 |
| PUMP — entrée chaque jour | 140 | 16 % | 77 % | 7 % | +0,28 |
| COTI — entrée chaque jour | 140 | 20 % | 76 % | 4 % | +0,45 |
| VELVET — jours de signal (bougie ≥ +15 %) | 27 | 19 % | 81 % | 0 % | +0,26 |
| 3 paires — jours de signal | 37 | 16 % | 84 % | 0 % | ≈ +0,10 |

**Écart avec le test manuel (≈ 13 % d'objectifs, ≈ 71 % de stops, R ≈ −0,5) — explication :**

- Les **taux** sont proches quand on entre sur les jours de signal (16 % / 84 % contre 13 % / 71 %).
  La différence de stops s'explique par l'absence de sorties par le temps ici (marché très
  directionnel) et par la fenêtre : VELVET est passé de 0,05 à 2,05 USDT (x30) sur la période,
  PUMP x5. Les données ont été vérifiées : aucun trou horaire, mèches cohérentes.
- Le **R moyen −0,5 de référence est arithmétiquement incompatible** avec 13 % d'objectifs à 6 R :
  même si tout le reste sortait au stop, R ≥ 0,13 x 6 − 0,87 x 1 ≈ −0,09. Le test manuel
  utilisait donc une autre définition de R (par ex. variation de prix ou frais / levier inclus),
  une autre fenêtre ou d'autres entrées. Le moteur, lui, est cohérent avec sa propre arithmétique
  (vérifié en section 1).
- Paliers sur ces 3 paires (entrées quotidiennes, ombre) : P1 22-38 % de réussite, P2 12-27 %,
  P3 13-24 %, P4 0-13 %. Ces chiffres sont **gonflés par la fenêtre haussière** et ne valent pas
  validation : ce ne sont pas des événements indépendants (une entrée par jour sur la même paire).
- Découpes (même rejeu) : 30/30/40 > 50/30/20 > 70/20/10 > 100/0/0 sur les 3 paires, pour la même
  raison (marché très directionnel) ; aucun changement n'est appliqué sur cette base.

Résultats bruts : `docs/replay_2ter.json`.

## 5. Activation

Activée après ces tests : migration 004 en base, routines 1 à 4 modifiées, routines 5 et 6
planifiées, routine 6 en **lecture seule pendant 7 jours** (`config.r6_readonly_until`).

## 6. Premiers passages réels (03/10/2026, après activation)

- Routine 5 (complète) : 13 signaux traités, 52 trades d'ombre (6 déjà terminés : stops serrés
  P2-P4 touchés sur NIGHT et SI), 13 instantanés rattrapés, ligne `routine5 / ok`, verrou libéré.
- Routine 6 (quotidienne, **lecture seule** jusqu'au 10/10/2026 19:35 UTC) : 13 événements
  indépendants ; P1 : 0 résultat complet ; P2-P4 : 2 résultats complets (2 stops). Aucun
  critère ni palier ne peut être jugé avant des dizaines d'événements : statut « inconclusif ».
