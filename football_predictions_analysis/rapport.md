# Backtest des pronostics de footballpredictions.net (FR) — Rapport

**Collecte des données réelles : 26/07/2026, 18:00–18:15 UTC.**
**Avertissement liminaire** : ce rapport ne promet aucun gain futur. Les
chiffres présentés sont calculés sur un échantillon réel mais **très
limité dans le temps** (voir section F). Aucune donnée n'a été inventée :
quand une information demandée n'était pas accessible, cela est dit
explicitement plutôt que comblé par une estimation.

---

## 0. Ce qui a été réellement possible à faire — et ce qui ne l'a pas été

Le cahier des charges demande un backtest sur 6 à 12 mois avec cotes,
enrichissement SofaScore, split chronologique 60/20/20 et validation
glissante. Avant de produire le moindre chiffre, l'accessibilité réelle des
données a été vérifiée techniquement (et non supposée). Résultat :

| Donnée demandée | Accessible ? | Constat technique |
|---|---|---|
| Pronostics du jour / week-end (1N2, score exact, BTTS, cotes affichées) | **Oui** | Pages FR server-rendues, accessibles en HTTP simple (voir `scraper.py`) |
| Résultats des matchs d'hier | **Oui** | Page dédiée `football-resultats-hier?show_all=1` |
| Résultats à J-2 / J-3 | **Oui** | Pages dédiées, mais **rien au-delà de J-3** |
| Historique de 6 à 12 mois de pronostics passés avec résultats | **Non** | Le site ne publie aucune archive au-delà de 3 jours ; aucune page « bilan » ou « historique » n'existe sur le domaine |
| Wayback Machine / archive.org pour reconstituer l'historique | **Non** | `robots.txt` du site contient explicitement `User-agent: ia_archiver` / `Disallow: /` → Internet Archive n'a **jamais eu le droit d'indexer ce site**, donc aucun instantané exploitable n'existe |
| Rendu JavaScript via navigateur headless (au cas où certaines pages seraient en SPA pure) | **Non, dans cet environnement** | Le sandbox de cette session bloque les connexions sortantes initiées par Chromium/Playwright (`ERR_CONNECTION_RESET`, y compris vers des domaines neutres comme example.com) ; non lié au site cible |
| API publique SofaScore (xG, tirs cadrés, forme, etc.) | **Non** | `api.sofascore.com` renvoie `403 Forbidden` à toute requête non authentifiée de ce type |
| Cotes pré-match affichées sur les pages de match individuelles | **Oui, partiellement** | Cote du pronostic 1N2, du BTTS et du score exact retrouvées ; **pas systématiquement** de marché plus/moins 2,5 buts sur toutes les pages |

**Conséquence directe et assumée** : un backtest de 6 à 12 mois, avec split
chronologique et validation glissante dans le temps, **n'a pas pu être
réalisé avec des données réelles** dans cette session — aucune archive
publique ne le permet, et il n'existait aucun jeu de données préexistant
dans ce dépôt à réutiliser. Fabriquer des mois de résultats aurait violé
l'exigence explicite de ne jamais inventer de données.

**Ce qui a été fait à la place**, pour rester utile et honnête :

1. Un outil de collecte réel et réutilisable (`scraper.py`) a été construit
   et testé en conditions réelles (voir section suivante).
2. Il a été exécuté immédiatement pour constituer un **jeu de données
   pilote réel** : 293 matchs terminés (résultats des 4 derniers jours
   disponibles publiquement) avec le pronostic 1N2 du site et le score
   final réel, plus un sous-échantillon de 40 matchs avec cotes réelles
   pour les marchés 1N2 / BTTS / score exact.
3. La boîte à outils statistique complète demandée (IC de Wilson, ROI,
   drawdown, séries de pertes, split chronologique, validation glissante,
   modèle de Poisson) a été implémentée dans `stats.py`, prête à tourner
   sur un historique plus long.
4. `scraper.py --collect-today` peut être **planifié quotidiennement**
   (cron / Task Scheduler) pour accumuler, jour après jour, le seul
   historique réellement disponible : au bout de 4 à 6 mois de collecte
   quotidienne, ce dépôt contiendrait un jeu de données suffisant pour
   effectuer le backtest tel que spécifié dans le cahier des charges.

Le reste de ce rapport présente les résultats obtenus sur ce pilote, avec
leurs limites statistiques clairement indiquées à chaque étape.

---

## A. Résumé exécutif

Sur l'échantillon réellement observable (293 matchs, 4 jours, toutes
compétitions confondues, fin juillet 2026) :

- Le pronostic 1N2 du site est correct **52,6 %** du temps (IC95%
  [46,8 % ; 58,2 %]), ce qui est supérieur à une stratégie naïve
  « toujours domicile » sur le même échantillon (46,4 %), mais l'intervalle
  de confiance est large et chevauche des scénarios proches du hasard
  pondéré par les cotes.
- Sur le sous-échantillon avec cotes réelles (n=38), le marché 1N2 affiche
  un **ROI négatif de -11,2 %** : le site devine correctement plus souvent
  que le hasard pur, mais pas assez pour compenser la marge des
  bookmakers sur les cotes qu'il recommande.
- Le marché BTTS (n=28) est le seul à afficher un ROI positif dans ce
  pilote (**+6,3 %**), mais l'intervalle de confiance du taux de réussite
  ([42,4 % ; 76,4 %]) est bien trop large pour en tirer une conclusion.
- Le score exact est, sans surprise, le marché le plus perdant
  (**ROI -33,3 %**, n=40) : c'est un marché à forte marge bookmaker et
  faible probabilité, cohérent avec la littérature sur les paris sportifs.
- **Aucun championnat n'atteint le seuil de 100 pronostics** retenu comme
  minimum représentatif dans ce projet (le plus documenté, Qualification
  pour la Conference League, n'en compte que 40). Il est donc **impossible
  d'affirmer aujourd'hui qu'un championnat en particulier est « fiable et
  rentable »** — ce serait une généralisation abusive à partir d'un
  échantillon insuffisant.
- **Aucune stratégie n'a pu être validée sur un échantillon de test
  indépendant** (split chronologique 60/20/20 impossible avec 4 jours de
  données). En l'état, **aucun avantage statistique robuste n'a été
  démontré** pour footballpredictions.net, ni en hit-rate ajusté du risque,
  ni en rentabilité.

## B. Tableau global (échantillon pilote — PAS un backtest validé)

| Marché | N pronostics | Taux de réussite | IC95% | Cote moyenne | ROI | Drawdown max | Confiance |
|---|---|---|---|---|---|---|---|
| 1N2 (échantillon large, sans cotes) | 293 | 52,6 % | [46,8% ; 58,2%] | n/a | n/a (cotes non connues) | n/a | Faible (1 seule fenêtre temporelle) |
| 1N2 (sous-échantillon avec cotes) | 38 | 47,4 % | [32,5% ; 62,7%] | 2,06 | **-11,2 %** | -6,66 u | Très faible (n<100) |
| BTTS (sous-échantillon avec cotes) | 28 | 60,7 % | [42,4% ; 76,4%] | 1,82 | **+6,3 %** | -4,66 u | Très faible (n<100) |
| Score exact (sous-échantillon avec cotes) | 40 | 7,5 % | [2,6% ; 19,9%] | 9,32 | **-33,3 %** | -17,00 u | Très faible (n<100) |
| Plus/Moins 2,5 buts | — | — | — | — | — | — | **Non évaluable** : pronostic non publié systématiquement par le site sur les pages consultées |
| Double chance, combinaisons résultat+O/U, résultat+BTTS | — | — | — | — | — | — | **Non évaluable dans ce pilote** (nécessite le même historique long que les marchés simples ; infrastructure prête dans `stats.py`, données insuffisantes) |

Séries de pertes observées (n petits, à ne pas extrapoler) : 1N2 → 5 défaites
consécutives max sur 38 paris ; BTTS → 5 sur 28 ; score exact → 24 sur 40
(le score exact perd très souvent, ce qui est normal pour ce marché).

## C. Tableau par championnat (n réel, aucun ≥ 100)

Classement des 10 championnats les mieux représentés dans le pilote — taux
de réussite du marché 1N2 uniquement (aucune cote disponible à ce niveau,
donc **pas de ROI par championnat possible** dans ce pilote) :

| Championnat | N | Taux de réussite 1N2 | IC95% | Verdict |
|---|---|---|---|---|
| Qualification pour la Conference League | 40 | 65,0 % | [49,5% ; 77,9%] | Échantillon encore insuffisant (< 100) |
| Etats-Unis : MLS | 30 | 50,0 % | [33,2% ; 66,8%] | Échantillon encore insuffisant |
| L'Autriche : ÖFB Cup | 29 | 72,4 % | [54,3% ; 85,3%] | Échantillon encore insuffisant |
| Écosse : Coupe de la Ligue | 16 | 62,5 % | [38,6% ; 81,5%] | Échantillon trop faible |
| Argentine : Torneo Clausura | 12 | 66,7 % | [39,1% ; 86,2%] | Échantillon trop faible |
| Qualifications Europa League | 9 | 33,3 % | [12,1% ; 64,6%] | Échantillon trop faible |
| Brésil : Serie A | 8 | 37,5 % | [13,7% ; 69,4%] | Échantillon trop faible |
| Chine : Super League | 8 | 50,0 % | [21,5% ; 78,5%] | Échantillon trop faible |
| Kazakhstan : Première Ligue | 7 | 42,9 % | [15,8% ; 75,0%] | Échantillon trop faible |
| Norvège : OBOS-ligaen | 7 | 14,3 % | [2,6% ; 51,3%] | Échantillon trop faible |

Le détail des 39 championnats observés est dans
`data/results/1x2_par_championnat.csv`.

**Classement en 3 catégories demandé par le cahier des charges :**

1. **Championnats fiables et rentables** : **aucun** — le seuil de 100
   pronostics n'est atteint par aucune compétition dans ce pilote.
2. **Championnats prometteurs mais insuffisamment documentés** :
   Qualification pour la Conference League, MLS, ÖFB Cup (Autriche) — les
   trois compétitions les mieux représentées, à ré-évaluer une fois 100+
   pronostics accumulés via la collecte quotidienne.
3. **Championnats à éviter** : aucune conclusion fiable ne peut être tirée
   sur des échantillons de 5 à 9 matchs (Qualifications Europa League,
   Kazakhstan, etc.) — les taux de 14 % ou 72 % observés y sont
   probablement du bruit statistique plutôt qu'un signal réel.

## D. Filtres testés (et pourquoi il n'y en a pas dix)

Le cahier des charges demande de tester de nombreux filtres puis de
présenter les 10 meilleurs. Sur un échantillon unique de 293 matchs
couvrant 4 jours, tester des dizaines de filtres et ne retenir que les 10
plus performants **serait exactement la sélection a posteriori (« data
dredging »)** que le cahier des charges demande par ailleurs d'éviter : avec
293 matchs, une part significative des « meilleurs » filtres parmi 50+
combinaisons testées ne serait due qu'au hasard. Un nombre volontairement
restreint de filtres a donc été testé, sur des sous-groupes déjà présents
naturellement dans les données (pas de filtre construit spécifiquement pour
« bien tomber ») :

| Règle | N | Taux de réussite | IC95% | Interprétation |
|---|---|---|---|---|
| Le site pronostique la victoire à domicile | 173 | **60,1 %** | [52,7% ; 67,1%] | Le filtre le plus net du pilote : quand le site joue le domicile, il a raison plus de 6 fois sur 10 |
| Le site pronostique la victoire à l'extérieur | 83 | 51,8 % | [41,2% ; 62,2%] | Proche d'une pièce non truquée |
| Le site pronostique le match nul | 37 | **18,9 %** | [9,5% ; 34,2%] | Confirme un fait bien connu du pronostic sportif : le nul est le résultat le plus difficile à prédire, et pronostiquer un nul reste statistiquement fragile même quand le site le fait |

Le filtre « victoire à domicile pronostiquée » (60,1 %, n=173) est le signal
le plus solide de ce pilote, mais **sans cote associée à ce niveau
d'agrégation**, sa rentabilité réelle reste inconnue : un taux de 60 % peut
très bien être non rentable si les cotes moyennes sur ces matchs sont
basses (favoris nets). C'est exactement le point que le cahier des charges
demande de ne jamais perdre de vue : **taux de réussite ≠ rentabilité**.

Les filtres suivants, demandés dans le cahier des charges, nécessitent des
données non disponibles dans ce pilote et n'ont donc **pas** été testés
(plutôt que testés avec des proxys approximatifs) : accord avec SofaScore
(API bloquée), écart de classement, moyenne combinée de buts, xG,
absences, jours de repos. L'infrastructure de `stats.py`
(`evaluate_filter`) est prête à les recevoir dès que ces variables seront
collectées.

## E. Comparaison avec des modèles de référence (partielle)

Comparaison possible avec les seules données réelles disponibles (base
réelle sur les 293 matchs terminés) :

| Modèle de référence | Résultat réel sur le pilote |
|---|---|
| Toujours choisir l'équipe à domicile | 46,4 % de réussite (136/293) |
| Toujours jouer « plus de 2,5 buts » | 57,3 % de réussite (168/293) — mais sans cote, ROI inconnu |
| Toujours jouer BTTS oui | 55,3 % de réussite (162/293) — mais sans cote, ROI inconnu |
| Pronostic 1N2 du site (échantillon complet) | **52,6 %** — inférieur à « toujours plus de 2,5 buts » en taux brut, supérieur à « toujours domicile » |
| Toujours choisir le favori des bookmakers | **Non calculable** : nécessite les 3 cotes (domicile/nul/extérieur) sur l'ensemble de l'échantillon ; seule la cote du pronostic choisi par le site a été collectée de façon fiable dans ce pilote |
| Modèle de Poisson (buts attendus par équipe) | **Implémenté** (`stats.poisson_match_probabilities`) mais non déployé à l'échelle du pilote : nécessite un historique de buts marqués/encaissés par équipe que ce pilote ne couvre pas de façon homogène |

**Constat honnête** : sur ce pilote, le pronostic du site ne bat pas
clairement la règle naïve « toujours plus de 2,5 buts » en taux de
réussite brut, et sa rentabilité (ROI) est négative sur le seul marché où
elle a pu être mesurée avec des cotes réelles (1N2, -11,2 %). Une
comparaison complète avec le favori des bookmakers et un modèle de Poisson
à l'échelle nécessite l'historique plus long mentionné en section 0.

## F. Limites (à lire avant toute décision)

- **Fenêtre temporelle** : 4 jours de matchs terminés (~23–26 juillet
  2026), pas 6 à 12 mois. Aucune saisonnalité, aucune stabilité mensuelle,
  aucune validation glissante n'a pu être mesurée.
- **Pas de split train/tune/test** : avec 293 matchs sur une seule fenêtre
  continue de 4 jours, un split chronologique 60/20/20 n'a pas de sens
  statistique (le « test » serait à 1 jour de distance de l'« entraînement »,
  donc pas indépendant des mêmes équipes en pleine série de forme).
- **Cotes partielles** : seuls 40 matchs sur 293 ont des cotes réelles
  collectées (1N2 du pronostic, BTTS, score exact). Le ROI du marché 1N2 sur
  l'échantillon large (293) est donc **inconnu**, seul le taux de réussite
  brut est mesuré.
- **Marché plus/moins 2,5 buts** : non publié de façon systématique par le
  site sur les pages de match consultées ; non évalué en tant que
  pronostic du site (seule la fréquence réelle de +2,5 buts dans les
  résultats a pu être mesurée : 57,3 %).
- **SofaScore** : aucune donnée SofaScore n'a pu être intégrée (API
  bloquée en accès non authentifié). Les données de forme, confrontations,
  absences citées sur les pages de footballpredictions.net elles-mêmes
  (narratif éditorial, pas une API structurée) ont été consultées
  manuellement sur un match d'exemple (Dunav Ruse – Ludogorets, page
  détail) mais pas extraites à l'échelle du pilote.
- **Correspondance équipe ↔ pronostic** : le texte du pronostic
  (« victoire de X ») est mis en correspondance avec l'équipe domicile ou
  extérieure par comparaison de chaînes normalisées. Sur les 293 matchs du
  pilote, 0 cas ambigu n'a été rencontré, mais cette méthode pourrait
  échouer sur des noms d'équipes très proches (ex : deux clubs « Sporting »)
  dans un jeu de données plus large — un contrôle manuel serait recommandé
  au-delà de quelques centaines de lignes.
- **Championnats** : 39 championnats couverts, aucun avec n ≥ 100. Toute
  affirmation du type « le site est meilleur en Ligue X » serait, à ce
  stade, statistiquement injustifiée.
- **Risque de surapprentissage** : volontairement limité en ne testant que
  3 filtres simples (section D) plutôt que des dizaines, précisément pour
  éviter la sélection a posteriori que la faible taille d'échantillon
  rendrait trompeuse.
- **Combinés (paris multiples)** : le site propose des « paris combinés »
  (paris quintuple/quadruple visibles sur les pages consultées), mais ces
  combos n'ont pas été suivis dans le temps dans ce pilote. La section 9
  du cahier des charges (paris simples vs combinés) ne peut donc être
  traitée qu'au niveau théorique (voir ci-dessous), pas empiriquement.

### Note théorique sur les combinés (à défaut de données empiriques)

Avec les taux mesurés sur ce pilote (1N2 ≈ 47–53 %, BTTS ≈ 61 %), un combiné
à 2 sélections indépendantes tomberait, en théorie, autour de 0,50 × 0,61 ≈
**31 %** de probabilité de réussite conjointe, et un combiné à 3 sélections
autour de **19 %** — *si* les sélections étaient statistiquement
indépendantes. En pratique, les résultats de matchs de la même journée ne
sont jamais parfaitement indépendants (mêmes conditions météo par zone,
même dynamique de championnat, corrélation entre BTTS et plus de 2,5 buts
sur les mêmes matchs), ce qui rend cette estimation optimiste. Combiné à la
marge du bookmaker qui s'applique à chaque sélection du combiné, la
rentabilité espérée d'un combiné est structurellement inférieure ou égale à
celle des paris simples correspondants — c'est un résultat mathématique
général, pas spécifique à ce site, et il est cohérent avec la littérature
sur les paris sportifs. **Aucun chiffre de ROI réel sur des combinés n'est
présenté ici**, faute de suivi réel dans le temps.

## G. Stratégies (prudente / équilibrée / agressive) — état actuel

Le cahier des charges demande jusqu'à trois stratégies exploitables avec
performances vérifiées hors échantillon. **Aucune des trois ne peut être
présentée comme validée aujourd'hui**, faute d'échantillon de test
indépendant (section F). Ce qui peut être dit honnêtement :

- **Piste la plus prometteuse pour une future stratégie « prudente »** :
  se limiter aux pronostics « victoire à domicile » du site (60,1 % de
  réussite brute sur n=173), en excluant les nuls. Cette piste doit être
  reconfirmée sur au moins 100 pronostics de la même catégorie **collectés
  après la date de ce rapport**, avec leurs cotes, avant d'être considérée
  comme une stratégie.
- **Aucune piste « équilibrée » ou « agressive »** n'est proposée : les
  proposer sur la base de 28 à 40 paris avec cotes serait donner une
  fausse impression de robustesse.
- **Prochaine étape concrète** : exécuter `scraper.py --collect-today`
  quotidiennement (ou via une tâche planifiée) pendant au moins 4 à 6 mois,
  puis relancer `run_analysis.py` avec le module `stats.chronological_split`
  et `stats.walk_forward_folds` déjà prêts pour produire un vrai split
  60/20/20 et une validation glissante.

**Conclusion honnête** : à ce stade, **aucun avantage statistique robuste
n'a été démontré** pour footballpredictions.net. Le signal le plus net
(pronostics de victoire à domicile, ~60 %) est intéressant mais repose sur
un échantillon trop petit et sans cotes pour en évaluer la rentabilité. Ne
pas parier sur la base de ce seul rapport.

---

## 11. Analyse du jour (26 juillet 2026, données collectées 18:00–18:15 UTC)

Conformément à la règle du cahier des charges (« n'afficher que les matchs
correspondant à une stratégie validée »), et puisqu'**aucune stratégie n'a
été validée** à l'issue du backtest ci-dessus, **aucun match ci-dessous
n'est classé « sélection principale » ou « sélection secondaire »**. Le
tableau suivant est fourni à titre **strictement informatif** (ce que le
site pronostique aujourd'hui, avec les cotes qu'il affiche), pas comme une
recommandation de pari.

| Match | Championnat | Pronostic 1N2 du site | Cote | BTTS | Cote BTTS | Score exact | Cote | Prob. implicite (1N2) | Historique validé ? |
|---|---|---|---|---|---|---|---|---|---|
| Monterrey – Necaxa | Mexique : Liga MX | Victoire de Monterrey | 2,05 | Oui | 1,53 | 1-2 | 9,0 | 48,8 % | Non (Mexique hors échantillon testé) |
| Atlético Acassuso – San Miguel | Argentine : Primera B Nacional | Victoire de San Miguel | 1,66 | — | — | 4-0 | 26,0 | 60,2 % | Non (championnat non couvert par le pilote) |
| Estudiantes de La Plata – Independiente | Argentine : Torneo Clausura | Victoire d'Estudiantes | 2,10 | — | — | 1-0 | 5,0 | 47,6 % | Non (n=12 dans le pilote, insuffisant) |
| Bahia – Corinthians | Brésil : Serie A | Victoire de Bahia | 2,35 | Oui | 1,80 | 2-1 | 9,5 | 42,6 % | Non (n=8 dans le pilote, insuffisant) |
| Criciuma – Náutico | Brésil : Serie B | Victoire de Criciuma | 1,56 | Oui | 2,00 | 2-1 | 8,5 | 64,1 % | Non (championnat non couvert) |
| Lokomotiv Plovdiv – Septemvri Sofia | Bulgarie : Première Ligue | Victoire de Lokomotiv Plovdiv | 1,68 | — | — | 2-0 | 7,5 | 59,5 % | Non (championnat non couvert) |
| Palestino – Ñublense | Chili : Campeonato Nacional | Victoire de Ñublense | 2,15 | Oui | 1,83 | 2-1 | 9,5 | 46,5 % | Non (championnat non couvert) |
| GKS Katowice – Wisła Kraków | Pologne : Ekstraklasa | Match nul | 3,40 | Oui | 1,67 | 1-1 | 7,0 | 29,4 % | Non — et le nul est le pronostic le moins fiable du pilote (18,9 % de réussite sur 37 cas) |

**Catégories demandées par le cahier des charges** :
- **Sélection(s) principale(s) : aucune.**
- **Sélection(s) secondaire(s) : aucune.**
- **Matchs à éviter en pari : les 8 ci-dessus**, non pas parce qu'ils sont
  mauvais individuellement, mais parce qu'**aucun d'eux ne répond à une
  règle validée statistiquement** dans ce rapport — parier dessus sur la
  seule foi de ce document ne serait pas justifié.

*Données collectées le 26/07/2026 entre 18:00 et 18:15 UTC directement
depuis footballpredictions.net/fr. Les cotes affichées sont celles publiées
par le site au moment de la collecte et sont susceptibles d'avoir changé
avant le coup d'envoi.*

---

## Reproduire / poursuivre ce travail

```bash
cd football_predictions_analysis
pip install requests beautifulsoup4

# Collecte quotidienne (à planifier, ex. cron à 12:00 chaque jour)
python3 scraper.py --collect-today --out data/predictions_log.csv

# Détail (cotes) d'une liste de matchs terminés ou à venir
python3 scraper.py --collect-details data/detail_sample_urls.txt --out-details data/predictions_details_log.csv

# Analyse
python3 run_analysis.py
```

Après plusieurs mois de collecte quotidienne, relancer `run_analysis.py` en
y branchant `stats.chronological_split` (60/20/20) et
`stats.walk_forward_folds` pour obtenir enfin le backtest tel que défini
dans le cahier des charges initial.
