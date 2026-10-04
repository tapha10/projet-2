# Backtest Phase 1 — 2026-10-04

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

Données : football-data.co.uk, 22 championnats, saisons 2021-22 à 2026-27 (au 30/09/2026). Période hors échantillon : 2023-24 -> 2026-27. Aucune information postérieure au jour du match (M1 réajusté chaque jour sur le passé ; M2/M3 entraînés sur les saisons antérieures ; M4 pondéré par la saison précédente). Cote = cote moyenne d'avant-match (Avg), clôture = AvgC.

## 1. Qualité des probabilités (tous les matchs, mêmes matchs pour chaque modèle)

| modele   |     n |   logloss |   brier |    ece |   precision_cote_forte |
|:---------|------:|----------:|--------:|-------:|-----------------------:|
| p_m0     | 24221 |    0.6766 |  0.2419 | 0.009  |                 0.5687 |
| p_m1     | 24221 |    0.692  |  0.2491 | 0.0433 |                 0.5523 |
| p_m2     | 24221 |    0.6914 |  0.2488 | 0.041  |                 0.5537 |
| p_m3     | 24221 |    0.6762 |  0.2417 | 0.0074 |                 0.5703 |
| p_m3gbm  | 24221 |    0.678  |  0.2425 | 0.0083 |                 0.5695 |
| p_m4     | 24221 |    0.6786 |  0.2429 | 0.0118 |                 0.5668 |

Test apparié de perte log contre le marché (M0), correction de Benjamini-Hochberg sur 5 tests :

- p_m1 : écart moyen de perte log -0.01541 (positif = meilleur que M0), p = 1 -> **ne bat pas le marché**
- p_m2 : écart moyen de perte log -0.01483 (positif = meilleur que M0), p = 1 -> **ne bat pas le marché**
- p_m3 : écart moyen de perte log +0.00039 (positif = meilleur que M0), p = 0.0694 -> **ne bat pas le marché**
- p_m3gbm : écart moyen de perte log -0.00134 (positif = meilleur que M0), p = 0.999 -> **ne bat pas le marché**
- p_m4 : écart moyen de perte log -0.00196 (positif = meilleur que M0), p = 1 -> **ne bat pas le marché**

## 2. Règles de sélection (cote >= 1,70, valeur > 0, plus de 5 matchs joués)

| modèle | règle | n | réussite | IC 95 % | seuil d'équilibre | ROI | écart clôture | bat la clôture | verdict |
|---|---|---|---|---|---|---|---|---|---|
| p_m1 | strict | 7242 | 48.7% | 47.6%–49.9% | 52.5% | -7.2% | +0.12% | 48% | aucun avantage mesuré |
| p_m1 | au_moins | 7523 | 48.6% | 47.5%–49.8% | 52.5% | -7.5% | +0.15% | 48% | aucun avantage mesuré |
| p_m2 | strict | 7145 | 48.9% | 47.7%–50.0% | 52.6% | -7.1% | +0.24% | 49% | aucun avantage mesuré |
| p_m2 | au_moins | 7431 | 48.8% | 47.6%–49.9% | 52.6% | -7.4% | +0.25% | 49% | aucun avantage mesuré |
| p_m3 | strict | 309 | 58.9% | 53.3%–64.2% | 55.2% | +6.7% | +1.27% | 58% | inconclusif |
| p_m3 | au_moins | 315 | 59.0% | 53.5%–64.3% | 55.3% | +6.9% | +1.28% | 58% | inconclusif |
| p_m3gbm | strict | 1742 | 52.3% | 49.9%–54.6% | 53.9% | -2.9% | +0.44% | 52% | aucun avantage mesuré |
| p_m3gbm | au_moins | 1790 | 52.5% | 50.2%–54.8% | 53.9% | -2.5% | +0.46% | 52% | aucun avantage mesuré |
| p_m4 | strict | 1728 | 49.7% | 47.3%–52.0% | 53.9% | -7.9% | +0.42% | 53% | aucun avantage mesuré |
| p_m4 | au_moins | 1808 | 49.5% | 47.2%–51.8% | 53.9% | -8.2% | +0.47% | 53% | aucun avantage mesuré |

## 3. Références sur les mêmes matchs que chaque sélection (règle stricte)

| modèle | modèle | hasard | toujours plus | toujours moins | favori du marché |
|---|---|---|---|---|---|
| p_m1 | 48.7% (ROI -7.2%) | 50.4% (ROI -5.4%) | 51.2% (ROI -4.6%) | 48.8% (ROI -7.8%) | 53.2% (ROI -6.2%) |
| p_m2 | 48.9% (ROI -7.1%) | 50.3% (ROI -5.6%) | 51.0% (ROI -4.7%) | 49.0% (ROI -7.6%) | 52.8% (ROI -6.8%) |
| p_m3 | 58.9% (ROI +6.7%) | 50.5% (ROI -5.5%) | 57.9% (ROI +7.4%) | 42.1% (ROI -19.6%) | 54.7% (ROI -2.6%) |
| p_m3gbm | 52.3% (ROI -2.9%) | 48.2% (ROI -8.7%) | 51.1% (ROI -4.7%) | 48.9% (ROI -6.5%) | 53.0% (ROI -5.8%) |
| p_m4 | 49.7% (ROI -7.9%) | 49.4% (ROI -6.8%) | 50.6% (ROI -4.4%) | 49.4% (ROI -7.0%) | 51.9% (ROI -6.9%) |

## 4. Détail de la sélection p_m3 (règle strict)

### Par side

| side   |   n |   taux |    roi |   cote |     p |   ic_bas |   ic_haut |
|:-------|----:|-------:|-------:|-------:|------:|---------:|----------:|
| over   | 238 |  0.609 |  0.105 |  1.818 | 0.558 |    0.546 |     0.669 |
| under  |  71 |  0.521 | -0.063 |  1.8   | 0.562 |    0.407 |     0.633 |

### Par tranche_cote

| tranche_cote   |   n |   taux |   roi |   cote |     p |   ic_bas |   ic_haut |
|:---------------|----:|-------:|------:|-------:|------:|---------:|----------:|
| 1.70-1.80      | 160 |  0.588 | 0.023 |  1.744 | 0.58  |    0.51  |     0.661 |
| 1.80-1.90      |  96 |  0.615 | 0.138 |  1.851 | 0.547 |    0.515 |     0.706 |
| 1.90-2.00      |  48 |  0.542 | 0.057 |  1.951 | 0.519 |    0.403 |     0.674 |
| 2.00-2.20      |   5 |  0.6   | 0.208 |  2.012 | 0.503 |    0.231 |     0.882 |

### Par season

|   season |   n |   taux |    roi |   cote |     p |   ic_bas |   ic_haut |
|---------:|----:|-------:|-------:|-------:|------:|---------:|----------:|
|     2324 |  74 |  0.541 | -0.04  |  1.782 | 0.567 |    0.428 |     0.649 |
|     2425 | 127 |  0.567 |  0.031 |  1.817 | 0.558 |    0.48  |     0.65  |
|     2526 | 108 |  0.648 |  0.182 |  1.832 | 0.554 |    0.554 |     0.732 |

### Par league

| league   |   n |   taux |    roi |   cote |     p |   ic_bas |   ic_haut |
|:---------|----:|-------:|-------:|-------:|------:|---------:|----------:|
| B1       |  25 |  0.68  |  0.206 |  1.777 | 0.569 |    0.484 |     0.828 |
| D1       |  12 |  0.667 |  0.198 |  1.795 | 0.563 |    0.391 |     0.862 |
| E0       |  35 |  0.457 | -0.176 |  1.803 | 0.564 |    0.305 |     0.618 |
| E1       |  25 |  0.48  | -0.128 |  1.826 | 0.554 |    0.3   |     0.665 |
| E2       |  22 |  0.591 |  0.065 |  1.825 | 0.557 |    0.387 |     0.767 |
| E3       |  18 |  0.611 |  0.118 |  1.839 | 0.551 |    0.386 |     0.797 |
| EC       |   4 |  0.75  |  0.4   |  1.825 | 0.555 |    0.301 |     0.954 |
| F1       |  15 |  0.6   |  0.077 |  1.786 | 0.565 |    0.357 |     0.802 |
| F2       |  12 |  0.667 |  0.218 |  1.812 | 0.559 |    0.391 |     0.862 |
| G1       |  13 |  0.308 | -0.421 |  1.847 | 0.548 |    0.127 |     0.576 |
| I1       |  45 |  0.667 |  0.215 |  1.823 | 0.559 |    0.521 |     0.786 |
| I2       |   7 |  0.429 | -0.233 |  1.784 | 0.564 |    0.158 |     0.75  |
| N1       |   5 |  0.6   |  0.066 |  1.792 | 0.563 |    0.231 |     0.882 |
| P1       |  18 |  0.722 |  0.321 |  1.849 | 0.547 |    0.491 |     0.875 |
| SC0      |  15 |  0.533 | -0.026 |  1.831 | 0.552 |    0.301 |     0.752 |
| SC1      |   8 |  0.75  |  0.435 |  1.908 | 0.529 |    0.409 |     0.929 |
| SC2      |   4 |  1     |  0.808 |  1.808 | 0.557 |    0.51  |     1     |
| SP1      |  16 |  0.438 | -0.24  |  1.753 | 0.578 |    0.231 |     0.668 |
| SP2      |   6 |  0.667 |  0.192 |  1.785 | 0.565 |    0.3   |     0.903 |
| T1       |   4 |  0.75  |  0.3   |  1.795 | 0.57  |    0.301 |     0.954 |

### Combiné quotidien (jusqu'à 5 matchs)

- 160 jours avec au moins une sélection ; combinés de 5 matchs complets : 13
- gagnés : 71 (44.4%) ; probabilité estimée moyenne 42.6% ; ROI simulé +4.5%

## 5. Choix du modèle actif (section 9)

- M1 -> M3 : changement accepté (meilleure perte log (p=0), calibration ok) ; n = 24221
- M3 contre le marché M0 : M3 pas significativement meilleur (amélioration non significative (p=0.0694, seuil 0.0125))
- **Modèle actif retenu : M3** (les autres tournent en observation).

## 6. Conclusion honnête

- Le marché (M0) est une estimation très difficile à battre : M1 et M2 (Poisson / Dixon-Coles sur les buts) sont nettement moins bons que lui (perte log et calibration), et leur sélection « valeur > 0 » perd environ 7 % : ils prennent la marge du bookmaker pour de la valeur.
- M3 (logistique sur M0 + M1 + variables) égale le marché, avec un gain minime. Sa sélection affiche un ROI positif sur environ 300 paris, mais l'IC 95 % contient le seuil d'équilibre et l'avantage disparaît après correction des tests multiples : **inconclusif**.
- Aucune conclusion « avantage mesuré » n'est possible à ce stade. Le suivi réel (Phase 2) décidera, avec les seuils de la section 9.