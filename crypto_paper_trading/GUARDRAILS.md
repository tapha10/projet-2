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

Si le capital réalisé d'un bras recule de **plus de 15 %** depuis son plus haut,
les nouvelles entrées de ce bras sont **suspendues** (refus par la base), et le
rapport hebdomadaire affiche une alerte. La reprise demande une décision humaine.

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
glissement (forfait de 0,1 % seulement), de la profondeur de marché et du
funding réel (estimé à 0,01 % par 8 h). **Chaque rapport le dit.**

## 8. Limites de l'auto-amélioration

- Aucun changement de paramètre tant qu'un bras n'a pas **30 trades fermés**.
- **Un seul changement à la fois**, limité à **±20 %** de la valeur actuelle.
- Validation **walk-forward** (70 % anciens / 30 % récents) et promotion seulement
  si l'espérance est meilleure **et** que l'intervalle de confiance bootstrap de
  la différence reste positif.
- Retour à la version précédente si l'espérance baisse sur 20 trades.
- L'auto-amélioration ne peut modifier ni ce fichier, ni les limites des sections 1 à 4.

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
