# Chaînes de victoires — logique actuelle (mémoire du projet)

> PAPIER UNIQUEMENT. Ce fichier est mis à jour à chaque changement de logique ; l'état chiffré
> (chaînes, étapes, seuils, décisions et leurs raisons) est dans Supabase : `chain_params`,
> `chains`, `chain_steps`, `chain_gating`, `chain_decisions`, `chain_sim_runs`, `chain_stats`.
> Pour reprendre après une coupure : lire ce fichier, puis `select paper_chain_data();`.

Dernière mise à jour : 04/10/2026 (activation, lecture seule jusqu'au 11/10/2026 vers 12:10, heure de Paris).

## 1. Principe (modèle de l'utilisateur = variante de départ, pas une vérité)

- Étape 1 : risque 1 % du capital K (1 000 USDT -> 10 USDT), stop 10 %, objectif +30 % (3R).
- Étapes 2 à 5 : risque = gain de l'étape précédente (« argent de la maison »), stop 5 %, objectif +15 %.
- Perte maximale d'une chaîne = 1 % du capital. Exemple de référence (capital 10 000, risque 100) :
  gains 300 / 900 / 2 700 / 8 100 / 24 300 = 36 300 ; bilan si échec à l'étape 1 à 5 :
  -100 / 0 / +300 / +1 200 / +3 900 (vérifié par les tests).
- Taille = risque / distance du stop ; levier ≤ 3x ; liquidation ≥ 2 fois le stop ; taille ≤ 0,1 % du
  volume 24 h ; si impossible : **risque réduit**, jamais le stop élargi (noté dans `chain_decisions`).
- Échec (stop) : la chaîne s'arrête, une nouvelle repart à 1 %. 5 victoires : gain encaissé.

## 2. Qui fait quoi

| Moment | Qui | Quoi |
|---|---|---|
| 14:00 | routine 1 | signaux du jour (décision `enter` = « accepté ») |
| 14:20 | routine 7 `decide` | pour chaque chaîne libre : prend le meilleur signal accepté des 24 dernières heures dont le score atteint le seuil du niveau ; sinon « attendre » |
| 08:00 / 14:30 / 20:00 / 23:30 | routine 2 | détecte stop / objectif des positions K (moteur existant, ordre tranché à la minute) ; la base met à jour l'étape et la chaîne |
| 05:45 | routine 7 `daily` | si les routines 5 et 6 ont fini : rejoue en ombre toutes les variantes sur les signaux enregistrés, Monte Carlo 10 000 chaînes, photo `chain_stats` ; sinon attend 30 min puis écrit « non exécutée » |
| dimanche 11:30 | routine 7 `weekly` | rejeu historique + ombre, comparaison aux références (aléatoire, prend tout, risque fixe) hors échantillon, test « main chaude », recherche de critères, proposition de seuil (une à la fois), statuts des variantes |
| dimanche 18:00 | routine 4 | section « chaînes de victoires » du rapport |

## 3. Score et seuils

- Score de qualité = score de la routine 1 (substitut tant qu'aucun critère n'est validé par la
  routine 6) + poids (10 x borne basse du lift) des critères validés présents.
- Seuils de départ (hypothèses) : niveau 1 ≥ 3, niveau 2 ≥ 3, niveau 3 ≥ 4, niveau 4 ≥ 5, niveau 5 ≥ 5.
- Modification : une seule à la fois (±1 sur un niveau), choisie sur les 70 % anciens, gardée seulement
  si sur les 30 % récents l'espérance modélisée (glissement x2) ET P(5) s'améliorent, et si la hausse
  du taux de victoire au niveau modifié reste significative après Benjamini-Hochberg (q = 0,10).
  Pendant la lecture seule, la proposition est seulement écrite.

## 4. Variantes comparées (16)

utilisateur_5x3R (champion de départ) ; chaine_3 ; R2, R4, R5 ; stop10_constant, stop5_constant,
stop15_45pc ; reinvest_75, reinvest_50 ; securiser_3j (encaisse après 3 j sans signal assez bon) ;
reinitialiser_50 (après 3 j : encaisse 50 %, le reste repart avec les seuils du niveau 1) ;
seuils_plats_3 ; seuils_stricts ; levier_5x_ombre, levier_7x_ombre (ombre seulement).

## 5. Ce que disent les données au 04/10/2026 (rejeu historique, 150 jours, 80 paires)

- 159 signaux historiques (50 paires, 128 événements indépendants), tous gardés, y compris ceux qui n'ont rien donné.
- Hausse maximale médiane sur 10 jours : **+15 %** sur l'ensemble des signaux, **+29 %** sur les cas de pump
  connus : mesurer l'amplitude sur des cas déjà pompés la surestime d'environ un facteur 2.
- Stop 10 % / objectif +30 % : objectif atteint dans **17 %** des cas (équilibre 3R : 25 %).
- Modèle de l'utilisateur : 38 chaînes, aucune au-delà du niveau 1, espérance −0,20 R par chaîne
  (−0,21 R avec glissement x2) ; « prends tout » −0,18 R ; aléatoire médian −0,25 R.
- Même stratégie sans enchaînement (risque fixe 1 %) : 80 trades, +32,7 USDT, drawdown max 10,7 % :
  **l'enchaînement ne bat pas le risque fixe** sur ces données.
- Test « main chaude » : inconclusif (une seule étape après 2 victoires).
- Verdict : **inconclusif**, aucune variante n'a d'avantage mesuré ; il manque des chaînes indépendantes
  (au moins 30 au niveau testé, 100 pour conclure « impossible avec ces critères »).

## 6. Exploration (anti-cercle vicieux, 04/10/2026)

Si aucune étape n'a été décidée depuis **7 jours** (comptés depuis la fin de la lecture seule), le
mode `decide` peut ouvrir **une** étape 1 d'exploration par passage : signal refusé seulement pour
son score (`decision_reason` commençant par « score »), sans alerte, au seuil du niveau 1 **moins 1**,
à **demi-risque** (0,5 % du capital K). Les autres règles (levier ≤ 3x, liquidation ≥ 2 x stop,
0,1 % du volume 24 h, 3 chaînes au plus, suspension à 15 % de drawdown global) restent identiques.
`paper_chain_data()` fournit pour cela `alerts` et `decision_reason` de chaque signal.

Passages depuis le 04/10/2026 : mode `daily` dans le passage du matin (05:30, après R5 et R6),
`weekly` le dimanche dans ce même passage, `decide` dans le passage de 14:00 (après R1).
