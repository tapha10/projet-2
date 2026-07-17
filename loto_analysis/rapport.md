# Rapport d'analyse statistique Loto (FDJ)

**Avertissement** : cette analyse est une exploration statistique expérimentale et ludique. Le Loto est un tirage aléatoire indépendant ; aucune méthode statistique ne peut prédire ou influencer un tirage futur. La grille produite ne doit pas être interprétée comme ayant une probabilité de gain supérieure à n'importe quelle autre grille.

**Règles** : 5 numéros distincts parmi 1-49, + 1 numéro chance parmi 1-10 (différent d'EuroMillions : 5 parmi 50 + 2 étoiles parmi 12).

## Étape 1 — Importation et contrôle des données

- Lignes brutes lues : 1048
- Lignes supprimées (valeurs manquantes) : 0
- Lignes supprimées (valeurs hors plage 1-49/1-10 ou doublons de numéros dans la même ligne) : 0
- Tirages en double supprimés : 0
- **Nombre total de tirages valides : 1048**
- Période : 2019-11-06 → 2026-07-15

## Étape 2 — Statistiques descriptives

### Numéros les plus fréquents (total)
31 (130x), 30 (123x), 24 (119x), 3 (118x), 15 (118x), 5 (116x), 22 (116x), 6 (115x), 26 (115x), 28 (115x)

### Numéros les plus fréquents (50 derniers tirages)
30 (11x), 31 (9x), 41 (9x), 16 (8x), 18 (8x), 29 (8x), 38 (8x), 3 (7x), 17 (7x), 21 (7x)

### Numéros chance les plus fréquents (total)
2 (115x), 9 (113x), 7 (109x), 4 (107x), 1 (103x)

### Paires de numéros les plus fréquentes
17-30 (20x), 7-11 (19x), 26-42 (18x), 8-46 (17x), 13-31 (17x), 12-26 (17x), 6-28 (17x), 31-40 (17x), 10-30 (16x), 4-22 (16x)

### Triplets les plus fréquents
31-39-49 (5x), 5-6-21 (5x), 7-15-19 (5x), 10-12-49 (4x), 10-30-49 (4x)

- Somme des 5 numéros : moyenne=124.7, médiane=125.0, écart-type=30.1 (min=44, max=209)
- Pairs/impairs moyens : 2.46 / 2.54
- Bas (1-25) / haut (26-49) moyens : 2.55 / 2.45
- Répartition par dizaines (1-10, 11-20, 21-30, 31-40, 41-49) : 20.6%, 20.0%, 21.1%, 20.3%, 18.1%
- Nombres consécutifs : moyenne=0.44 par tirage, proportion de tirages avec ≥1 paire consécutive=37.9%
- Étendue (max-min) moyenne : 33.1 (écart-type 8.5)
- Répétitions moyennes par rapport au tirage précédent : 0.51

## Étape 3 — Corrélations et tests statistiques

- Test du khi-deux (numéros) : χ²=34.81, p-value=0.9228 → compatible avec une distribution uniforme
- Test du khi-deux (numéro chance) : χ²=3.16, p-value=0.9574 → compatible avec une distribution uniforme
- Paires testées pour co-occurrence : 1176, seuil de Bonferroni appliqué (α=4.25e-05)
- Nombre de paires restant significatives après correction de Bonferroni : **0** sur 1176
  → Après correction pour comparaisons multiples, ce nombre est proche de ce qui est attendu par pur hasard. Les corrélations observées entre numéros ne sont **pas** traitées comme prédictives.

## Étape 4 — Backtesting temporel (sans fuite de données)

- Tirages testés : 150
- Sélections aléatoires de comparaison : 9900 (≥ 10 000)
- Moyenne de bons numéros du modèle : 0.5200
- Moyenne de bons numéros du hasard : 0.5023
- Moyenne de bon numéro chance du modèle : 0.0867
- Moyenne de bon numéro chance du hasard : 0.1006
- Distribution des bons numéros (modèle) : 0: 56.7%, 1: 35.3%, 2: 7.3%, 3: 0.7%, 4: 0.0%, 5: 0.0%
- Différence observée (modèle - hasard) : 0.0177
- Intervalle de confiance à 95% de la différence : [-0.0891, 0.1245]
- Test t : t=0.324, p-value=0.7461
- **Conclusion du backtesting : non supérieur au hasard (résultat non concluant)**
  aucune différence statistiquement significative avec le hasard n'a été détectée.

## Étape 5 & 6 — Génération, scoring et sélection finale

- Combinaisons candidates générées et scorées : 120 000
- Score composite : équilibre fréquence historique/récente (poids fort), stabilité des intervalles, associations de paires (poids faible), somme centrale, équilibre pair/impair et bas/haut, répartition par dizaines, pénalité suites longues, pénalité similarité au dernier tirage, pénalité profils 'populaires' (anti-partage de gain, pas anti-hasard).
- Sélection finale tirée avec pondération aléatoire contrôlée parmi le top 50 des scores (graine aléatoire = 1453315676), afin de ne pas renvoyer systématiquement la même combinaison.

## Grille unique proposée

**Numéros : 10 – 17 – 30 – 31 – 49**
**Numéro chance : 05**

### Indicateurs de la grille

- Score statistique interne : 100.0/100 (percentile du score composite parmi les 120 000 candidats générés — un score interne, pas une probabilité de gain)
- Somme des numéros : 137
- Pair/impair : 2/3
- Bas/haut : 2/3
- Répartition par dizaines : 1-10: 1, 11-20: 1, 21-30: 1, 31-40: 1, 41-49: 1
- Nombre de paires historiquement fréquentes (top décile) dans la grille : 4
- Similarité avec le dernier tirage : 0 numéro(s) en commun

### Résultat du backtesting (rappel)

- Tirages testés : 150
- Moyenne de bons numéros du modèle : 0.5200
- Moyenne de bons numéros du hasard : 0.5023
- Différence observée : 0.0177 (IC95% [-0.0891, 0.1245], p=0.7461)
- **Conclusion : non supérieur au hasard (résultat non concluant)**

### Probabilités réelles

- Nombre total de combinaisons possibles : 19 068 840 (= C(49,5) × 10)
- Avant analyse : 1 sur 19 068 840, soit environ 0.00000524%
- Après analyse : 1 sur 19 068 840, soit environ 0.00000524%
- **Gain de probabilité démontré : 0%**

À titre de comparaison, EuroMillions offre 1 chance sur 139 838 160 (≈0,000000715%) — le Loto est donc environ 7.3x plus favorable en probabilité brute, mais reste malgré tout extrêmement improbable.

Le score statistique interne (ci-dessus) reflète uniquement une préférence pour des caractéristiques observées historiquement (fréquence, équilibre, répartition) et une pénalité anti-partage de gain. Il ne représente en aucun cas une probabilité de gagner. La probabilité réelle de gain au jackpot reste strictement 1 sur 19 068 840, identique avant et après toute analyse.
