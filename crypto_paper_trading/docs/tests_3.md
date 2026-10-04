# Tests du prompt 3 — routine 7 « chaînes de victoires » (papier uniquement)

Règle d'arrêt : un test qui échoue est corrigé puis relancé ; après trois échecs sur le même test,
arrêt et signalement. Rien n'est activé tant que tout n'est pas vert.

## 1. Garde-fous en base (transactions annulées, 04/10/2026)

Rien n'est conservé : après les tests, `positions`, `chains`, `chain_steps` sont vides.

| # | Cas | Attendu | Obtenu |
|---|---|---|---|
| 1 | Position K pendant les 7 jours de lecture seule | refus | refusé (« routine 7 en lecture seule ») |
| 2 | Étape 1, risque 10 = 1 % de 1 000 | accepté | accepté |
| 3 | 2e position dans la même chaîne | refus | refusé (« une seule position par chaîne ») |
| 4 | Étape 1, risque 11 (1,1 %) | refus | refusé |
| 5 | Stop 16 % | refus | refusé (« stop > 15 % ») |
| 6 | Objectif +40 % avec stop 10 % (≠ 3R) | refus | refusé |
| 7 | Même pair déjà ouvert dans une autre chaîne | refus | refusé (pas de moyenne à la baisse) |
| 8 | Position 150 alors que 0,1 % du volume 24 h = 100 | refus | refusé (liquidité) |
| 9 | Clôture de l'étape 1 à l'objectif (+30) | niveau 1, gain en jeu 30 | niveau 1, maison 30, chaîne ouverte |
| 10 | Étape 2 avec risque 31 > gain 30 | refus | refusé (« risque > gain de l'étape précédente ») |
| 11 | Étape 2 avec risque 30 = gain | accepté | accepté |
| 12 | Étape 2 perdue | chaîne échouée, bilan 0 | échouée, bilan 0 (= exemple : échec à l'étape 2 → 0) |
| 13 | 4e chaîne « papier réel » ouverte | refus | refusé (« déjà 3 chaînes ouvertes ») |
| 14 | Bras A, risque 1,5 % (non-régression) | refus | refusé (règle d'origine inchangée) |
| 15 | Levier déclaré 4x | refus | refusé (« levier > 3x ») |
| 16 | Stop 15 %, levier 3x (liquidation 32,3 % ≥ 2 x 15,1 %) | accepté | accepté |
| 17 | Drawdown global 16 % (perte latente de 800 sur 5 000) | refus | refusé (« routine 7 suspendue ») |

Note : le premier essai du cas 8 a été bloqué par le plafond de risque (risque 10,1 > 10) avant
d'atteindre la règle de liquidité ; le cas a été refait avec un risque conforme (stop 5 %, risque 7,5).

## 2. Tests du moteur (`tests/test_chains.py`, 24 tests, tous verts)

| Groupe | Ce qui est vérifié | Résultat |
|---|---|---|
| Exemple chiffré | risques 100/300/900/2 700/8 100, gains 300/900/2 700/8 100/24 300, total 36 300 ; bilans d'échec -100 / 0 / +300 / +1 200 / +3 900 ; positions 1 000 (stop 10 %) et 6 000 (stop 5 %) | OK |
| Unitaires | risque k+1 = gain k ; position = risque / stop ; stop = objectif / 3 ; stop > 15 % refusé ; levier dépassé -> risque réduit (étape 5 : 81 000 -> 66 000, stop inchangé) ; liquidation ≥ 2x le stop ; liquidité 0,1 % ; arrêt à la première perte ; part réinvestie ; seuils par niveau ; « sécuriser » ; pas deux fois le même pair ; événements indépendants (5 victoires sur une même hausse = 1) | OK |
| Synthétique (a) | p = 70 % -> P(5) ≈ 16,8 % (simulation et Monte Carlo à ±2-3 points) | OK |
| Synthétique (b) | un critère qui relève vraiment P(victoire) (30 % -> 75 % aux niveaux 2-5) est retenu et fait monter le seuil du niveau 4 (5 -> 6) ; il faut 8 000 événements pour que la validation ait la puissance de conclure | OK |
| Synthétique (c) | critère aléatoire retenu **2 fois sur 200** (1 %), sous la limite fixée de 2/200 | OK |
| Synthétique (d) | sans effet de série, le test « main chaude » ne conclut pas (p > 0,05) | OK |
| Non-régression | routines 1 à 6 et `baseline_before_3.json` identiques | OK |
| Cycle 14 jours | 05:45 / 14:20 / vérifications / dimanche 11:30 ; lecture seule 7 jours (aucune position avant J+7) ; attente puis « non exécutée » quand la routine 6 n'a pas fini ; coupure simulée puis reprise à partir de l'état ; relance immédiate sans doublon ; 0 violation des garde-fous recopiés | OK |

Suite complète du projet : **123 tests verts** (dont les 99 précédents, inchangés).

Note sur (b) : un premier essai à 1 500 événements a échoué faute de puissance (~15 étapes de niveau 4
dans la période de validation) ; le critère de décision a aussi été changé de « espérance brute
par chaîne » (dominée par quelques chaînes complètes à ~360 R, trop bruitée) à « espérance modélisée »
à partir des taux de victoire lissés par niveau. Les règles de validation n'ont pas été assouplies.

## 3. Migrations rejouées deux fois

Voir section 4 (vérification en base après la seconde exécution).

## 4. Intégration en base (04/10/2026)

- Migration 009 appliquée puis **rejouée** (tables, colonnes, seuils, version K, configuration, journal) :
  compteurs identiques après la seconde exécution (16 variantes, 78 seuils, 1 version K,
  1 ligne de journal, date de fin de lecture seule inchangée : 11/10/2026 12:09, heure de Paris).
- Le connecteur Supabase expire au-delà d'environ 60 s : la migration a été appliquée en plusieurs
  morceaux (aucun n'a été appliqué à moitié : chaque morceau expiré a été vérifié puis renvoyé).
- Première optimisation (lecture seule) enregistrée : 32 lignes `chain_sim_runs` (rejeu historique
  et Monte Carlo pour les 16 variantes), statuts « inconclusif », 2 décisions, 1 ligne de journal.
- Activation : tâches planifiées 05:45, 14:20 et dimanche 11:30 (heure de Paris). Lecture seule
  jusqu'au 11/10/2026 ; chaînes papier ensuite.
