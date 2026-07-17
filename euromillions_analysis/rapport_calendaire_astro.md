# Facteurs calendaires et astronomiques — EuroMillions

**Avertissement** : un tirage EuroMillions est un processus mécanique indépendant de la date calendaire ou de la position de la Lune. Cette analyse ne part pas de l'hypothèse que ces facteurs devraient avoir un effet — elle applique une recherche exhaustive avec des garde-fous stricts contre les faux positifs, pour vérifier rigoureusement s'il existe un signal quelconque.

Données : 673 tirages valides (2020-02-04 → 2026-07-14).

## 1. Facteurs testés

### Facteurs calendaires (14)

Jour de la semaine, jour du mois, numéro du jour dans l'année, semaine ISO, mois, trimestre, saison (météorologique : hiver=DJF, printemps=MAM, été=JJA, automne=SON), année, jour pair/impair, mois pair/impair, période du mois (début/milieu/fin en tiers de 10 jours), période de l'année (tiers de l'année), distance en jours depuis le 1er janvier, distance en jours jusqu'au 31 décembre.

### Facteurs astronomiques (5)

Calculés avec la bibliothèque `ephem` (algorithmes orbitaux autonomes, aucune donnée externe téléchargée), à une heure nominale fixe de tirage (20h UTC, approximation documentée — sans impact matériel sur des facteurs qui évoluent à l'échelle de la journée) : phase de la Lune (8 catégories), âge de la Lune en jours depuis la dernière nouvelle lune, pourcentage d'illumination lunaire, distance Terre-Lune (km), distance Terre-Soleil (km).

Le jeu de données enrichi (19 colonnes ajoutées) est sauvegardé dans `euromillions_with_calendar_astro_features.csv`.

## 2. Méthode

Pour chacun des 19 facteurs, un test est effectué contre chacune des 62 variables cibles (présence/absence de chacun des 50 numéros et 12 étoiles à chaque tirage), soit **1178 tests** au total :
- facteur catégoriel → test du khi-deux d'indépendance (table facteur × présence), taille d'effet = V de Cramér ;
- facteur continu → test de Mann-Whitney (valeurs du facteur les jours où le numéro sort vs les jours où il ne sort pas), taille d'effet = corrélation rang-biserial.

Corrections de comparaisons multiples appliquées sur l'ensemble des 1178 tests : correction de Bonferroni (stricte, α ajusté = 4.24e-05) et correction de Benjamini-Hochberg (FDR, taux de faux positifs attendu ≤5% parmi les résultats retenus, moins conservatrice et standard en exploration à grande échelle).

Les 6 associations les plus significatives (plus petite p-value brute) sont ensuite validées individuellement par :
- **validation hors échantillon** : test recalculé séparément sur les 70% de tirages les plus anciens (entraînement) et les 30% les plus récents (test), en exigeant un effet dans le même sens et p<0,05 sur la portion de test ;
- **bootstrap** (3 000 ré-échantillonnages) pour obtenir un intervalle de confiance à 95% de la taille d'effet ;
- **test de permutation multi-graines** (5 000 permutations × 4 graines indépendantes) : p-value empirique ne reposant sur aucune approximation asymptotique, répétée avec des graines différentes pour vérifier sa stabilité.

## 3. Résultats globaux

- **0 test(s) sur 1178** significatif(s) après correction de Bonferroni (seuil très strict, α=4.24e-05).
- **0 test(s) sur 1178** significatif(s) après correction FDR de Benjamini-Hochberg (seuil moins strict, q=0,05).
- Pour rappel, sous hypothèse nulle pure (aucun effet réel), on attend en moyenne **59 faux positifs** avec un seuil brut à 5% sur 1178 tests non corrigés — d'où la nécessité des corrections ci-dessus.

### Meilleur résultat par facteur (avant validation)

Pour chaque facteur, l'association la plus forte trouvée parmi les 62 variables cibles testées, avec correction de Bonferroni intra-facteur (×62) puis inter-facteurs (×19) :

| Facteur | Meilleure cible | p brute | Effet | p corrigée (intra+inter-facteurs) |
|---|---|---|---|---|
| cal_year_period | numéro 20 | 0.0004 | 0.1529 | 0.4520 |
| cal_days_until_dec31 | numéro 18 | 0.0004 | -0.2732 | 0.4594 |
| cal_days_since_jan1 | numéro 18 | 0.0004 | 0.2731 | 0.4618 |
| cal_day_of_year | numéro 18 | 0.0004 | 0.2731 | 0.4618 |
| cal_month | numéro 18 | 0.0004 | 0.2231 | 0.5167 |
| cal_iso_week | numéro 18 | 0.0005 | 0.2683 | 0.5805 |
| cal_quarter | numéro 42 | 0.0014 | 0.1524 | 1.0000 |
| cal_season | numéro 20 | 0.0017 | 0.1500 | 1.0000 |
| cal_day_of_week | numéro 47 | 0.0031 | 0.1142 | 1.0000 |
| astro_moon_illumination_pct | étoile 11 | 0.0051 | 0.1718 | 1.0000 |
| astro_earth_sun_distance_km | numéro 20 | 0.0067 | 0.1993 | 1.0000 |
| astro_moon_phase | numéro 47 | 0.0089 | 0.1670 | 1.0000 |
| cal_day_even | étoile 2 | 0.0144 | 0.0943 | 1.0000 |
| cal_year | numéro 5 | 0.0185 | 0.1505 | 1.0000 |
| cal_month_period | numéro 33 | 0.0188 | 0.1087 | 1.0000 |
| cal_day_of_month | numéro 45 | 0.0216 | 0.1645 | 1.0000 |
| astro_earth_moon_distance_km | numéro 8 | 0.0234 | -0.1709 | 1.0000 |
| cal_month_even | numéro 18 | 0.0242 | 0.0869 | 1.0000 |
| astro_moon_age_days | numéro 5 | 0.0504 | -0.1456 | 1.0000 |

## 4. Validation détaillée des meilleurs candidats

Les 6 associations avec la p-value brute la plus faible (toutes cibles confondues), indépendamment de leur significativité après correction — pour vérifier que même le meilleur résultat trouvé ne résiste pas à une validation indépendante :

### cal_year_period → numéro 20

- Test complet (n=673) : chi2, p=0.00038, effet=0.1529, p_Bonferroni_global=0.4520, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0006, effet=0.1774 → test (n=202) p=0.3824, effet=0.0976 → **non confirmé**
- Bootstrap : effet moyen=0.1579, IC95%=[0.0938 ; 0.2205] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0003 (min=0.0002, max=0.0006) → stable entre graines

### cal_days_until_dec31 → numéro 18

- Test complet (n=673) : mannwhitney, p=0.00039, effet=-0.2732, p_Bonferroni_global=0.4594, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0016, effet=-0.2919 → test (n=202) p=0.0933, effet=-0.2344 → **non confirmé**
- Bootstrap : effet moyen=-0.2758, IC95%=[-0.4128 ; -0.1325] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0005 (min=0.0002, max=0.0012) → stable entre graines

### cal_days_since_jan1 → numéro 18

- Test complet (n=673) : mannwhitney, p=0.00039, effet=0.2731, p_Bonferroni_global=0.4618, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0016, effet=0.2916 → test (n=202) p=0.0933, effet=0.2344 → **non confirmé**
- Bootstrap : effet moyen=0.2711, IC95%=[0.1300 ; 0.4108] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0005 (min=0.0002, max=0.0012) → stable entre graines

### cal_day_of_year → numéro 18

- Test complet (n=673) : mannwhitney, p=0.00039, effet=0.2731, p_Bonferroni_global=0.4618, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0016, effet=0.2916 → test (n=202) p=0.0933, effet=0.2344 → **non confirmé**
- Bootstrap : effet moyen=0.2709, IC95%=[0.1245 ; 0.4153] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0005 (min=0.0002, max=0.0012) → stable entre graines

### cal_month → numéro 18

- Test complet (n=673) : chi2, p=0.00044, effet=0.2231, p_Bonferroni_global=0.5167, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0100, effet=0.2291 → test (n=202) p=0.1950, effet=0.2701 → **non confirmé**
- Bootstrap : effet moyen=0.2505, IC95%=[0.1793 ; 0.3341] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0006 (min=0.0004, max=0.0008) → stable entre graines

### cal_iso_week → numéro 18

- Test complet (n=673) : mannwhitney, p=0.00049, effet=0.2683, p_Bonferroni_global=0.5805, p_FDR=0.0967
- Hors échantillon : entraînement (n=471) p=0.0014, effet=0.2961 → test (n=202) p=0.1371, effet=0.2077 → **non confirmé**
- Bootstrap : effet moyen=0.2675, IC95%=[0.1211 ; 0.4104] → IC exclut zéro
- Permutations (5 000 × 4 graines) : p empirique moyenne=0.0007 (min=0.0002, max=0.0010) → stable entre graines

## 5. Conclusion

**Aucun des 6 meilleurs candidats ne résiste simultanément aux trois validations (hors échantillon, bootstrap, permutations multi-graines).** Aucun test ne passait même la correction FDR, moins stricte que Bonferroni.

**Tous les facteurs calendaires et astronomiques testés sont statistiquement compatibles avec le hasard.** Aucun ne présente de signal reproductible. Ce résultat est cohérent avec la nature mécanique et indépendante du tirage : ni la date, ni la Lune, ni la distance Terre-Soleil n'ont de lien physique avec la sélection des boules.
