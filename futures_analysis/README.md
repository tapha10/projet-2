# Analyse fondamentale matinale — Futures (MES / MYM / MNQ / MCL)

Routine automatisée qui produit, chaque matin avant l'ouverture US, un biais
directionnel (HAUSSE / BAISSE / NEUTRE / PAS ASSEZ D'INFO) pour chacun de vos
4 instruments de trading en 5 minutes :

- **MES** — Micro E-mini S&P 500
- **MYM** — Micro E-mini Dow
- **MNQ** — Micro E-mini Nasdaq
- **MCL** — Micro WTI Crude Oil

## Comment ça marche

1. **Données quantitatives** (API Yahoo Finance, gratuit, sans clé) : futures overnight
   des indices (proxies grand format `ES=F`/`YM=F`/`NQ=F`/`CL=F` — même sens
   directionnel que les micro-contrats), VIX, Dollar Index (DXY), rendement du
   10 ans US (US10Y).
2. **Calendrier économique du jour** : flux JSON public de ForexFactory
   (CPI, NFP, FOMC, PMI/ISM, PCE...).
3. **Recherche web + synthèse** : l'API Claude (avec l'outil de recherche web
   intégré) cherche l'actualité macro de dernière minute, le dernier rapport
   EIA/API pour le pétrole, et l'actualité géopolitique pertinente, puis
   produit le rapport final dans le format exact demandé, avec sources.
4. Le rapport est affiché dans le terminal et sauvegardé dans
   `reports/rapport_AAAA-MM-JJ.md`.

## Installation

```bash
cd futures_analysis
python3 -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# éditez .env et renseignez ANTHROPIC_API_KEY
```

## Utilisation manuelle

```bash
source venv/bin/activate
export $(grep -v '^#' .env | xargs)   # charge les variables du .env dans le shell
python3 morning_report.py
```

Le rapport apparaît dans le terminal et un fichier
`reports/rapport_2026-08-08.md` est créé.

## Format du rapport

Pour chaque instrument :

```
MES : HAUSSE
→ Futures S&P en hausse de +0.4% overnight, 10 ans stable, VIX en léger repli — signal net.
→ Sources : https://..., https://...
```

Suivi d'une section signalant tout événement macro majeur (CPI/NFP/FOMC/PMI/PCE)
tombant entre 8h00 et 10h30 ET, avec l'heure exacte.

## Automatiser l'exécution avant l'ouverture US (cron)

L'ouverture des marchés US est à 9h30 ET. On veut lancer le script ~45-60 min
avant, par exemple **8h30 ET**, du lundi au vendredi.

⚠️ Piège classique : l'heure ET change deux fois par an (EST/EDT). Deux
options robustes :

### Option A — `CRON_TZ` (recommandé, Linux avec cronie/Vixie cron — la
plupart des distributions modernes)

```bash
crontab -e
```

Ajoutez en tête du fichier crontab, puis la tâche (adaptez le chemin) :

```cron
CRON_TZ=America/New_York
30 8 * * 1-5 cd /chemin/vers/futures_analysis && /chemin/vers/venv/bin/python3 morning_report.py >> logs/cron.log 2>&1
```

`CRON_TZ` fait que cron interprète `30 8 * * 1-5` en heure de New York, DST
géré automatiquement. Créez le dossier `logs/` au préalable (`mkdir logs`).

### Option B — systemd timer (si `CRON_TZ` n'est pas supporté)

`~/.config/systemd/user/futures-report.service` :

```ini
[Unit]
Description=Rapport fondamental matinal futures

[Service]
Type=oneshot
WorkingDirectory=/chemin/vers/futures_analysis
EnvironmentFile=/chemin/vers/futures_analysis/.env
ExecStart=/chemin/vers/venv/bin/python3 morning_report.py
```

`~/.config/systemd/user/futures-report.timer` :

```ini
[Unit]
Description=Déclenche le rapport futures à 8h30 ET, lun-ven

[Timer]
OnCalendar=Mon..Fri 08:30:00 America/New_York
Persistent=true

[Install]
WantedBy=timers.target
```

Puis :

```bash
systemctl --user daemon-reload
systemctl --user enable --now futures-report.timer
```

### Option C — sans dépendance TZ du planificateur

Convertissez manuellement 8h30 ET en UTC selon la saison (13h30 UTC en EDT,
été ; 14h30 UTC en heure d'hiver EST) et utilisez un cron UTC classique en
acceptant de le corriger deux fois par an — c'est la solution la moins
fiable, à éviter si les options A/B sont disponibles.

## Notes et limites

- Les proxies `ES=F`/`YM=F`/`NQ=F`/`CL=F` reflètent le même sens directionnel
  que les micro-contrats MES/MYM/MNQ/MCL, mais avec une taille de contrat
  différente (aucun impact sur le biais directionnel, qui est ce que cette
  routine fournit).
- Si l'API Yahoo Finance ou le flux ForexFactory sont temporairement
  indisponibles, le script continue en signalant la donnée manquante au
  modèle, qui appliquera la règle "PAS ASSEZ D'INFO" plutôt que d'inventer un
  chiffre.
- Le coût d'un appel dépend du modèle et du nombre de recherches web
  effectuées (typiquement quelques centimes par exécution avec
  `claude-opus-5`). Réduisez `CLAUDE_EFFORT` à `low` ou passez à
  `claude-sonnet-5` dans `.env` si le coût quotidien devient significatif.
- Ceci est un outil d'aide à la décision, pas un signal de trading
  automatique — vérifiez toujours l'information avant d'ouvrir une position.
