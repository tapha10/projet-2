# Paper trading crypto — détection de hausses, 100 % démo

Système autonome qui détecte des cryptos avant une forte hausse, ouvre des
**positions virtuelles** (aucun ordre réel), les suit, mesure ses résultats et
ajuste prudemment ses paramètres. Tout l'état vit dans **Supabase** ; chaque
routine démarre sans mémoire. Règles absolues : [`GUARDRAILS.md`](GUARDRAILS.md).
Stratégie lisible : [`STRATEGY.md`](STRATEGY.md).

## Architecture

```
Routines Claude Code planifiées (sessions cloud, une par exécution)
  │  lisent routines/*.md + GUARDRAILS.md
  │  python3 -m engine.cli …   (données publiques en lecture seule → SQL)
  ▼
Connecteur Supabase (execute_sql) ──► projet « crypto-paper-trading » (vfwzokeoavnicmfyyszm)
                                       tables + RLS + triggers garde-fous
Connecteur Gmail ──► rapport hebdomadaire
```

| Routine | Horaire (Europe/Paris) | Fichier |
|---|---|---|
| 3. Adaptation | tous les jours 12:30 | `routines/03_adaptation.md` |
| 1. Analyse et entrées | tous les jours 14:00 | `routines/01_analyse_entrees.md` |
| 2. Vérification stop / objectif | 08:00, 14:30, 20:00, 23:30 | `routines/02_verification.md` |
| 4. Rapport hebdomadaire | dimanche 18:00 | `routines/04_rapport_hebdo.md` |

### Planification

Les routines sont des déclencheurs Claude Code (« Routines ») rattachés à la session
cloud qui a construit le système, car c'est elle qui détient les connecteurs Supabase
et Gmail : une routine créée en « nouvelle session à chaque exécution » depuis l'outil
n'emporte aucun connecteur dans cette organisation. Chaque déclenchement repart de
Supabase (le prompt interdit de s'appuyer sur la mémoire de la conversation).
Pour des sessions totalement isolées, recréer les 5 routines depuis l'interface
claude.ai (Routines) en cochant les connecteurs Supabase et Gmail, avec le même prompt.

| Déclencheur | Cron (Europe/Paris) |
|---|---|
| 3. Adaptation | `27 12 * * *` |
| 1. Analyse et entrées | `0 14 * * *` |
| 1b. Analyse intrajournalière (détection précoce) | `0 2,6,10,18,22 * * *` |
| 2. Vérification | `0 8,20 * * *` et `30 14,23 * * *` |
| 4. Rapport | `0 18 * * 0` |
| 5. Préparation des données (2ter) | `0 4 * * *` et `0 10 * * 0` |
| 6. Paliers et critères (2ter) | `30 5 * * *` et `0 11 * * 0` |

Addendum 2ter (paliers P1-P4, tranches, découverte de critères) : `docs/audit_2ter.md`,
`docs/tests_2ter.md`, migration `sql/004_tiers_2ter.sql`, modules `engine/tiers.py`,
`engine/features.py`, `engine/discovery.py`, `engine/cli2ter.py`, `engine/dryrun.py`.

Le serveur peut décaler l'heure de quelques minutes pour répartir la charge.

## Contenu

- `sql/001_init.sql` — tables, index, RLS (sans politique publique), triggers garde-fous,
  fonctions `paper_state()` / `paper_history()`.
- `sql/002_seed.sql` — configuration (1 000 USDT par bras) et bras A, B, C (`challenger`).
- `sql/003_engine_support.sql` — colonnes du moteur et `paper_record_daily()`.
- `engine/` — Python standard (aucune dépendance) :
  `market.py` (Gate → OKX → MEXC → KuCoin), `risk.py` (stop / objectif / taille / levier),
  `simulate.py` (bougie par bougie, affinage 1 min, stop d'abord si l'ordre reste inconnu), `stats.py` (métriques, bootstrap,
  walk-forward), `cli.py` (commandes des routines), `import_reference.py` (cas historiques).
- `tests/` — `python3 -m unittest discover -s tests` (hors réseau).

## Commandes du moteur

```bash
cd crypto_paper_trading
python3 -m engine.cli scan     --state state.json --out candidates.json
python3 -m engine.cli decide   --state state.json --candidates candidates.json --out entries.sql
python3 -m engine.cli check    --state state.json --out check.sql [--daily]
python3 -m engine.cli outcomes --history history.json --out outcomes.sql
python3 -m engine.cli adapt    --history history.json --out adapt.sql
python3 -m engine.cli report   --history history.json --calendar cal.md --out report.md --sql report.sql
python3 -m engine.import_reference base_gainers_2026-10-03.xlsx --out ref.sql   # nécessite openpyxl
```

`state.json` = résultat de `select paper_state();`, `history.json` = résultat de
`select paper_history();` (l'enveloppe renvoyée par le connecteur est acceptée).

## Garde-fous appliqués par la base (pas seulement par le code)

- `config.mode` ne peut valoir que `paper` ; les limites de risque ne peuvent pas être relâchées.
- Insertion d'une position refusée si : risque > 1 % du capital du bras, levier > 10x
  (A > 2x), plus de 8 positions ouvertes, plus de 3 entrées dans la journée (Paris),
  pair déjà ouvert dans le bras, drawdown du bras (réalisé + latent) > 15 %, stop/objectif incohérents.
- Paramètres d'entrée immuables, stop qui ne peut que monter, pas de réouverture.

## Données

Binance (451) et Bybit (403) sont bloqués depuis l'environnement cloud. Sources
utilisées : Gate.io (tickers, contrats, bougies, open interest), puis OKX, MEXC,
KuCoin en secours pour les bougies. Les actions / indices / métaux tokenisés de
Gate sont exclus. Les annonces, unlocks et transferts viennent de la recherche web.

## Limites connues

- Démo : glissement forfaitaire 0,1 %, frais 0,055 %/côté (Bybit), funding réel Gate (pas Bybit),
  prix Gate/OKX et non Bybit (Bybit bloqué depuis le cloud) ; voir `docs/audit_bougies.md`.
- Échantillon de départ minuscule et biaisé (4 cas, uniquement des hausses).
- La qualité des signaux « annonces » dépend de la recherche web de la routine.
- Les routines sont des agents : une routine peut échouer (source bloquée, quota) ;
  les triggers de la base garantissent toutefois que les plafonds ne sont jamais dépassés.
