# Audit du suivi des positions (bougies, ordre stop / objectif) — 3 octobre 2026

> **DÉMO UNIQUEMENT.** Cet audit rend les résultats papier plus fidèles. Il n'ajoute aucune
> fonction de trading réel. Tout passage au réel suppose de relire `GUARDRAILS.md` ensemble.

## 1. Ce qui a été vérifié

Le suivi des positions a été vérifié sur trois plans : le code (`simulate.py`, `tiers.py`,
`cli.py check`, `cli2ter.check_t`), la base Supabase et des données de marché réelles.
Au moment de l'audit, la base ne contenait **aucune position** : aucun résultat passé
n'est donc faussé.

## 2. Défauts trouvés et corrections

| # | Défaut | Effet | Correction | Test |
|---|---|---|---|---|
| 1 | Chaque vérification relisait la dernière bougie déjà traitée, avec le stop déjà déplacé. | **Fausses sorties à l'équilibre ou au stop suiveur**, reproduites. | Nouvelle colonne `sim_through_at` : chaque bougie fermée est traitée une seule fois. | `test_candle_not_reread`, `test_no_gap_between_checks` |
| 2 | La bougie 15 min en cours (incomplète) était traitée, puis retraitée. | Plus haut, plus bas et stop calculés sur une bougie partielle. | Seules les bougies fermées sont traitées ; la bougie en cours attend la vérification suivante. La sortie reste datée à la bonne minute. | `test_open_candle_waits` |
| 3 | Stop et objectif touchés dans la même bougie 15 min : le stop était toujours retenu. | Pessimiste. | La bougie est rejouée en bougies de 1 min ; « stop d'abord » ne s'applique que si les deux tombent dans la même minute. | `test_tp_first_in_minutes`, `test_stop_first_in_minutes`, `test_same_minute_stays_prudent` |
| 4 | Passage à l'équilibre ou stop suiveur déclenché puis touché dans la même bougie : ignoré. | **Optimiste** : un vrai stop déplacé aurait fermé la position. | Rejeu en 1 min, le stop déplacé s'applique dès la minute suivante. | `test_breakeven_inside_candle` |
| 5 | La bougie d'entrée était ignorée entièrement. | Un stop touché entre l'entrée et la fin du quart d'heure n'était pas vu. | Rejeu en 1 min à partir de la minute qui suit l'entrée ; les prix d'avant l'entrée ne comptent pas. | `test_prices_before_entry_ignored`, `test_prices_after_entry_count` |
| 6 | Funding forfaitaire : 0,01 % par 8 h, au prorata. | Sous-estimé d'un facteur 2,3 sur les plus fortes hausses (voir §3). | Taux réellement réglés (historique Gate) entre l'entrée et la sortie ; le forfait ne sert que si l'historique est indisponible. | `test_real_rates_between_entry_and_exit` |
| 7 | Objectif rempli exactement au prix visé. | Optimiste : un TP Bybit est un ordre au marché déclenché. | Glissement de 0,1 % aussi sur l'objectif. | référence A/B/C régénérée, voir §5 |
| 8 | Frais à 0,05 % par côté. | Légèrement sous Bybit. | 0,055 % par côté (preneur Bybit), sorties à l'objectif comprises. | migration `007_candle_audit.sql`, journal `iteration_log` |

Le rejeu en 1 min s'applique à toute bougie où il se passe quelque chose : stop, objectif,
liquidation, passage à l'équilibre, stop suiveur, et pour le portefeuille T, les objectifs
et stops de chaque tranche et le stop chandelier. Les données 1 min viennent de Gate
(environ 6 jours d'historique), puis d'OKX au-delà. Sans données 1 min, la règle prudente
« stop d'abord » s'applique, et la note `price_checks` le signale.

Chaque ligne `price_checks` indique combien de bougies ont été rejouées en 1 min, si une
règle prudente a servi, et la source du funding (réel Gate ou forfait).

## 3. Contre-épreuve sur données réelles

Méthode :

- 360 positions fictives (bras A, B et C) ont été ouvertes toutes les 12 h sur les
  12 perps qui ont le plus bougé dans les 5 jours précédant le 3 octobre 2026 ;
- l'entrée tombe 7 minutes après le début d'un quart d'heure ;
- chaque position a été suivie deux fois : en 15 min seul (ancien moteur), puis avec rejeu
  en 1 min (nouveau moteur).

| Mesure | Résultat |
|---|---|
| Bougies 15 min rejouées en 1 min | 837 |
| Bougies tranchées par la règle prudente faute de 1 min | 0 |
| Positions dont seule l'heure de sortie change (plus précise, à la minute) | 178 |
| Positions dont le **résultat** change | 4 |
| PnL de ces 4 positions, ancien → nouveau moteur | +22,05 → −14,24 USDT |
| Funding réel / forfait (195 positions clôturées) | 12,92 / 5,67 USDT |

Le cas le plus parlant : 龙虾USDT, bras B, entrée le 1ᵉʳ octobre.

- L'ancien moteur donnait un objectif atteint, à **+33,22 USDT**.
- À la minute, le prix touche +15 % (le stop passe à l'entrée), redescend sous l'entrée à
  10:58, et la position sort à l'équilibre, à **−0,18 USDT**.
- C'est ce qu'aurait fait un vrai stop déplacé. L'ancien moteur surestimait ce cas.

Les écarts de funding vont jusqu'à ±1,4 USDT par position, soit environ ±0,14 R. Le funding
est souvent élevé sur les cryptos qui viennent de monter fort.

## 4. Ce qui reste différent d'un vrai compte Bybit

Il s'agit de limites connues, et non d'ajouts à faire maintenant. Tout passage au réel
exige la relecture de `GUARDRAILS.md` ensemble.

1. **Source des prix.** Bybit est bloqué depuis l'environnement cloud (réponse 403,
   vérifié le 3 octobre 2026). Bougies, funding et liste des perps viennent donc de Gate,
   puis d'OKX. Les prix entre bourses diffèrent souvent de 0,05 à 0,3 % sur les petites
   cryptos, davantage pendant les pics. Un perp listé sur Gate peut aussi être absent de
   Bybit.
2. **Déplacement des stops.** La simulation déplace le stop (équilibre B, suiveur C,
   chandelier T) en moins d'une minute. Les routines ne tournent que 4 fois par jour. En
   réel, il faudrait des ordres conditionnels gérés par la bourse elle-même, par exemple
   le stop suiveur natif. Ces ordres n'ont pas exactement les mêmes règles que la
   simulation.
3. **Prix de déclenchement.** Le moteur déclenche sur le dernier prix échangé, comme les
   TP/SL de Bybit par défaut. La liquidation, chez Bybit, se calcule sur le *mark price* ;
   l'estimation du moteur est donc plutôt prudente.
4. **Glissement.** Le forfait est de 0,1 % par exécution. Sur une petite crypto en plein
   pic, ou en cas de trou de cotation sous le stop, le vrai glissement peut être bien plus
   grand. Les trous de cotation sont exécutés au prix d'ouverture.
5. **Funding.** Ce sont les taux de Gate, proches mais pas identiques à ceux de Bybit ;
   l'intervalle de règlement peut aussi différer d'une crypto à l'autre.
6. **Quantités.** Le moteur ne tient pas compte de la taille minimale d'ordre ni du pas
   de quantité de Bybit, ce qui donne de petits écarts de taille.
7. **Moment d'entrée.** Le moteur prend le dernier prix 15 min connu au moment du passage,
   plus 0,1 %. Les routines démarrent avec quelques minutes de décalage aléatoire.

## 5. Non-régression

- 97 tests, tous verts.
- La référence A/B/C (`tests/baseline_before_2ter.json`) a été régénérée à cause du
  correctif 7. Il a été vérifié avant de régénérer que **seules les sorties à l'objectif**
  changent : 52 en A, 31 en B, 26 en C. Taille, levier et raison de sortie sont
  identiques. L'écart moyen est de −0,006 R (A), −0,012 R (B) et −0,008 R (C), soit le
  coût de 0,1 % de glissement.
- Les rejeux de recherche (`outcomes`, `adapt`, R5, ombres des paliers) restent en bougies
  de 1 h, avec la règle « stop d'abord ». Ce choix est prudent, et seul le suivi des
  positions vivantes compte dans le capital.
