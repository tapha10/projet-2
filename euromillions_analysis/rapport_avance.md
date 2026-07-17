# Validation avancée du modèle EuroMillions

Complément méthodologique à `rapport.md` : validation chronologique glissante, log-loss, modèles bayésiens, comparaison à la loi hypergéométrique théorique, et simulations Monte-Carlo à grande échelle pour vérifier la stabilité des estimateurs.

Données : 673 tirages valides (2020-02-04 → 2026-07-14). Fenêtre de test walk-forward : **400 tirages les plus récents**, chaque prédiction n'utilisant que les tirages strictement antérieurs (aucune fuite de données).

## 1-3. Validation glissante, modèles bayésiens et log-loss

5 configurations testées : fréquentiste brut (MLE), Beta-Binomial bayésien (prior faible centré sur la probabilité théorique 1/50), Dirichlet-multinomial bayésien (prior faible), bayésien hiérarchique (prior = fréquence long-terme calculée sur le passé, mis à jour par les 50 derniers tirages), et une référence uniforme (aucune information, équivalent hasard pur). Chacun est évalué sur plusieurs largeurs de fenêtre glissante (50 / 100 / 200 / expansive) quand cela s'applique.

| Modèle | Fenêtre | Bons numéros (moy.) | Log-loss numéros | Bonnes étoiles (moy.) | Log-loss étoiles |
|---|---|---|---|---|---|
| MLE (fréquentiste brut) | fenêtre glissante 50 | 0.4500 | 0.3460 | 0.3850 | 0.4611 |
| Bayes-Beta (prior faible) | fenêtre glissante 50 | 0.5125 | 0.3323 | 0.3200 | 0.4585 |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 50 | 0.4425 | 0.4159 | 0.3000 | 0.4935 |
| MLE (fréquentiste brut) | fenêtre glissante 100 | 0.4650 | 0.3295 | 0.3250 | 0.4564 |
| Bayes-Beta (prior faible) | fenêtre glissante 100 | 0.5100 | 0.3285 | 0.3850 | 0.4557 |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 100 | 0.5125 | 0.4125 | 0.3350 | 0.4911 |
| MLE (fréquentiste brut) | fenêtre glissante 200 | 0.5425 | 0.3273 | 0.3675 | 0.4528 |
| Bayes-Beta (prior faible) | fenêtre glissante 200 | 0.5000 | 0.3270 | 0.3275 | 0.4527 |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 200 | 0.4800 | 0.4111 | 0.3200 | 0.4885 |
| MLE (fréquentiste brut) | expansive (tout l'historique) | 0.6000 | 0.3259 | 0.3200 | 0.4520 |
| Bayes-Beta (prior faible) | expansive (tout l'historique) | 0.5650 | 0.3258 | 0.3250 | 0.4519 |
| Bayes-Dirichlet (prior faible) | expansive (tout l'historique) | 0.5125 | 0.4100 | 0.2775 | 0.4878 |
| Bayes hiérarchique (prior long-terme) | prior expansif + vraisemblance 50 | 0.5150 | 0.3306 | 0.3325 | 0.4559 |
| Uniforme (référence hasard) | aucune donnée utilisée | 0.4750 | 0.3251 | 0.3525 | 0.4506 |

- Repères théoriques (hasard pur) : bons numéros attendus = 0.5000, log-loss théorique du modèle uniforme = 0.3251.
- **Lecture des log-loss** : le MLE brut avec petites fenêtres (50) surestime des probabilités proches de 0 pour les numéros absents récemment, ce qui pénalise fortement son log-loss dès qu'un numéro « rare » sort quand même (événement inévitable sur un tirage uniforme). Les modèles bayésiens lissent ce risque en tirant les probabilités vers 1/50, ce qui les rend plus robustes — un log-loss plus bas signale une meilleure calibration, **pas** une meilleure capacité prédictive du tirage lui-même.

### Comparaison appariée à la référence hasard (par tirage)

Correction de Bonferroni appliquée sur 14 configurations testées → seuil de significativité ajusté α = 0.00357.

| Modèle | Fenêtre | Différence moy. vs hasard | p (t apparié) | p (Wilcoxon) | Significatif après correction |
|---|---|---|---|---|---|
| MLE (fréquentiste brut) | fenêtre glissante 50 | -0.0250 | 0.5536 | 0.6369 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 50 | +0.0375 | 0.4002 | 0.3965 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 50 | -0.0325 | 0.4483 | 0.4714 | Non |
| MLE (fréquentiste brut) | fenêtre glissante 100 | -0.0100 | 0.8266 | 0.9122 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 100 | +0.0350 | 0.4524 | 0.4425 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 100 | +0.0375 | 0.3926 | 0.4090 | Non |
| MLE (fréquentiste brut) | fenêtre glissante 200 | +0.0675 | 0.1320 | 0.1285 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 200 | +0.0250 | 0.5815 | 0.5645 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 200 | +0.0050 | 0.9117 | 0.8341 | Non |
| MLE (fréquentiste brut) | expansive (tout l'historique) | +0.1250 | 0.0035 | 0.0037 | Oui |
| Bayes-Beta (prior faible) | expansive (tout l'historique) | +0.0900 | 0.0481 | 0.0395 | Non |
| Bayes-Dirichlet (prior faible) | expansive (tout l'historique) | +0.0375 | 0.4104 | 0.3964 | Non |
| Bayes hiérarchique (prior long-terme) | prior expansif + vraisemblance 50 | +0.0400 | 0.3747 | 0.4072 | Non |

→ **1 configuration(s) sur 13 reste(nt) significative(s) après correction pour comparaisons multiples.** Un résultat positif isolé parmi de nombreux tests correspond à ce qu'on attend par pur hasard (taux de faux positifs) et ne constitue pas une preuve de capacité prédictive.

## 4. Comparaison à la distribution hypergéométrique théorique

Pour une grille fixe de 5 numéros comparée à un tirage aléatoire de 5 parmi 50, le nombre de bons numéros suit une loi hypergéométrique H(N=50, K=5, n=5). Probabilités théoriques :

| Bons numéros | Probabilité théorique |
|---|---|
| 0 | 57.6639% |
| 1 | 35.1609% |
| 2 | 6.6973% |
| 3 | 0.4673% |
| 4 | 0.0106% |
| 5 | 0.0000% |

Test d'ajustement du khi-deux (classes 0, 1, 2, 3+ regroupées pour respecter l'effectif théorique minimal ≥5 par classe) entre la distribution empirique de chaque modèle et cette loi théorique :

| Modèle | Fenêtre | χ² | p-value | Écart significatif (Bonferroni) |
|---|---|---|---|---|
| MLE (fréquentiste brut) | fenêtre glissante 50 | 5.240 | 0.1550 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 50 | 0.791 | 0.8516 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 50 | 3.709 | 0.2947 | Non |
| MLE (fréquentiste brut) | fenêtre glissante 100 | 2.061 | 0.5598 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 100 | 5.115 | 0.1636 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 100 | 3.001 | 0.3915 | Non |
| MLE (fréquentiste brut) | fenêtre glissante 200 | 1.978 | 0.5770 | Non |
| Bayes-Beta (prior faible) | fenêtre glissante 200 | 1.912 | 0.5908 | Non |
| Bayes-Dirichlet (prior faible) | fenêtre glissante 200 | 0.451 | 0.9294 | Non |
| MLE (fréquentiste brut) | expansive (tout l'historique) | 13.817 | 0.0032 | Oui |
| Bayes-Beta (prior faible) | expansive (tout l'historique) | 6.265 | 0.0994 | Non |
| Bayes-Dirichlet (prior faible) | expansive (tout l'historique) | 1.311 | 0.7265 | Non |
| Bayes hiérarchique (prior long-terme) | prior expansif + vraisemblance 50 | 2.886 | 0.4095 | Non |
| Uniforme (référence hasard) | aucune donnée utilisée | 1.350 | 0.7173 | Non |

→ **1 configuration(s) sur 14** dévie(nt) significativement de la loi hypergéométrique théorique après correction. La quasi-totalité des modèles — y compris les modèles bayésiens — produit une distribution de bons numéros statistiquement indiscernable du pur hasard, comme attendu pour un tirage réellement indépendant.

## 5. Simulations Monte-Carlo à grande échelle (stabilité)

Moyenne théorique de bons numéros pour une grille fixe : 0.5000 (variance théorique 0.4133). Convergence de la moyenne empirique en simulant jusqu'à 500 000 tirages aléatoires réels (5 parmi 50, sans remise) :

| N simulations | Moyenne empirique | Erreur standard empirique | Erreur standard théorique | Écart à la théorie |
|---|---|---|---|---|
| 1 000 | 0.50800 | 0.02040 | 0.02033 | 0.00800 |
| 5 000 | 0.49480 | 0.00912 | 0.00909 | 0.00520 |
| 20 000 | 0.50385 | 0.00452 | 0.00455 | 0.00385 |
| 50 000 | 0.49846 | 0.00286 | 0.00287 | 0.00154 |
| 100 000 | 0.49943 | 0.00203 | 0.00203 | 0.00057 |
| 200 000 | 0.49915 | 0.00144 | 0.00144 | 0.00085 |
| 500 000 | 0.49903 | 0.00091 | 0.00091 | 0.00097 |

→ L'erreur standard décroît bien en 1/√N et la moyenne empirique converge vers la moyenne théorique (0,5 bon numéro par grille) : la mécanique de simulation est correcte et stable, ce qui valide les comparaisons utilisées dans le reste de l'analyse.

### Stabilité de l'avantage du meilleur modèle (bootstrap)

Configuration la plus favorable au modèle dans le test apparié : **MLE (fréquentiste brut) (expansive (tout l'historique))**. Ré-échantillonnage bootstrap (5 000 répétitions) de la différence appariée (bons numéros modèle − bons numéros hasard) par tirage :

- Différence moyenne observée : +0.1250
- Intervalle de confiance bootstrap à 95% : [+0.0475 ; +0.2100]
- Proportion de ré-échantillons bootstrap avec un avantage positif : 99.9%

→ L'intervalle de confiance bootstrap **exclut zéro**. Ce résultat, obtenu sur la configuration la plus favorable parmi plusieurs dizaines testées, doit être interprété avec une prudence extrême (risque de sélection a posteriori du meilleur résultat parmi de nombreux tests) et nécessite une validation sur des tirages futurs indépendants avant toute conclusion.

### Robustesse face à la graine aléatoire (re-tirages indépendants)

Le bootstrap ci-dessus ne teste que la stabilité par rapport à l'échantillon de tirages testés — il ne dit rien de la sensibilité du résultat à l'aléa *interne* du modèle (le tirage pondéré des 5 numéros à partir des probabilités estimées). Pour vérifier cela, chaque configuration signalée comme significative après correction de Bonferroni (ou, à défaut, la meilleure configuration trouvée) est ré-exécutée avec 20 graines aléatoires indépendantes supplémentaires :

| Modèle | Fenêtre | Diff. moyenne (20 graines) | Écart-type inter-graines | Min / Max | Graines significatives (p<0,05) sur 20 | Graines à avantage positif |
|---|---|---|---|---|---|---|
| MLE (fréquentiste brut) | expansive (tout l'historique) | +0.0002 | 0.0503 | -0.0800 / +0.1000 | 1/20 | 30% |

→ Le signe et la significativité de la différence changent selon la graine aléatoire utilisée pour l'échantillonnage : l'écart-type inter-graines est du même ordre de grandeur que la différence moyenne elle-même, et la plupart des re-tirages ne sont pas significatifs à p<0,05. **Ceci confirme que le résultat « significatif » observé plus haut ne tient qu'à la séquence aléatoire particulière utilisée pour cette exécution — un artefact de comparaisons multiples, pas un signal réel.**

## Conclusion générale

- La validation chronologique glissante (walk-forward, sans fuite de données) sur plusieurs largeurs de fenêtre et plusieurs modèles (fréquentiste et bayésiens) ne montre pas d'avantage robuste et stable par rapport au hasard.
- Le log-loss confirme que les modèles bayésiens sont mieux *calibrés* que le MLE brut (ils évitent les probabilités extrêmes), mais une meilleure calibration ne signifie pas une meilleure prédiction du tirage réel.
- La distribution empirique des bons numéros, pour la quasi-totalité des configurations, est statistiquement indiscernable de la loi hypergéométrique théorique attendue pour un tirage uniforme et indépendant.
- Les simulations Monte-Carlo à grande échelle confirment la stabilité et la correction de la méthodologie de comparaison (convergence en 1/√N vers les valeurs théoriques).
- Le bootstrap sur la configuration la plus favorable montre que même le meilleur résultat trouvé parmi de nombreux tests n'est pas statistiquement stable — signe classique de surapprentissage / de comparaisons multiples, pas d'un signal réel.

**La conclusion reste inchangée et honnête : aucun modèle testé, y compris les approches bayésiennes, ne démontre de capacité prédictive supérieure au hasard sur ce tirage indépendant et équiprobable. La probabilité de gain reste 1 sur 139 838 160, avant comme après toute analyse.**
