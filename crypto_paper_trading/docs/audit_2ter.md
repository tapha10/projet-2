# Audit avant greffe — addendum 2ter (03/10/2026)

## 1. Ce qui existe (dépôt `claude/crypto-paper-trading` + Supabase `vfwzokeoavnicmfyyszm`)

| Élément | État |
|---|---|
| `GUARDRAILS.md`, `STRATEGY.md`, `README.md` | présents (prompt 1) |
| Tables `strategy_versions`, `signals`, `positions`, `price_checks`, `daily_results`, `weekly_reports`, `iteration_log`, `config` | présentes, RLS actif, triggers garde-fous |
| Bras A / B / C | 3 versions `challenger` ; 0 position ; 13 signaux (1 wait, 12 skip) au 03/10 |
| Routines | R1 analyse (14:00), R2 vérification (08:00, 14:30, 20:00, 23:30), R3 adaptation (12:30), R4 rapport (dimanche 18:00) |
| Moteur de rejeu | `engine/simulate.py` (bougie par bougie, stop d'abord) + `engine/risk.py` |
| Cycle de promotion | `challenger` → `champion` / `retired` + retour arrière (R3), walk-forward 70/30, bootstrap |

## 2. Ce qui MANQUE (cité par 2ter, absent ici — signalé, pas inventé en doublon)

| Élément cité | Constat | Décision (validée avec le propriétaire le 03/10) |
|---|---|---|
| Prompt 2 et addendum 2bis | jamais fournis à ce système | greffe de 2ter sur l'existant |
| Routine 5 (04:00, dimanche 10:00) | n'existe pas | **substitut minimal** : préparation des données des paliers (`routines/05_preparation_donnees.md`), pour que R6 ait un prédécesseur |
| `strategy_registry` | n'existe pas | les paliers sont des lignes de `strategy_versions` (`arm = 'T'`, colonne `tier`) |
| `engine/replay.py` | n'existe pas | réutilisation de `engine/simulate.py` (rejeu) ; les tranches sont dans `engine/tiers.py` |
| Table `candles` | n'existe pas | créée (vide pour l'instant ; les routines relisent les bougies aux sources publiques) |
| Entrées E1 à E5, sorties S1 à S6 | n'existent pas | P2-P4 utilisent un **substitut d'E5** : stop structurel serré 0,6 x ATR(14) borné 3-6 % ; aucune S1-S6 |
| Cycle explore → ombre → challenger → champion | seuls challenger / champion / retired existaient | statuts `explore` et `shadow` ajoutés à la contrainte (élargissement, sans retrait) |
| `promotion_decisions`, `entry_filters`, `signal_features` | n'existent pas | créées |

## 3. Ce qui est réutilisé tel quel

- Moteur de rejeu `simulate.replay` (paliers autonomes en ombre), `risk.plan_position`.
- Règle « stop d'abord dans la même bougie », frais 0,05 %/côté, funding estimé, glissement 0,1 %.
- Walk-forward 70/30 et bootstrap de `engine/stats.py`.
- Triggers garde-fous de la base (étendus pour le portefeuille T, inchangés pour A/B/C).
- `iteration_log` pour la traçabilité de chaque exécution.

## 4. Ce qui est ajouté

- **Migration `sql/004_tiers_2ter.sql`** (idempotente, ajouts seulement) : colonnes `tier`, `tranches`,
  `mfe_r`, `time_to_peak_h`, `peak_at`, `lowest_price` ; tables `candles`, `signal_features`,
  `shadow_trades`, `entry_filters`, `promotion_decisions` (RLS actif) ; verrous
  `paper_lock_acquire/release` (dans `config`, avec expiration) ; `paper_tier_data()` ;
  4 versions de paliers P1 (`champion`, capital papier) et P2-P4 (`shadow`).
- **Portefeuille virtuel séparé « T »** (1 000 USDT) pour les paliers : les bras A/B/C et leurs
  résultats restent strictement identiques (référence `tests/baseline_before_2ter.json`).
- **Garde-fous 2ter** (portefeuille T uniquement, plus stricts que GUARDRAILS.md) : levier <= 3x,
  position <= 25 % du capital, notionnel total <= 150 %, liquidation >= 3x la distance du stop.
  Décision du propriétaire : 3x pour les paliers seulement (les bras B et C gardent 5-6x).
- `engine/tiers.py` (paliers, tranches, déblocage), `engine/features.py` (critères sans regard
  vers le futur, événements indépendants), `engine/discovery.py` (lift, Benjamini-Hochberg,
  rétention, décisions de palier, découpes), `engine/cli2ter.py` (R5, R6, accroches R1/R2/R4),
  `engine/dryrun.py` (cycle complet en mode sec).
- Routines modifiées (pas dupliquées) : R1 `decide --tiers`, R2 `check --tiers`, R3 lit l'état
  des paliers, R4 `--tiers-data` ; nouvelles R5 et R6.

## 5. Interprétations à connaître

- **Tranches et capital** : chaque signal entré ouvre une seule position T découpée A 50 % /
  B 30 % / C 20 %. Une tranche dont le palier est encore en ombre ne reçoit pas de capital : sa
  part est rattachée à la tranche A (sortie à 2,5 R) et elle est mesurée en ombre (rejeu des
  découpes). Un palier débloqué au risque r reçoit r / 1 % de sa part. Le risque total d'une
  position T reste <= 1 % du capital. Tant que seul P1 est débloqué, la position T sort donc
  entièrement à 2,5 R.
- **R de la tranche B / C** : exprimés avec le stop de la position (stop P1 8-12 %), donc 6 R ≈ +50 à +70 %.
- **Rattrapage des instantanés** : les 13 signaux antérieurs ont reçu un instantané calculé après
  coup avec les seules bougies fermées avant leur détection (`backfilled: true`) ; les critères
  d'information (catalyseur, sources) y sont absents.
- **Lecture seule** : `config.r6_readonly_until` = activation + 7 jours ; avant, R6 écrit des
  constats et des `promotion_decisions` marquées `read_only`, sans changer `tier_state`.
