# Stratégie courante (lisible)

> Source de vérité : tables `strategy_versions` (paramètres par bras) et `config`
> (`entry_rules`, `signal_weights`) dans Supabase. Ce fichier décrit la version
> de départ (v1). Les versions suivantes, produites par la routine d'adaptation,
> sont lisibles dans `strategy_versions` (colonne `rationale`) et dans le rapport
> hebdomadaire.

## Hypothèses de départ (à tester, pas des certitudes)

Issues d'une étude manuelle de **4 cas seulement** (VELVET x2, PUMP, COTI), tous
suivis d'une hausse : le vrai taux de réussite est **inconnu**, c'est ce que le
système mesure.

- Pic médian 8-9 jours après le signal, puis le prix rend 20 à 80 % de la hausse
  → sortie par le temps à **10 jours**.
- **Ne jamais acheter la bougie du signal** (+15 % ou plus sur 24 h) : sur VELVET,
  les 4 grosses bougies ont perdu 11 à 44 % le lendemain.
- Bruit élevé (souvent > 10 %/jour sur les petites capitalisations) : un stop trop
  serré saute par bruit.

## Détection et score

Candidats collectés chaque jour à 14:00 (Paris) : plus fortes hausses 24 h des perps
USDT crypto liquides (≥ 2 M USDT/24 h), nouveaux perps listés depuis moins de 7 jours,
puis recherche d'annonces datées sur le web.

| Type de signal | Poids | Détection |
|---|---|---|
| `dated_announcement` (partenariat, listing, perp annoncé) | +2,0 | recherche web, date de publication obligatoire |
| `listing_or_perp` | +2,0 | perp lancé sur Gate depuis < 7 j, ou annonce |
| `volume_doubling` | +1,5 | volume au moins doublé chaque jour, 2 jours de suite |
| `oi_rising` | +1,0 | open interest +20 % sur 3 jours |
| `revenue_or_buyback` | +1,0 | revenus ou rachats publics (web) |
| `oversold_or_breakout` | +1,0 | RSI14 < 30, ou clôture au-dessus du plus haut 20 j |
| `top_gainer_24h` | +0,5 | +10 % ou plus sur 24 h |
| `alert_team_transfer` | −3,0 | transferts équipe / market maker vers exchanges → **skip** |
| `alert_unlock_7d` | −3,0 | unlock > 0,5 % de l'offre dans les 7 jours → **skip** |
| `alert_peak_passed` | −2,0 | +50 % en 10 j puis −25 % depuis le plus haut |

Seuil d'entrée : score ≥ **3,0**.

## Règles d'entrée

1. Alerte équipe ou unlock → `skip`.
2. Score < 3 → `skip` (enregistré : sert à mesurer les occasions manquées).
3. Hausse 24 h ≥ 15 % (bougie du signal) → `wait`.
4. Sinon → `enter` dans les trois bras (dans la limite des plafonds).
5. Un `wait` est réévalué 1 à 2 jours plus tard et entre seulement si :
   - volume 24 h ≥ **2x** la moyenne des 14 jours précédant le signal ;
   - prix pas plus de **15 %** sous la clôture du jour du signal ;
   - aucun unlock > 0,5 % de l'offre dans les 7 jours ;
   - aucun transfert de l'équipe vers les exchanges ;
   - pas de nouvelle bougie de signal (+15 %).
   Échec au jour 1 → encore `wait` ; échec au jour 2 → `skip`.

Prix d'entrée virtuel : dernier prix 15 min + 0,1 % de glissement.

## Les trois bras (mêmes signaux, mêmes entrées)

| Bras | Stop | Objectif | Particularités | Gain/perte | Équilibre |
|---|---|---|---|---|---|
| A (référence) | −25 % | +40 % | levier 2x max | 1,6 | 39 % |
| B (stop serré) | −12 % | +40 % | stop à l'entrée dès +15 % | 3,3 | 23 % |
| C (adaptatif) | 1,5 x ATR(14) journalier, borné 10-25 % | 2,5 x distance du stop | stop suiveur (distance = distance initiale) après +20 % | 2,5 | 29 % |

Commun : sortie par le temps après 10 jours ; si stop et objectif sont dans la même
bougie 15 min, la bougie est rejouée minute par minute ; si l'ordre reste inconnu
(même minute ou pas de bougies 1 min), le stop compte d'abord. Taille = (1 % du capital du bras) / distance du stop,
plafonnée par le levier maximum. Le levier est choisi pour que la liquidation
estimée (marge de maintenance 1 % + 2 % de marge) reste sous le stop.

## Suivi (4 fois par jour : 08:00, 14:00, 20:00, 23:30)

Bougies de **15 minutes** fermées, chacune traitée **une seule fois** : `sim_through_at`
mémorise la fin de la dernière bougie simulée et la vérification suivante repart de là.
Toute bougie où il se passe quelque chose (stop, objectif, liquidation, passage à
l'équilibre, stop suiveur) et la bougie d'entrée sont **rejouées en bougies de 1 minute**
(Gate ~6 jours, OKX au-delà) : la sortie est datée à la minute et l'ordre stop / objectif
est celui du marché. La bougie d'entrée n'est rejouée qu'à partir de la minute suivant
l'entrée. Ordre dans une bougie : liquidation / stop → objectif → passage à l'équilibre →
stop suiveur (appliqués à partir de la bougie suivante, donc 1 min après affinage) →
durée maximale. Audit détaillé : `docs/audit_bougies.md`.
Frais : 0,055 % par exécution et par côté (preneur Bybit, aussi sur l'objectif).
Funding : taux **réellement réglés** (historique Gate) entre l'entrée et la sortie ;
estimation 0,01 % par 8 h seulement si l'historique est indisponible.

## Auto-amélioration (passage du matin, 05:30)

- Statistiques quotidiennes par bras et par type de signal.
- Aucun changement avant **30 trades fermés** dans un bras.
- Ensuite, un seul changement à la fois parmi : stop, objectif, durée max, seuil
  d'équilibre, activation du suiveur (±10 % ou ±20 %), validé en walk-forward
  70/30 avec IC bootstrap > 0 sur la différence appariée de R.
- Retour arrière si la nouvelle version fait moins bien que sa parente sur ses
  20 derniers trades (rejoués sur les mêmes données).
- Résultats à 10 jours de **tous** les signaux (entrés ou non) : occasions
  manquées, avance du signal, R contrefactuel par bras.
- **Anti-cercle vicieux (04/10/2026)** : moins de 30 trades fermés → l'échantillon d'adaptation
  est complété par des **trades contrefactuels** (signaux non entrés de plus de 10 jours, un par
  événement indépendant) ; après **7 jours sans entrée** dans un bras, **une** entrée d'exploration
  à demi-risque par passage sur le meilleur signal refusé seulement pour son score (≥ seuil − 1,
  sans alerte). Même logique pour la première étape des chaînes (routine 7). Voir GUARDRAILS section 8.

## Addendum 2ter — échelle d'ambition (paliers P1 à P4)

Portefeuille virtuel séparé « T » (les bras A/B/C sont inchangés). Détails : `docs/audit_2ter.md`.

| Palier | Objectif | Stop | Équilibre | Statut au départ |
|---|---|---|---|---|
| P1 « base » | 2,5 R | 1,5 x ATR(14), borné 8-12 % | 29 % | actif (capital papier) |
| P2 « précision » | 6 R | 0,6 x ATR(14), borné 3-6 % (substitut d'E5) | 14 % | ombre |
| P3 « grosse hausse » | 10 R | idem | 9 % | ombre |
| P4 « x50 » | 50 R (coureur) | idem, moitié de risque au plus | 2 % | ombre |

- **Une entrée, plusieurs sorties** : tranche A 50 % à 2,5 R ; B 30 % à 6 R ; C 20 % coureur
  (stop chandelier = plus haut − 3 x ATR, 30 jours au plus). Après A, le stop du solde passe à
  l'entrée. Une tranche dont le palier est en ombre est rattachée à A.
- **Critères** : instantané à chaque signal (`signal_features`, bougies fermées avant la décision),
  lift avec / sans par palier, événements indépendants (même pair < 10 jours = 1), correction de
  Benjamini-Hochberg (q = 10 %), rétention si ≥ 30 événements, lift ≥ +10 points, borne basse 80 %
  > 0 et lift positif sur la validation (30 % récents).
- **Déblocage** P2/P3/P4 : réussite hors échantillon (borne basse 80 %) ≥ équilibre + 3 points,
  ≥ 40 événements (P3/P4 : 30), espérance > 0 avec glissement x2, Monte Carlo acceptable.
  **Retour en ombre** si la borne haute 80 % sur 40 événements passe sous l'équilibre.
- Routine 5 (04:00, dimanche 10:00) : résultats d'ombre ; routine 6 (05:30, dimanche 11:00) :
  critères et décisions, en lecture seule les 7 premiers jours.

## Détection précoce (ajoutée le 03/10/2026)

Trois modes de détection tournent en parallèle et sont comparés chaque semaine (rapport,
section « Modes de détection comparés », et critères `mode_*` de la routine 6) :

| Mode | Comment | Poids ajoutés |
|---|---|---|
| `momentum` | plus fortes hausses 24 h + nouveaux perps (logique d'origine) | – |
| `pre_move` « avant la hausse » | volume 24 h ≥ 2x la moyenne 14 j, prix < 10 % sur 24 h et < 20 % sur 7 j, **et** open interest +15 % sur 3 j ou ATR(7)/ATR(30) ≤ 0,85 ; balayage de ~250 perps liquides (≥ 1 M USDT) | `pre_move_accumulation` +2,0 |
| `announcement` | annonces officielles < 48 h : Binance, OKX, KuCoin, Bitget, Bithumb (listing, perp, levée de surveillance) | `annonce_exchange_fraiche` (< 24 h) +1,0 |

Mise sous surveillance ou fin de cotation annoncée par un exchange : `alert_exchange_warning`
(−3,0, **skip**). Upbit, Gate et Bybit ne sont pas accessibles depuis le cloud (403).

Recherche toutes les 4 heures : 14:00 (complète) + 02:00, 06:00, 10:00, 18:00, 22:00 (légère,
routine 1b). Les plafonds (3 entrées/jour/bras, 8 positions) sont communs à tous les passages.
