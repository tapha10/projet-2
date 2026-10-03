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

## Contenu

- `sql/001_init.sql` — tables, index, RLS (sans politique publique), triggers garde-fous,
  fonctions `paper_state()` / `paper_history()`.
- `sql/002_seed.sql` — configuration (1 000 USDT par bras) et bras A, B, C (`challenger`).
- `sql/003_engine_support.sql` — colonnes du moteur et `paper_record_daily()`.
- `engine/` — Python standard (aucune dépendance) :
  `market.py` (Gate → OKX → MEXC → KuCoin), `risk.py` (stop / objectif / taille / levier),
  `simulate.py` (bougie par bougie, stop d'abord), `stats.py` (métriques, bootstrap,
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
  pair déjà ouvert dans le bras, drawdown du bras > 15 %, stop/objectif incohérents.
- Paramètres d'entrée immuables, stop qui ne peut que monter, pas de réouverture.

## Données

Binance (451) et Bybit (403) sont bloqués depuis l'environnement cloud. Sources
utilisées : Gate.io (tickers, contrats, bougies, open interest), puis OKX, MEXC,
KuCoin en secours pour les bougies. Les actions / indices / métaux tokenisés de
Gate sont exclus. Les annonces, unlocks et transferts viennent de la recherche web.

## Limites connues

- Démo : glissement forfaitaire 0,1 %, frais 0,05 %/côté, funding estimé 0,01 %/8 h.
- Échantillon de départ minuscule et biaisé (4 cas, uniquement des hausses).
- La qualité des signaux « annonces » dépend de la recherche web de la routine.
- Les routines sont des agents : une routine peut échouer (source bloquée, quota) ;
  les triggers de la base garantissent toutefois que les plafonds ne sont jamais dépassés.
