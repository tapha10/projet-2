# Routine 6 — Paliers et critères (05:30 tous les jours ; dimanche 11:00 analyse complète, Paris)

> **Depuis le 04/10/2026**, cette routine n'a plus de déclencheur propre : elle est appelée par les
> passages regroupés `10_matin.md` (05:30), `11_verif_scan.md` (08:00, 20:00), `12_apres_midi.md` (14:00)
> et `13_cloture.md` (23:30). Les horaires du titre sont historiques. Commence par `select paper_memory();`.

> Addendum 2ter. Elle n'ouvre **jamais** de position : elle analyse, débloque ou bloque des
> paliers, puis la routine 1 applique au cycle suivant. Les 7 premiers jours après activation
> (`config.r6_readonly_until`), elle tourne en **lecture seule** : constats sans décision.

## Contexte (tu ne te souviens de rien : tout est dans Supabase et dans ce dépôt)

- Paper trading crypto **100 % démo**. Lis d'abord `crypto_paper_trading/GUARDRAILS.md`.
- Base : projet Supabase `crypto-paper-trading`, **project_id `vfwzokeoavnicmfyyszm`**, outil `execute_sql`.
- Code : branche `claude/crypto-paper-trading` du dépôt `tapha10/projet-2` :
  ```bash
  cd /home/user/projet-2 && git fetch origin claude/crypto-paper-trading && git checkout -B claude/crypto-paper-trading origin/claude/crypto-paper-trading
  cd crypto_paper_trading && W=$(mktemp -d)
  ```
- **Interdit** : modifier `GUARDRAILS.md`, commit, push, changer `config.mode`, ouvrir une position.

## Étapes

1. Mode : `weekly` si c'est le passage du dimanche 11:00, sinon `daily`. Tentative : `1`, ou `2`
   si le message qui t'a réveillé dit « tentative 2 ».
2. Verrou : `select paper_lock_acquire('tiers', 'routine6', 45);`. Si `false` : programme une
   nouvelle tentative dans 15 minutes (`send_later`) et arrête-toi.
3. `select paper_tier_data();` → `$W/data.json`.
4. `python3 -m engine.cli2ter r6 --data $W/data.json --out $W/r6.sql --mode <mode> --attempt <n>`
   - **Condition de départ** : la dernière exécution de la routine 5 doit s'être terminée avec
     succès (ligne `routine5` avec `status: ok` dans `iteration_log`, de moins de 8 h en quotidien,
     de moins de 3 h le dimanche).
   - Si le moteur affiche `ATTENTE` (tentative 1) : libère le verrou, programme avec `send_later`
     un réveil dans **30 minutes** avec le message « [ROUTINE 6 — tentative 2] » suivi de la même
     consigne et du mode, puis arrête-toi sans rien décider.
   - Si le moteur affiche `NON EXÉCUTÉE` (tentative 2) : exécute `$W/r6.sql` (une seule ligne
     `iteration_log` « non exécutée » avec la raison), libère le verrou, arrête-toi.
5. Sinon exécute `$W/r6.sql` :
   - quotidien : résultats par palier et lift des critères déjà suivis (calcul léger) ;
   - dimanche : analyse de tous les critères et paires de critères, correction de
     Benjamini-Hochberg, `entry_filters`, `promotion_decisions` (déblocage, montée de risque
     0,25 → 0,5 → 1 %, retour en ombre), découpe de sortie, et `config.tier_state` (seulement
     hors lecture seule).
6. `select paper_lock_release('tiers', 'routine6');` (toujours).
7. Résumé en français (5 lignes max) : statut de chaque palier, critères retenus, décisions
   (ou constats en lecture seule), ce qui manque pour trancher.
