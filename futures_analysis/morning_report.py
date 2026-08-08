#!/usr/bin/env python3
"""
Routine d'analyse fondamentale matinale pour le trading de futures (5 min, session US).

Instruments couverts : MES, MYM, MNQ, MCL (proxies via les futures grand format
ES=F, YM=F, NQ=F, CL=F sur Yahoo Finance -- même sens directionnel, tick size
différent).

Étapes :
  1. Données quantitatives (API Yahoo Finance) : futures overnight, VIX, DXY, US10Y.
  2. Calendrier économique du jour (flux JSON ForexFactory).
  3. Synthèse qualitative + recherche web (API Claude, outil web_search) :
     actualité macro de dernière minute, rapport EIA/API, géopolitique pétrole.
  4. Rapport formaté par instrument, sauvegardé dans reports/.

Usage :
    python3 morning_report.py

Variables d'environnement :
    ANTHROPIC_API_KEY   (obligatoire, sauf si un profil `ant auth login` est actif)
    CLAUDE_MODEL         (optionnel, défaut: claude-opus-5)
    CLAUDE_EFFORT        (optionnel, défaut: medium)
"""

from __future__ import annotations

import os
import sys
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    import anthropic
except ImportError:
    print("Erreur : le paquet 'anthropic' n'est pas installé. Lancez : pip install -r requirements.txt")
    sys.exit(1)


NY_TZ = ZoneInfo("America/New_York")
SCRIPT_DIR = Path(__file__).resolve().parent
REPORTS_DIR = SCRIPT_DIR / "reports"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")

# Tickers Yahoo Finance : proxies "grand format" des futures micro demandés.
# Le sens directionnel (hausse/baisse) est identique entre le micro et le
# grand format -- seule la taille du tick / la marge diffère.
TICKERS = {
    "MES (Micro E-mini S&P 500)": "ES=F",
    "MYM (Micro E-mini Dow)": "YM=F",
    "MNQ (Micro E-mini Nasdaq)": "NQ=F",
    "MCL (Micro WTI Crude Oil)": "CL=F",
}
MACRO_TICKERS = {
    "VIX": "^VIX",
    "US10Y (rendement 10 ans, %)": "^TNX",  # Yahoo renvoie déjà le rendement en %
    "DXY (Dollar Index)": "DX-Y.NYB",
}

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def fetch_quote_change(ticker: str) -> dict | None:
    """Retourne {last, prev_close, pct_change} pour un ticker, ou None si échec."""
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]

        last = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        if last is None or prev_close is None:
            return None
        last, prev_close = float(last), float(prev_close)

        pct_change = ((last - prev_close) / prev_close) * 100 if prev_close else None
        return {"last": round(last, 3), "prev_close": round(prev_close, 3), "pct_change": round(pct_change, 3) if pct_change is not None else None}
    except Exception as exc:
        print(f"  [!] Échec récupération {ticker}: {exc}", file=sys.stderr)
        return None


def fetch_market_data() -> dict:
    """Récupère toutes les données de marché quantitatives (API Yahoo Finance)."""
    print("→ Récupération des données de marché (Yahoo Finance)...")
    data = {"futures": {}, "macro": {}}

    for name, ticker in TICKERS.items():
        data["futures"][name] = fetch_quote_change(ticker)

    for name, ticker in MACRO_TICKERS.items():
        data["macro"][name] = fetch_quote_change(ticker)

    return data


def fetch_economic_calendar(today_ny: dt.date) -> list[dict]:
    """Récupère le calendrier économique du jour via le flux JSON ForexFactory.

    Retourne une liste vide si le flux est inaccessible -- le modèle sera alors
    chargé de chercher le calendrier lui-même via web_search.
    """
    print("→ Récupération du calendrier économique (ForexFactory)...")
    try:
        resp = requests.get(FF_CALENDAR_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        events = resp.json()
    except Exception as exc:
        print(f"  [!] Échec récupération calendrier FF: {exc}", file=sys.stderr)
        return []

    todays_events = []
    for ev in events:
        try:
            # Le champ "date" est au format ISO8601 avec offset, ex: "2026-08-08T08:30:00-04:00"
            ev_dt = dt.datetime.fromisoformat(ev["date"])
            ev_dt_ny = ev_dt.astimezone(NY_TZ)
        except Exception:
            continue
        if ev_dt_ny.date() != today_ny:
            continue
        if ev.get("country") != "USD":
            continue
        todays_events.append(
            {
                "title": ev.get("title"),
                "time_et": ev_dt_ny.strftime("%H:%M ET"),
                "impact": ev.get("impact"),
                "forecast": ev.get("forecast"),
                "previous": ev.get("previous"),
            }
        )

    todays_events.sort(key=lambda e: e["time_et"])
    return todays_events


def format_market_data_for_prompt(data: dict) -> str:
    lines = ["### Données de marché quantitatives (source : Yahoo Finance, delta vs clôture veille)\n"]
    lines.append("**Futures indices / pétrole :**")
    for name, q in data["futures"].items():
        if q is None:
            lines.append(f"- {name} : DONNÉE INDISPONIBLE")
        else:
            sign = "+" if (q["pct_change"] or 0) >= 0 else ""
            lines.append(f"- {name} : dernier={q['last']}, clôture veille={q['prev_close']}, variation={sign}{q['pct_change']}%")

    lines.append("\n**Indicateurs macro :**")
    for name, q in data["macro"].items():
        if q is None:
            lines.append(f"- {name} : DONNÉE INDISPONIBLE")
        else:
            sign = "+" if (q["pct_change"] or 0) >= 0 else ""
            lines.append(f"- {name} : niveau={q['last']}, veille={q['prev_close']}, variation={sign}{q['pct_change']}%")

    return "\n".join(lines)


def format_calendar_for_prompt(events: list[dict]) -> str:
    if not events:
        return (
            "### Calendrier économique du jour\n"
            "Le flux ForexFactory n'a pas pu être récupéré automatiquement. "
            "Cherche toi-même le calendrier économique US du jour (ForexFactory ou Investing.com) "
            "et vérifie en particulier : CPI, NFP, FOMC, PMI/ISM, PCE."
        )
    lines = ["### Calendrier économique du jour (USD, source : ForexFactory)\n"]
    for ev in events:
        impact = ev.get("impact") or "?"
        lines.append(f"- {ev['time_et']} [{impact}] {ev['title']} (prévision: {ev.get('forecast') or 'n/a'}, précédent: {ev.get('previous') or 'n/a'})")
    return "\n".join(lines)


SYSTEM_PROMPT = """Tu es un analyste macro spécialisé dans le trading intraday de futures \
(MES, MYM, MNQ, MCL) sur timeframe 5 minutes, pour un trader qui ouvre ses positions \
le matin en session US (autour de 9h30 ET).

Ta mission : produire un rapport de biais directionnel fondamental pour CHAQUE \
instrument, en te basant sur les données quantitatives fournies ET sur tes propres \
recherches web pour les éléments qualitatifs suivants :
- Actualité macro de dernière minute (Reuters, Bloomberg, sources fast-headline type @DeItaone)
- Pour le pétrole (MCL) : dernier rapport EIA (mercredi) ou API (mardi soir), niveau des \
  stocks de brut, actualité géopolitique récente (Moyen-Orient, OPEP+, sanctions)
- Si le calendrier économique ne t'a pas été fourni ou semble incomplet, cherche-le toi-même.

RÈGLES STRICTES :
1. Format de sortie EXACT pour chaque instrument (dans l'ordre MES, MYM, MNQ, MCL) :

[NOM INSTRUMENT] : [HAUSSE/BAISSE/NEUTRE/PAS ASSEZ D'INFO]
→ Explication en 1-2 phrases simples, pourquoi ce biais
→ Sources : [lien 1], [lien 2]

2. Si les signaux se contredisent trop (ex: yields disent baisse, futures disent hausse) \
-> biais NEUTRE, et explique la contradiction en une phrase.
3. Si tu n'as pas d'info fiable ou récente sur un instrument -> PAS ASSEZ D'INFO. \
Ne force JAMAIS une conclusion.
4. Reste factuel, ne sur-interprète pas. Donne le sens le plus probable avec un niveau \
de confiance implicite dans ta phrase (ex: "signal net" vs "biais léger").
5. Termine le rapport par une section "⚠️ ÉVÉNEMENT MACRO MAJEUR" si un CPI, NFP, FOMC, \
PMI/ISM ou PCE tombe pendant ou juste avant la fenêtre de trading du matin (8h00-10h30 ET), \
avec l'heure EXACTE en ET. Si aucun événement majeur, écris "Aucun événement macro majeur \
dans la fenêtre 8h00-10h30 ET aujourd'hui."
6. Inclue les vraies URLs des sources que tu as consultées via la recherche web (pas des \
URLs inventées).
7. Ne mets PAS de préambule ni de conclusion générale hors de ce format -- va droit au but.
8. Écris en français.
"""


def build_user_message(today_ny: dt.date, market_data_block: str, calendar_block: str) -> str:
    return f"""Date du jour (session US) : {today_ny.strftime('%A %d %B %Y')}

{calendar_block}

{market_data_block}

Utilise la recherche web pour :
1. Vérifier/compléter le calendrier économique du jour si nécessaire.
2. Trouver la dernière actualité macro (dans les dernières heures) pouvant influencer \
l'ouverture US.
3. Pour MCL spécifiquement : dernier rapport EIA/API sur les stocks de brut, et toute \
actualité géopolitique récente (Moyen-Orient, OPEP+, sanctions) pouvant impacter le WTI.

Produis ensuite le rapport de biais directionnel pour MES, MYM, MNQ et MCL selon le format \
et les règles définies dans tes instructions système."""


def resume_on_pause(client: anthropic.Anthropic, messages: list, tools: list, initial_user_content):
    """Envoie la requête et gère la reprise automatique si stop_reason == pause_turn."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        tools=tools,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        response = stream.get_final_message()

    restarts = 0
    while response.stop_reason == "pause_turn" and restarts < 5:
        restarts += 1
        print(f"  (reprise {restarts}/5 -- le modèle continue sa recherche...)")
        messages = [
            {"role": "user", "content": initial_user_content},
            {"role": "assistant", "content": response.content},
        ]
        with client.messages.stream(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            tools=tools,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

    return response


def generate_report(today_ny: dt.date, market_data: dict, calendar_events: list[dict]) -> str:
    print(f"→ Synthèse et recherche web via {MODEL} (effort={EFFORT})...")

    client = anthropic.Anthropic()

    market_block = format_market_data_for_prompt(market_data)
    calendar_block = format_calendar_for_prompt(calendar_events)
    user_content = build_user_message(today_ny, market_block, calendar_block)

    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
    messages = [{"role": "user", "content": user_content}]

    response = resume_on_pause(client, messages, tools, user_content)

    if response.stop_reason == "refusal":
        return "⚠️ La génération du rapport a été refusée par les filtres de sécurité du modèle. Réessayez plus tard ou consultez le calendrier manuellement."

    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_parts).strip()


def save_report(report_text: str, today_ny: dt.date) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / f"rapport_{today_ny.isoformat()}.md"
    header = f"# Rapport fondamental matinal futures -- {today_ny.strftime('%A %d %B %Y')}\n\n"
    out_path.write_text(header + report_text + "\n", encoding="utf-8")
    return out_path


def main():
    now_ny = dt.datetime.now(NY_TZ)
    today_ny = now_ny.date()

    print(f"=== Analyse fondamentale matinale -- {today_ny.isoformat()} ({now_ny.strftime('%H:%M')} ET) ===\n")

    market_data = fetch_market_data()
    calendar_events = fetch_economic_calendar(today_ny)

    report_text = generate_report(today_ny, market_data, calendar_events)

    out_path = save_report(report_text, today_ny)

    print("\n" + "=" * 70)
    print(report_text)
    print("=" * 70)
    print(f"\n✓ Rapport sauvegardé : {out_path}")


if __name__ == "__main__":
    main()
