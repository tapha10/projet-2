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
