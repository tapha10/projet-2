# Rapport d'analyse statistique EuroMillions (2020-2026)

**Avertissement** : cette analyse est une exploration statistique expérimentale et ludique. EuroMillions est un tirage aléatoire indépendant ; aucune méthode statistique ne peut prédire ou influencer un tirage futur. La grille produite ne doit pas être interprétée comme ayant une probabilité de gain supérieure à n'importe quelle autre grille.

## Étape 1 — Importation et contrôle des données

- Lignes brutes lues : 673
- Lignes supprimées (valeurs manquantes) : 0
- Lignes supprimées (valeurs hors plage 1-50/1-12 ou doublons de numéros dans la même ligne) : 0
- Tirages en double supprimés : 0
- **Nombre total de tirages valides : 673**
- Période : 2020-02-04 → 2026-07-14

## Étape 2 — Statistiques descriptives

### Numéros les plus fréquents (total)
35 (85x), 42 (84x), 21 (80x), 29 (79x), 34 (79x), 10 (76x), 17 (75x), 19 (74x), 13 (73x), 16 (73x)

### Numéros les plus fréquents (50 derniers tirages)
37 (10x), 4 (8x), 10 (8x), 14 (8x), 17 (8x), 41 (8x), 42 (8x), 47 (8x), 5 (7x), 6 (7x)

### Étoiles les plus fréquentes (total)
3 (125x), 2 (124x), 6 (124x), 12 (118x), 9 (117x)

### Paires de numéros les plus fréquentes
23-32 (14x), 2-19 (14x), 7-34 (14x), 27-41 (13x), 5-14 (13x), 8-42 (13x), 19-37 (13x), 13-24 (13x), 2-45 (12x), 5-42 (12x)

### Triplets les plus fréquents
23-35-37 (5x), 7-12-33 (4x), 2-12-19 (4x), 24-29-42 (4x), 17-34-42 (4x)

### Paires d'étoiles les plus fréquentes
2-10 (18x), 3-9 (17x), 2-8 (17x), 9-12 (17x), 1-10 (16x)

- Somme des 5 numéros : moyenne=128.7, médiane=131.0, écart-type=30.3 (min=42, max=202)
- Pairs/impairs moyens : 2.48 / 2.52
- Bas (1-25) / haut (26-50) moyens : 2.48 / 2.52
- Répartition par dizaines (1-10,11-20,21-30,31-40,41-50) : 19.2%, 20.5%, 19.9%, 19.9%, 20.6%
- Nombres consécutifs : moyenne=0.41 par tirage, proportion de tirages avec ≥1 paire consécutive=36.3%
- Étendue (max-min) moyenne : 33.6 (écart-type 8.3)
- Répétitions moyennes par rapport au tirage précédent : 0.49

## Étape 3 — Corrélations et tests statistiques

- Test du khi-deux (numéros) : χ²=49.25, p-value=0.4631 → compatible avec une distribution uniforme
- Test du khi-deux (étoiles) : χ²=11.28, p-value=0.4198 → compatible avec une distribution uniforme
- Paires testées pour co-occurrence : 1225, seuil de Bonferroni appliqué (α=4.08e-05)
- Nombre de paires restant significatives après correction de Bonferroni : **0** sur 1225
  → Après correction pour comparaisons multiples, ce nombre est proche de ce qui est attendu par pur hasard. Les corrélations observées entre numéros ne sont **pas** traitées comme prédictives.

## Étape 4 — Backtesting temporel (sans fuite de données)

- Tirages testés : 150
- Sélections aléatoires de comparaison : 9900 (≥ 10 000)
- Moyenne de bons numéros du modèle : 0.5533
- Moyenne de bons numéros du hasard : 0.5041
- Moyenne de bonnes étoiles du modèle : 0.4400
- Moyenne de bonnes étoiles du hasard : 0.3268
- Distribution des bons numéros (modèle) : 0: 56.0%, 1: 34.0%, 2: 8.7%, 3: 1.3%, 4: 0.0%, 5: 0.0%
- Différence observée (modèle - hasard) : 0.0492
- Intervalle de confiance à 95% de la différence : [-0.0651, 0.1635]
- Test t : t=0.844, p-value=0.4003
- **Conclusion du backtesting : non supérieur au hasard (résultat non concluant)**
  aucune différence statistiquement significative avec le hasard n'a été détectée.

## Étape 5 & 6 — Génération, scoring et sélection finale

- Combinaisons candidates générées et scorées : 120 000
- Score composite : équilibre fréquence historique/récente (poids fort), stabilité des intervalles, associations de paires (poids faible), somme centrale, équilibre pair/impair et bas/haut, répartition par dizaines, pénalité suites longues, pénalité similarité au dernier tirage, pénalité profils 'populaires' (anti-partage de gain, pas anti-hasard).
- Sélection finale tirée avec pondération aléatoire contrôlée parmi le top 50 des scores (graine aléatoire = 1465400911), afin de ne pas renvoyer systématiquement la même combinaison.

## Grille unique proposée

**Numéros : 06 – 17 – 23 – 34 – 44**
**Étoiles : 05 – 07**

### Indicateurs de la grille

- Score statistique interne : 100.0/100 (percentile du score composite parmi les 120 000 candidats générés — un score interne, pas une probabilité de gain)
- Somme des numéros : 124
- Pair/impair : 3/2
- Bas/haut : 3/2
- Répartition par dizaines : 1-10: 1, 11-20: 1, 21-30: 1, 31-40: 1, 41-50: 1
- Nombre de paires historiquement fréquentes (top décile) dans la grille : 6
- Similarité avec le dernier tirage : 0 numéro(s) en commun

### Résultat du backtesting (rappel)

- Tirages testés : 150
- Moyenne de bons numéros du modèle : 0.5533
- Moyenne de bons numéros du hasard : 0.5041
- Différence observée : 0.0492 (IC95% [-0.0651, 0.1635], p=0.4003)
- **Conclusion : non supérieur au hasard (résultat non concluant)**

### Probabilités réelles

- Nombre total de combinaisons possibles : 139 838 160
- Avant analyse : 1 sur 139 838 160, soit environ 0.000000715%
- Après analyse : 1 sur 139 838 160, soit environ 0.000000715%
- **Gain de probabilité démontré : 0%**

Le score statistique interne (ci-dessus) reflète uniquement une préférence pour des caractéristiques observées historiquement (fréquence, équilibre, répartition) et une pénalité anti-partage de gain. Il ne représente en aucun cas une probabilité de gagner. La probabilité réelle de gain au jackpot reste strictement 1 sur 139 838 160, identique avant et après toute analyse.
