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
bougie, le stop compte d'abord. Taille = (1 % du capital du bras) / distance du stop,
plafonnée par le levier maximum. Le levier est choisi pour que la liquidation
estimée (marge de maintenance 1 % + 2 % de marge) reste sous le stop.

## Suivi (4 fois par jour)

Bougies de **15 minutes** depuis la dernière vérification, plus hauts et plus bas.
Ordre par bougie : liquidation / stop → objectif → passage à l'équilibre → stop
suiveur (appliqués à partir de la bougie suivante) → durée maximale.
Frais : 0,05 % par exécution et par côté. Funding estimé : 0,01 % par 8 h.

## Auto-amélioration (12:30)

- Statistiques quotidiennes par bras et par type de signal.
- Aucun changement avant **30 trades fermés** dans un bras.
- Ensuite, un seul changement à la fois parmi : stop, objectif, durée max, seuil
  d'équilibre, activation du suiveur (±10 % ou ±20 %), validé en walk-forward
  70/30 avec IC bootstrap > 0 sur la différence appariée de R.
- Retour arrière si la nouvelle version fait moins bien que sa parente sur ses
  20 derniers trades (rejoués sur les mêmes données).
- Résultats à 10 jours de **tous** les signaux (entrés ou non) : occasions
  manquées, avance du signal, R contrefactuel par bras.
