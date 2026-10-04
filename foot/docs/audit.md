# Audit (Phase 0) — 04/10/2026

_Simulation papier, pas un conseil de pari ; parier de l'argent réel comporte un risque de perte._

## Infrastructure

| Élément | État | Détail |
|---|---|---|
| Code | branche `claude/foot-paper-analysis` du dépôt `tapha10/projet-2` (branche orpheline : aucun fichier des autres projets) | la création d'un nouveau dépôt GitHub est refusée à l'intégration (403) ; choix validé : branche à part |
| Supabase | **en attente** | offre gratuite limitée à 2 projets actifs (tiktok-auto, crypto-paper-trading). Le projet `foot-paper-analysis` sera créé dès que tiktok-auto sera mis en pause. **crypto-paper-trading n'a jamais été modifié** (une seule lecture de la liste de ses tables, avant la consigne). |
| Base locale | `data/foot.sqlite`, même schéma que la migration `migrations/001_foot_init.sql` (traduction automatique, vérifiée par un test) | sert aux tests, au rejeu et de copie de travail des routines |
| Clés | aucune dans le dépôt ; emplacements prévus en variables d'environnement : `ODDS_API_KEY`, `API_FOOTBALL_KEY`, `FOOTBALL_DATA_ORG_KEY` | |

## Sources (détail dans `foot_source_audit`)

| Source | Accès | Utilisée | Pourquoi |
|---|---|---|---|
| football-data.co.uk, fichiers de saison | 200 | **oui** | 22 championnats, résultats, tirs, arbitre, cotes plus/moins 2,5 d'avant-match (Avg, B365, Max) et de clôture (AvgC…), xG depuis 2026-27. robots.txt : tout autorisé (sauf robots d'entraînement d'IA : ce système n'en est pas un). Cache local et 1,5 s entre requêtes. |
| football-data.co.uk, `fixtures.csv` | 200 | **oui** | matchs à venir avec cotes plus/moins 2,5. Mis à jour avant les week-ends et les journées de semaine : certains jours ne sont pas couverts. |
| football-data.co.uk, ligues « new » (MLS, Brésil…) | 200 | non | cotes 1X2 seulement, **pas de cote plus/moins 2,5** -> non éligibles. |
| OpenLigaDB | 200 | prévue | scores Bundesliga en quasi temps réel ; la table de correspondance des noms d'équipes reste à faire. |
| openfootball | 200 | non | calendriers seulement ; scores irréguliers. |
| Open-Meteo | 200 | non | météo disponible, mais les coordonnées des stades manquent. |
| Understat | 200 (robots) | **non** | robots.txt : `Disallow: /` -> interdit. |
| FBref | 403 | **non** | accès refusé -> non contourné. |
| TheSportsDB | 200 | **non** | `Content-Signal: ai-input=no` -> exclu par prudence. |
| ESPN | 403 | **non** | API non documentée, robots refusé. |
| Sofascore / Flashscore / Transfermarkt | — | **non** | conditions d'utilisation interdisant l'extraction automatisée. |
| The Odds API / API-Football / football-data.org | 401/403 | si clé fournie | offres gratuites (500 requêtes/mois, 100 requêtes/jour, 10 requêtes/min). Elles apporteraient les compositions, les absences, des scores en temps réel et des cotes pour plus de ligues. |

### Variables de la section 5 : disponibles ou manquantes

- **Disponibles** : cotes d'avant-match (instantané football-data) et de clôture, ligne 2,5 ; buts pour/contre (domicile/extérieur, moyennes glissantes), tirs, tirs cadrés, taux de plus de 2,5, repos entre matchs **de championnat**, enjeu approché (écart au leader et à la zone de relégation), arbitre (nom), xG (saison 2026-27 seulement).
- **Manquantes** : compositions, absences et leur poids chiffré ; matchs de coupe (le repos sous-estime la fatigue) ; météo ; état du terrain ; cotes « deux équipes marquent » ; véritable cote d'ouverture et mouvement de ligne (football-data ne donne qu'un instantané d'avant-match et la clôture). Ces valeurs restent **vides** ; M2 utilise 0 comme impact d'absence inconnu.

## Interprétations écrites

1. **« Plus de 5 matchs joués »** : lecture principale `strict` = chaque équipe a joué au moins 6 matchs de championnat dans la saison en cours (`regle_min_matchs = "strict"`). La variante `au_moins` (≥ 5) est testée en parallèle (backtest : aucune différence notable). La lecture « au moins 5 matchs éligibles dans la journée » n'est pas un filtre de match : elle porte sur la taille du combiné, déjà gérée (combiné plus court si moins de 5).
2. **Début de saison** : les variables d'équipe sont des moyennes pondérées exponentiellement sur les derniers matchs, **toutes saisons confondues** (demi-vie de 6 matchs). Les matchs de la saison précédente perdent naturellement leur poids au fil des journées : après 6 matchs, ils pèsent environ la moitié ; après 12, environ un quart. M1 utilise 2 ans de matchs avec une demi-vie de 180 jours.
3. **Verrouillage** : R1 démarre à 10:00 (heure de Paris) et verrouille dès la fin de son calcul (vers 10:10–10:30, donc avant 11:00). L'heure réelle est écrite dans `locked_at`. Un match qui commence avant le verrouillage est exclu : une contrainte de base l'interdit.
4. **Cote de référence** : la cote moyenne de marché `Avg` de football-data, avec repli sur B365. Heure de capture = heure de téléchargement ; l'heure de collecte réelle de la source n'est pas publiée, elle est au plus tard l'heure de téléchargement.
5. **Côté choisi** : celui de plus forte probabilité selon le modèle actif. Si sa cote est sous 1,70, le match est écarté, jamais forcé.
6. **Temps réglementaire** : les championnats retenus n'ont ni prolongation ni tirs au but (les play-offs sont exclus). Les scores football-data sont ceux du temps réglementaire.
