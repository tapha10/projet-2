# Routine 5 — Préparation des données des paliers (04:00 tous les jours ; dimanche 10:00 complète, Paris)

> Substitut minimal créé par l'addendum 2ter : la routine 5 de l'addendum 2bis n'existe
> pas dans ce système (voir `docs/audit_2ter.md`). Elle ne fait que préparer les
> données dont la routine 6 a besoin. Elle n'ouvre ni ne ferme aucune position.

## Contexte (tu ne te souviens de rien : tout est dans Supabase et dans ce dépôt)

- Paper trading crypto **100 % démo**. Lis d'abord `crypto_paper_trading/GUARDRAILS.md`.
- Base : projet Supabase `crypto-paper-trading`, **project_id `vfwzokeoavnicmfyyszm`**, outil `execute_sql`
  du connecteur Supabase (ToolSearch `select:mcp__Supabase__execute_sql` si besoin).
- Code : branche `claude/crypto-paper-trading` du dépôt `tapha10/projet-2` :
  ```bash
  cd /home/user/projet-2 && git fetch origin claude/crypto-paper-trading && git checkout -B claude/crypto-paper-trading origin/claude/crypto-paper-trading
  cd crypto_paper_trading && W=$(mktemp -d)
  ```
- **Interdit** : modifier `GUARDRAILS.md`, commit, push, changer `config.mode`.
- Pour passer un résultat SQL au moteur : écris le texte JSON du résultat dans le fichier indiqué (Write).
- Pour exécuter un fichier SQL généré : passe son contenu tel quel à `execute_sql` (transaction `begin … commit`).

## Étapes

1. Verrou : `select paper_lock_acquire('tiers', 'routine5', 45);`. Si le résultat est `false`, une
   autre routine écrit les mêmes tables : programme une nouvelle tentative dans 15 minutes avec
   `send_later` (message : la même consigne de routine 5) et arrête-toi.
2. `select paper_tier_data();` → écris le résultat dans `$W/data.json`.
3. Le dimanche (passage de 10:00) ajoute `--weekly` (rattrapage des instantanés manquants,
   calculés avec les seules bougies fermées avant la détection) :
   `python3 -m engine.cli2ter r5 --data $W/data.json --out $W/r5.sql [--weekly]`
   Le moteur rejoue, pour chaque signal (entré ou non) des 35 derniers jours, les paliers
   P1-P4 en ombre (taux de réussite, R, R avec glissement x2, MFE, MAE, durée) et les découpes
   de sortie 50/30/20, 30/30/40, 70/20/10, 100/0/0.
4. Exécute `$W/r5.sql`. La dernière instruction écrit dans `iteration_log` la ligne
   `routine5` avec `status: ok` que la routine 6 attend. En cas d'erreur SQL, écris à la place :
   `insert into iteration_log(routine, change, rationale) values ('routine5', '{"action":"data_prep","status":"error"}', '<erreur>');`
5. `select paper_lock_release('tiers', 'routine5');` (toujours, même en cas d'erreur).
6. Résumé en 3 lignes (signaux traités, lignes d'ombre, erreurs). Réponds en français.
