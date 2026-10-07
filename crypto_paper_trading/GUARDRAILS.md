# GUARDRAILS — règles non négociables

> Ce fichier ne peut **jamais** être modifié par une routine. Les routines n'ont
> pas le droit de faire de commit ni de push : elles écrivent uniquement dans
> Supabase. Toute modification de ce fichier se fait à la main, en le relisant
> avec le propriétaire du projet.

## 1. Démo uniquement

- Aucun ordre réel. Aucune clé d'API d'exchange, encore moins avec droit de trading.
- Seules des données de marché **publiques, en lecture seule** sont utilisées
  (Gate.io, OKX, MEXC, KuCoin, CoinGecko, recherche web).
- Le code ne contient aucun client d'exchange authentifié et ne doit jamais en contenir.
- La base refuse toute valeur de `config.mode` autre que `paper` (trigger `config_guardrails`).
- Même si on le demande plus tard, **aucune fonction de trading réel n'est ajoutée**
  sans avoir relu ce fichier avec le propriétaire.

## 1 bis. Seuil avant toute discussion sur le réel (relecture du 03/10/2026)

Le système reste en démo. Une nouvelle relecture de ce fichier pour envisager le réel
n'est possible que lorsqu'**un bras** remplit **toutes** ces conditions :

| Condition | Seuil |
|---|---|
| Trades fermés du bras | **≥ 50** |
| Durée de la démo (depuis `config.demo_started_at`, le 03/10/2026) | **≥ 3 semaines** (ramené de 12 à 3 le 07/10/2026 à la demande du propriétaire) |
| R moyen par trade | **> 0** et intervalle de confiance bootstrap à **90 %** entièrement positif |
| Drawdown maximum (réalisé + latent) | **< 15 %** |
| Incidents de données ou d'exécution | **aucun** non expliqué |

Le rapport du dimanche affiche où en est chaque bras. Atteindre le seuil **n'autorise
rien** : il permet seulement de rouvrir la discussion, en relisant ce fichier ensemble.
Les résultats de démo viennent des prix Gate/OKX et non de Bybit (bloqué depuis le
cloud) ; les écarts connus sont listés dans `docs/audit_bougies.md`.

## 2. Capital virtuel

- Capital de départ : **1 000 USDT par bras** (clé `initial_capital_usdt` de la table `config`).
- Interprétation retenue : chaque bras (A, B, C) est un **portefeuille virtuel séparé**
  qui reçoit les mêmes signaux. Les plafonds ci-dessous s'appliquent **par bras**.
  La ligne `daily_results.equity` est la somme des trois portefeuilles.

## 3. Risque et plafonds (par bras)

| Règle | Limite |
|---|---|
| Risque par trade (perte au stop) | **1 %** du capital virtuel du bras, au maximum |
| Levier | **10x** maximum (bras A : **2x** maximum) |
| Positions ouvertes en même temps | **8** maximum |
| Nouvelles entrées par jour (heure de Paris) | **3** maximum |
| Même pair ouvert deux fois dans le même bras | **interdit** |
| Sens | long uniquement, stop < entrée < objectif |

Ces limites sont codées **en dur** dans la base (`paper_hard_limits()`) et
vérifiées par le trigger `positions_guardrails_insert` à chaque insertion.
La table `config` peut les rendre plus strictes, jamais plus laxistes
(trigger `config_guardrails`). Une position ne peut pas voir ses paramètres
d'entrée modifiés, et son stop ne peut que monter (`positions_guardrails_update`).

## 4. Drawdown

Si le capital **réalisé + latent** d'un bras (positions fermées + PnL non réalisé des
positions ouvertes) recule de **plus de 15 %** depuis son plus haut, les nouvelles
entrées de ce bras sont **suspendues** (refus par la base), et le rapport hebdomadaire
affiche une alerte. La reprise demande une décision humaine.
Le latent de chaque position est enregistré (`arm_marks`, `paper_set_marks`) à chaque
vérification et juste avant chaque décision d'entrée ; une position fermée cesse d'être
comptée en latent. La taille des positions reste calculée sur le capital réalisé.
(Relecture du 03/10/2026 : auparavant, seul le capital réalisé comptait.)

## 5. Secrets

Aucune clé ni secret dans le dépôt Git. Les routines accèdent à Supabase par le
connecteur Supabase de Claude (pas de clé stockée) ; tout autre secret irait dans
les variables d'environnement ou les secrets de la plateforme.

## 6. Traçabilité

Chaque décision (`enter`, `wait`, `skip`) est enregistrée dans `signals` avec sa
raison (`decision_reason`) et ses sources datées (`evidence` : url, titre,
date de publication ; `info_published_at`). Chaque entrée refusée par un
garde-fou est écrite dans `iteration_log`. Chaque changement de stratégie est
écrit dans `strategy_versions` et `iteration_log` avec sa justification chiffrée.

## 7. Honnêteté des résultats

Aucun résultat n'est garanti. Les chiffres en démo ignorent une partie du
glissement réel (forfait de 0,1 % par exécution, objectif compris) et la profondeur
de marché. Les prix, les bougies 1 minute et le funding réellement réglé viennent de
sources publiques (Gate.io, puis OKX), **pas de Bybit** ; les frais sont ceux de Bybit
(0,055 % par côté). L'ordre stop / objectif est tranché à la minute ; s'il reste
inconnu, le stop compte d'abord. Détail : `docs/audit_bougies.md`. **Chaque rapport le dit.**

## 8. Limites de l'auto-amélioration

- Aucun changement de paramètre tant qu'un bras n'a pas **30 trades fermés**.
- **Un seul changement à la fois**, limité à **±20 %** de la valeur actuelle.
- Validation **walk-forward** (70 % anciens / 30 % récents) et promotion seulement
  si l'espérance est meilleure **et** que l'intervalle de confiance bootstrap de
  la différence reste positif.
- Retour à la version précédente si l'espérance baisse sur 20 trades.
- L'auto-amélioration ne peut modifier ni ce fichier, ni les limites des sections 1 à 4.

**Anti-cercle vicieux (ajouté le 04/10/2026 à la demande du propriétaire).** Sans trade, rien ne
s'apprend ; sans apprentissage, aucun trade. Deux corrections, sans toucher aux limites 1 à 4 :

- **Trades contrefactuels pour l'adaptation** : tant qu'un bras a moins de 30 trades fermés, son
  échantillon est complété par les signaux **non entrés** dont les 10 jours sont écoulés (entrée au
  prix de détection, un seul par événement indépendant : même pair à moins de 10 jours). Toutes les
  autres conditions (30 au total, un seul changement, ±20 %, walk-forward 70/30, IC bootstrap > 0,
  retour arrière) restent identiques ; le rapport précise que l'échantillon contient des contrefactuels.
- **Exploration** : si un bras n'a pris **aucune entrée depuis 7 jours** (`config.exploration_after_days`,
  à défaut depuis `demo_started_at`), le moteur peut prendre **une seule** entrée d'exploration par
  passage, à **demi-risque** (0,5 %), sur un signal refusé **uniquement** pour son score (score ≥ seuil − 1),
  sans aucune alerte. Mêmes plafonds, mêmes garde-fous de la base. Pour la routine 7 : après 7 jours
  sans étape (comptés depuis la fin de la lecture seule), une étape 1 à demi-risque au seuil du niveau 1
  moins 1, une par passage. Chaque entrée d'exploration est marquée comme telle dans sa justification.

## 9. Addendum 2ter — portefeuille des paliers « T » (règles plus strictes, ajoutées le 03/10/2026 avec le propriétaire)

Les paliers P1-P4 vivent dans un portefeuille virtuel séparé « T » (1 000 USDT). En plus des
sections 1 à 8, toute position du portefeuille T respecte, et la base l'impose par trigger :

| Règle | Limite |
|---|---|
| Levier | **3x** maximum |
| Taille d'une position | **25 %** du capital T au maximum |
| Notionnel total ouvert | **150 %** du capital T au maximum |
| Liquidation estimée | au moins **3 fois** plus loin que le stop |
| Moyenne à la baisse | interdite (un même pair ne peut pas être ouvert deux fois dans T) |
| Risque par position (toutes tranches) | **1 %** au maximum ; palier P4 : 0,5 % au maximum |
| Palier supérieur débloqué | commence à 0,25 % de risque, puis 0,5 % et 1 % après ≥ 3 semaines et ≥ 15 événements |

Les bras A, B et C gardent leurs limites d'origine (section 3). La routine 6 n'ouvre jamais de
position et ne peut pas modifier ces limites.

## 10. Prompt 3 — routine 7 « chaînes de victoires » (portefeuille « K », ajouté le 04/10/2026 à la demande du propriétaire)

Papier uniquement, aucun secret dans le dépôt. Les chaînes vivent dans un portefeuille virtuel
séparé « K » (1 000 USDT). Plafonds imposés par la base (fonction `enforce_chain_position`,
triggers `chains_guardrails` et `positions_chain_close`) et par le code (`engine/chains.py`) :

| Règle | Limite |
|---|---|
| Risque de l'étape 1 | **1 %** du capital virtuel K |
| Risque des étapes suivantes | jamais plus que le **gain de l'étape précédente** (perte maximale d'une chaîne = 1 % du capital) |
| Chaînes ouvertes | **3** au plus, **1 position** par chaîne, un même pair jamais ouvert deux fois |
| Levier des chaînes | **3x** par défaut ; variantes 5x et 7x **en ombre seulement** tant qu'elles ne sont pas validées |
| Stop | **≤ 15 %**, objectif = R x stop ; stop jamais déplacé dans le mauvais sens ; aucune moyenne à la baisse |
| Liquidation estimée | au moins **2 fois** plus loin que le stop (glissement compris) |
| Taille | **exception explicite** à « position ≤ 25 % du capital » (section 9) : la valeur nominale d'une position de chaîne peut dépasser 25 % du capital, mais jamais le levier maximum ni **0,1 % du volume 24 h** du pair |
| Suspension | routine 7 suspendue (refus par la base) si le **drawdown global** (tous portefeuilles, latent compris) atteint **15 %** |
| Démarrage | **7 jours de lecture seule** après l'activation (`config.chain_readonly_until`), puis chaînes en papier |

Quand la taille voulue dépasse un plafond, c'est le **risque** de l'étape qui est réduit, jamais le
stop qui est élargi. La routine n'ouvre jamais de position hors du papier et ne contourne aucun de
ces plafonds ; l'auto-optimisation (seuils de score par niveau) ne peut modifier ni ce fichier ni
ces limites. Les bras A, B, C et le portefeuille T gardent leurs règles (sections 3 et 9).

## 11. Portefeuille « S » — stratégie inverse (short), démo uniquement (ajouté le 07/10/2026 à la demande du propriétaire)

Les sections 1 à 4 restent en vigueur, **y compris « long uniquement » pour la table `positions`** :
aucun short n'y entre jamais. La stratégie inverse vit dans une **table séparée**
`inverse_positions` (`sql/011_inverse.sql`, code `engine/inverse.py`), **papier uniquement**,
sans exchange, sans clé, sans ordre. Elle reprend chaque entrée longue des bras A, B, C et T (un short
par signal, au même prix d'entrée) et les rejoue sur l'historique.

| Règle | Limite |
|---|---|
| Sens | short ; la base impose objectif < entrée < stop (contrainte `check`) |
| Levier | **2x** maximum |
| Stop | **30 %** au-dessus de l'entrée au départ, jamais élargi (trigger `inverse_guardrails_update`) |
| Objectif | **10 %** sous l'entrée ; sortie par le temps après **7 jours** |
| Risque par trade | **1 %** du capital virtuel S (1 000 USDT de départ) |
| Positions | **8** ouvertes au plus, **3** entrées par jour (Paris), un même pair jamais deux fois |
| Drawdown | entrées suspendues si le capital réalisé recule de plus de **15 %** depuis son plus haut |

Les valeurs de départ (stop 30 %, objectif 10 %, option de TP « suiveur » `tp_trail_pct`) sont dans
`config.inverse_params` ; elles ne s'appliquent qu'aux **nouvelles** entrées et suivent la règle de la
section 8, appliquée automatiquement par `python3 -m engine.inverse adapt` (aucun changement avant
30 trades fermés dans S, un seul à la fois parmi stop / objectif / durée, ±20 %, walk-forward 70/30,
IC bootstrap > 0, retour arrière sur 20 trades). Levier, risque, 8 positions et 3 entrées par jour sont plafonnés dans le code. Le portefeuille
S ne compte pas dans le seuil de la section 1 bis et **ne donne aucun droit** à un passage en réel.

## Relectures avec le propriétaire

| Date | Décisions |
|---|---|
| 03/10/2026 | Addendum 2ter (section 9). |
| 03/10/2026 | Démo maintenue ; seuil de la section 1 bis (50 trades, 12 semaines, IC 90 % > 0, drawdown < 15 %, aucun incident) ; limites de la section 3 inchangées ; drawdown sur réalisé + latent (section 4) ; section 7 mise à jour après l'audit des bougies ; section 8 inchangée. |
| 04/10/2026 | Prompt 3 : section 10 (chaînes de victoires, portefeuille K), règles fournies par le propriétaire. |
| 04/10/2026 | Section 8 : anti-cercle vicieux (trades contrefactuels pour l'adaptation, exploration à demi-risque après 7 jours sans entrée), à la demande du propriétaire. Limites des sections 1 à 4 inchangées. |
| 07/10/2026 | Section 11 : portefeuille S (stratégie inverse, short, démo) dans une table séparée, stop 30 % / objectif 10 % ; sections 1 à 4 inchangées, démo maintenue, aucun passage en réel. |
| 07/10/2026 | Section 1 bis : durée minimale de démo ramenée de **12 à 3 semaines** (à la demande du propriétaire) ; les autres conditions (50 trades fermés, R moyen > 0 avec IC 90 % entièrement positif, drawdown < 15 %, aucun incident) sont inchangées ; atteindre le seuil n'autorise toujours rien : il rouvre seulement la relecture de ce fichier ensemble. Le portefeuille S est évalué comme les autres bras. |
