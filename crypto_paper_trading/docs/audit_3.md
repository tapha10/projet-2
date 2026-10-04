# Audit avant greffe — prompt 3 (routine 7, chaînes de victoires)

Lecture du dépôt et de Supabase le 04/10/2026, avant toute modification.

## Réutilisé tel quel

| Élément demandé | Existant réutilisé |
|---|---|
| Signaux | `signals` (routines 1 et 1b), score et décision de la routine 1 |
| Résultats des positions | routine 2 (`engine/cli.py check`) : stop / objectif tranchés à la minute, frais Bybit, funding réel |
| Rejeux | `engine/simulate.py` (`replay`, `step`, `pnl`) pour toute la grille (stop, R) |
| Critères | `engine/features.py` (`compute_features`, `CRITERIA`, `cluster_events` à 10 jours), `entry_filters` (critères retenus par la routine 6) |
| Statistiques | `engine/discovery.py` (Benjamini-Hochberg, loi normale), `engine/stats.py` |
| Verrou, journal | `paper_lock_acquire/release`, `iteration_log` |
| Drawdown | `paper_equity`, `paper_unrealized`, `paper_peak_equity` (réalisé + latent) |

## Ajouté (migrations idempotentes `sql/009_chains.sql`)

- Colonnes `positions.chain_id`, `positions.chain_step` (les positions de chaîne sont des lignes de
  `positions`, bras « K ») ; contraintes de bras étendues à `K` (A, B, C, T inchangés).
- Tables `chain_params`, `chains`, `chain_steps`, `chain_gating`, `chain_decisions`, `chain_sim_runs`,
  `chain_stats` (RLS activée, aucune politique).
- Fonctions `enforce_chain_position`, `paper_global_drawdown`, `paper_chain_data`, triggers
  `chains_guardrails`, `positions_chain_close`.
- Fonctions existantes étendues en recopiant leur corps à l'identique et en ajoutant K :
  `enforce_paper_guardrails` (branche K avant les règles générales), `enforce_paper_strategy`,
  `paper_set_marks`, `paper_record_daily` (K dans `by_arm`, pas dans le total A+B+C).
- Code : `engine/chains.py`, `engine/chain_history.py`, `engine/cli7.py`, `engine/dryrun7.py`,
  `routines/07_chaines.md`, section « chaînes » du rapport (`cli report --chains-data`).

## Ce qui manque (substituts)

| Demandé | Constat | Substitut |
|---|---|---|
| `strategy_registry` | n'existe pas | `chain_params` (statuts explore/ombre/challenger/champion/restreint/pause/retiré/inconclusif) |
| `engine/replay.py` | n'existe pas | `engine/simulate.py` (`replay`) |
| table `candles` | existe mais vide | bougies lues à la demande (Gate, puis OKX) |
| prompt 2 / addendum 2bis | jamais reçus | rien n'en dépend ; à intégrer s'ils arrivent |
| score « critères validés par la routine 6 pondérés par le lift » | aucun critère validé à ce jour | score de la routine 1 + poids des critères validés quand il y en aura |
| historique de signaux | 13 signaux réels seulement | rejeu historique : signaux reconstruits sur prix et volumes (modes « avant la hausse » et « momentum » de la routine 1), sans annonces ni open interest ancien |
| capital de l'exemple (10 000) | le système utilise 1 000 USDT par portefeuille | portefeuille K de 1 000 USDT ; l'exemple à 10 000 est vérifié dans les tests |

## Non-régression

- `tests/baseline_before_3.json` figé avant la greffe ; `test_chains.TestNonRegression3` exige l'égalité
  exacte (bras A/B/C, découpes du portefeuille T, cycle sec de 14 jours des routines 1 à 6).
- Le banc sec existant n'était pas déterministe (`hash(pair)` change à chaque processus) : remplacé par
  `zlib.crc32` (banc de test seulement), référence régénérée avant toute modification des routines.
- Garde-fous A/B/C/T revérifiés en base (cas 14 de `docs/tests_3.md`).

## Points d'attention

- Aux étapes 4 et 5, les positions grossissent (levier nécessaire jusqu'à ~3,7x avec un stop de 10 %) :
  le plafond 3x réduit alors le risque, et la règle des 0,1 % du volume exclut les petits tokens.
- Le drawdown global à 15 % inclut l'argent de la maison : un échec aux étapes 4 ou 5 peut, à lui seul,
  approcher ce seuil ; la routine sera alors suspendue (c'est voulu par la section 10).
