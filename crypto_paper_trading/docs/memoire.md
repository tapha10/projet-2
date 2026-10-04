# Mémoire du projet (à lire au début de chaque passage)

Les sessions Claude n'ont pas de souvenir fiable d'un passage à l'autre : redémarrages du
worker, contexte résumé, passages manqués. La mémoire du projet est donc **dans Supabase** et
dans ce dépôt, jamais dans la conversation.

## 1. Lire la mémoire

```sql
select paper_memory();
```

Renvoie :

| Clé | Contenu |
|---|---|
| `mode` | toujours `paper` (ne jamais changer) |
| `lecture_seule` | fin de la lecture seule des routines 6 et 7 |
| `rattrapage` | ce qui a déjà tourné **aujourd'hui** (heure de Paris) : `routine5`, `routine6`, `routine7`, `adaptation`, `verification` ; `cloture_hier` (ligne `daily_results` d'hier) ; `rapport_manque` (rapport du dimanche absent) ; `dimanche` |
| `positions_ouvertes`, `trades_fermes`, `derniere_entree` | par bras (A, B, C, T, K) |
| `chaines` | chaînes papier ouvertes / terminées |
| `journal` | les 15 dernières lignes de `iteration_log` (quoi, quand, quelle routine) |

`select paper_catchup();` donne seulement la partie `rattrapage`.

## 2. Calendrier (depuis le 04/10/2026, Europe/Paris)

| Heure | Passage | Fichier |
|---|---|---|
| 05:30 | matin : rattrapage, R5, R6, R7 daily (+ weekly le dimanche), R3, rapport en retard | `routines/10_matin.md` |
| 08:00 et 20:00 | vérification R2 + analyse légère R1b (+ rattrapage du matin) | `routines/11_verif_scan.md` |
| 14:00 | R1 complète, R7 decide, R2 | `routines/12_apres_midi.md` |
| 23:30 | R2 avec clôture du jour | `routines/13_cloture.md` |
| dimanche 18:00 | rapport hebdomadaire R4 (Gmail) | `routines/04_rapport_hebdo.md` |

5 passages par jour (6 le dimanche) au lieu de 16 auparavant. Les anciens déclencheurs sont
désactivés, pas supprimés.

## 3. Reprendre après une interruption

- **Message « worker restarted »** au milieu d'un passage : ce n'est pas une fin. Relis
  `paper_memory()` et termine les étapes qui ne sont pas marquées faites. Ne réponds jamais
  « rien à faire » sans avoir vérifié.
- **Passage manqué** : le passage suivant le rattrape (règles dans chaque fichier de routine) :
  - matin manqué → rattrapé à 08:00 (ou 14:00 au plus tard) ;
  - clôture de 23:30 manquée → écrite le lendemain matin avec
    `engine.cli check --late-date AAAA-MM-JJ` (`paper_record_daily_late` : ligne marquée
    RATTRAPAGE, jamais par-dessus une clôture existante) ;
  - rapport du dimanche manqué → produit au passage du matin suivant, objet « (rattrapage) ».
- **Verrou occupé** (`paper_lock_acquire` = `false`) : une seule nouvelle tentative via
  `send_later` dans 10 à 15 minutes.
- **Étape en échec** : ligne `iteration_log` avec `status: error`, puis on continue les étapes
  suivantes.

## 4. Anti-cercle vicieux (pour que le système commence à apprendre)

Constat du 04/10/2026 : 0 trade → 0 apprentissage → mêmes seuils → 0 trade.
Corrections (GUARDRAILS section 8) :
1. adaptation nourrie de **trades contrefactuels** (signaux non entrés de plus de 10 jours,
   un par événement indépendant) tant qu'un bras a moins de 30 trades fermés ;
2. **exploration** après 7 jours sans entrée : une entrée à demi-risque par passage, signal refusé
   seulement pour son score (≥ seuil − 1), sans alerte ; idem pour l'étape 1 des chaînes après
   7 jours sans étape (comptés depuis la fin de la lecture seule de la routine 7).

## 5. Problèmes connus et précautions

- Le connecteur Supabase coupe une requête après ~60 s : découper le SQL généré
  (blocs `do $$ … $$;`), utiliser `set lock_timeout = '5s'` pour les changements de schéma, et
  vérifier ensuite ce qui a été appliqué.
- Binance et Bybit sont bloqués depuis le cloud : sources Gate → OKX → MEXC → KuCoin.
- Le rejeu historique ne connaît ni les annonces ni l'open interest ancien (`docs/audit_3.md`).
- Nuit du 03 au 04/10/2026 : des passages R1b, R5 et R6 ont été perdus parce que la session a
  répondu « rien à faire » après un redémarrage ; c'est la raison de cette mémoire et du rattrapage.
- Interdits permanents des passages : modifier `GUARDRAILS.md`, commit, push, changer
  `config.mode`, toute fonction de trading réel.
