"""Récapitulatif lisible : ce que le système a vu, ce qu'il a fait, et POURQUOI (en clair).

Utilisé par `cli report` (sections « En bref » et « Ce que le système a vu cette semaine »).
"""
from __future__ import annotations

import re

from . import stats

SIGNAL_FR = {
    "dated_announcement": "annonce datée",
    "listing_or_perp": "listing / nouveau contrat",
    "volume_doubling": "volume qui double",
    "oi_rising": "open interest en hausse",
    "revenue_or_buyback": "revenus / rachats",
    "oversold_or_breakout": "survente ou cassure",
    "top_gainer_24h": "forte hausse 24 h",
    "pre_move_accumulation": "accumulation avant la hausse",
    "annonce_exchange_fraiche": "annonce d'exchange < 24 h",
}
ALERT_FR = {
    "alert_peak_passed": "pic déjà passé",
    "alert_unlock_7d": "déblocage de jetons sous 7 jours",
    "alert_team_transfer": "transferts de l'équipe vers les exchanges",
    "alert_exchange_warning": "surveillance / retrait annoncé par un exchange",
}
MODE_FR = {"mode_momentum": "hausse 24 h", "mode_pre_move": "avant la hausse", "mode_announcement": "annonce d'exchange"}
DECISION_FR = {"enter": "✅ ENTRÉE", "wait": "⏳ ATTENTE", "skip": "❌ ÉCARTÉ"}


def modes_of(s):
    m = [MODE_FR[t] for t in (s.get("signal_types") or []) if t in MODE_FR]
    return ", ".join(m) if m else "hausse 24 h"


def signals_fr(s):
    return ", ".join(SIGNAL_FR[t] for t in (s.get("signal_types") or []) if t in SIGNAL_FR) or "aucun"


def simple_reason(s):
    """Raison de la décision en une phrase simple."""
    r = s.get("decision_reason") or ""
    alerts = s.get("alerts") or []
    dec = s.get("decision")
    if dec == "enter":
        base = "Signal assez fort et aucune alerte : position virtuelle ouverte."
        if "non ouvert" in r:
            base += " Certains bras étaient déjà pleins."
        return base
    if "alert_team_transfer" in alerts or "transferts de l'équipe" in r:
        return "L'équipe ou le market maker envoie des jetons vers les exchanges : risque de vente, on s'abstient."
    if "alert_unlock_7d" in alerts or "unlock" in r:
        return "Des jetons vont être débloqués dans moins de 7 jours : pression vendeuse probable, on s'abstient."
    if "alert_exchange_warning" in alerts or "surveillance" in r:
        return "Un exchange a mis la crypto sous surveillance ou annonce son retrait : on s'abstient."
    if "bougie du signal" in r:
        m = re.search(r"\+(\d+)%", r)
        pct = f" (+{m.group(1)} %)" if m else ""
        return (f"Déjà en très forte hausse sur la journée{pct}. On n'achète jamais cette bougie : "
                "on attend 1 à 2 jours pour voir si le mouvement tient.")
    if "aucune place" in r:
        return "Signal valide mais plafond atteint (8 positions ou 3 entrées par jour) : non ouvert."
    if "conditions" in r:
        detail = r.split(":", 1)[-1].strip() if ":" in r else r
        return f"Réévaluation après attente : conditions non remplies ({detail})."
    if "prix indisponible" in r or "données indisponibles" in r:
        return "Prix indisponible au moment de la décision (source de données en panne)."
    m = re.search(r"score (-?[\d.]+) < seuil ([\d.]+)", r)
    if m:
        sc, th = float(m.group(1)), float(m.group(2))
        warn = [ALERT_FR[a] for a in alerts if a in ALERT_FR]
        why = f"Signal trop faible : {sc:g} point(s) sur {th:g} requis."
        if warn:
            why += " Pénalité : " + ", ".join(warn) + "."
        missing = [lab for key, lab in (("dated_announcement", "annonce datée"), ("volume_doubling", "volume qui double"),
                                         ("oi_rising", "open interest en hausse"),
                                         ("pre_move_accumulation", "accumulation avant la hausse"))
                   if key not in (s.get("signal_types") or [])]
        if not warn and missing:
            why += " Il manquait par exemple : " + " ou ".join(missing[:2]) + "."
        return why
    return r[:160] or "—"


def reason_bucket(s):
    t = simple_reason(s)
    if s.get("decision") == "enter":
        return "Entrées"
    for key, label in (("trop faible", "Signal trop faible (score < 3)"),
                       ("très forte hausse", "Déjà en forte hausse : attente"),
                       ("débloqués", "Déblocage de jetons proche"),
                       ("équipe", "Transferts de l'équipe"),
                       ("surveillance", "Alerte d'un exchange"),
                       ("plafond", "Plafond de positions atteint"),
                       ("Réévaluation", "Attente non confirmée"),
                       ("indisponible", "Données indisponibles")):
        if key in t:
            return label
    return "Autre"


def sources_md(s, n=2):
    out = []
    for e in (s.get("evidence") or [])[:n]:
        url, title = e.get("url"), (e.get("titre") or "source")[:60]
        date = (e.get("date_publication") or "")[:10]
        out.append(f"[{title}]({url}) {date}" if url else f"{title} {date}")
    return " ; ".join(out) if out else "—"


def scan_rows(log, wk0):
    return [r for r in log if (r.get("change") or {}).get("action") == "scan_summary"
            and stats.parse_ts(r["created_at"]) >= wk0]


def brief(week_sig, week_closed, open_now, arms_equity, tiers_line=None):
    """Section « En bref » (5 lignes au plus)."""
    dec = {k: sum(1 for s in week_sig if s.get("decision") == k) for k in ("enter", "wait", "skip")}
    L = ["## En bref\n"]
    L.append(f"- **{len(week_sig)} signaux** analysés cette semaine : {dec['enter']} entrée(s), "
             f"{dec['wait']} en attente, {dec['skip']} écarté(s).")
    L.append(f"- **{len(week_closed)} trade(s) fermé(s)**, **{len(open_now)} position(s) ouverte(s)**.")
    L.append("- Capital virtuel : " + " · ".join(f"bras {a} {v:,.2f} USDT".replace(",", " ")
                                                for a, v in arms_equity.items()) + ".")
    if dec["enter"] == 0:
        top = {}
        for s in week_sig:
            b = reason_bucket(s)
            top[b] = top.get(b, 0) + 1
        main = max(top.items(), key=lambda kv: kv[1]) if top else None
        L.append("- **Pourquoi aucune entrée ?** " + (f"surtout « {main[0]} » ({main[1]} signaux) — "
                                                     "détail plus bas." if main else "aucun signal détecté."))
    if tiers_line:
        L.append(f"- {tiers_line}")
    return L


def funnel(week_sig, scans, open_pairs_count):
    """Section « Ce que le système a vu cette semaine et pourquoi »."""
    L = ["\n## 3 ter. Ce que le système a vu cette semaine, et pourquoi\n"]
    n_scans = len(scans)
    pm_scanned = sum(int(((r.get("evidence") or {}).get("early_detection") or {}).get("pre_move", {}).get("scannes") or 0)
                     for r in scans)
    n_ann = sum(int(((r.get("evidence") or {}).get("early_detection") or {}).get("announcements", {}).get("n_annonces") or 0)
                for r in scans)
    if n_scans == 0:
        L.append("*Le résumé de chaque passage d'analyse est enregistré à partir du 04/10/2026 ; "
                 "les signaux ci-dessous restent tous détaillés.*\n")
    L.append(f"**Recherches effectuées** : {n_scans} passage(s) d'analyse enregistré(s) ; "
             f"{pm_scanned} examens « avant la hausse » ; {n_ann} annonce(s) d'exchanges lues "
             "(Binance, OKX, KuCoin, Bitget, Bithumb).\n")
    L.append("**Parcours des candidats par mode de détection**\n")
    L.append("| Mode | Candidats retenus | ✅ Entrées | ⏳ Attente | ❌ Écartés |")
    L.append("|---|---|---|---|---|")
    for tag, label in MODE_FR.items():
        ss = [s for s in week_sig if tag in (s.get("signal_types") or [])]
        L.append(f"| {label} | {len(ss)} | {sum(1 for s in ss if s['decision'] == 'enter')} | "
                 f"{sum(1 for s in ss if s['decision'] == 'wait')} | {sum(1 for s in ss if s['decision'] == 'skip')} |")
    buckets = {}
    for s in week_sig:
        buckets.setdefault(reason_bucket(s), []).append(s)
    L.append("\n**Pourquoi les candidats n'ont pas été pris** (regroupé)\n")
    if not week_sig:
        L.append("Aucun candidat cette semaine : aucune crypto ne remplissait les conditions de départ "
                 "(forte hausse, accumulation avant la hausse ou annonce d'exchange).")
    else:
        L.append("| Raison | Nombre | Exemples |")
        L.append("|---|---|---|")
        for b, ss in sorted(buckets.items(), key=lambda kv: (kv[0] == "Entrées", -len(kv[1]))):
            L.append(f"| {b} | {len(ss)} | {', '.join(s['pair'].replace('USDT', '') for s in ss[:6])} |")
    L.append("\n**Détail de chaque signal**\n")
    if week_sig:
        L.append("| Date | Crypto | Mode | Score | Décision | Pourquoi (en clair) | Signaux vus | Sources |")
        L.append("|---|---|---|---|---|---|---|---|")
        for s in sorted(week_sig, key=lambda s: (s["decision"] != "enter", s["decision"] != "wait",
                                                  -(float(s.get("score") or 0)))):
            d = (s.get("detected_at") or "")[5:16].replace("T", " ")
            L.append(f"| {d} | **{s['pair'].replace('USDT', '')}** | {modes_of(s)} | {s.get('score') if s.get('score') is not None else '—'} | "
                     f"{DECISION_FR.get(s['decision'], s['decision'])} | {simple_reason(s)} | {signals_fr(s)} | {sources_md(s)} |")
    L.append("\n*Rappel des règles* : il faut **3 points** (annonce datée ou listing +2, volume qui double +1,5, "
             "accumulation avant la hausse +2, open interest +1, annonce d'exchange < 24 h +1, survente/cassure +1, "
             "forte hausse +0,5). Une hausse de 15 % ou plus le jour même impose d'attendre 1 à 2 jours. "
             "Déblocage de jetons, transferts de l'équipe ou alerte d'exchange : on s'abstient.")
    return L


CRITERIA_FR = {
    "compression_forte": "volatilité comprimée", "bollinger_serre": "bandes de Bollinger serrées",
    "volume_x2": "volume x2", "volume_x5": "volume x5", "oi_hausse_20": "open interest +20 %",
    "funding_negatif": "funding négatif", "catalyseur_fiable": "source fiable", "info_fraiche_24h": "info < 24 h",
    "sources_2plus": "2 sources ou plus", "pas_unlock_30j": "pas d'unlock sous 30 j",
    "pas_transfert_equipe": "pas de transfert de l'équipe", "btc_haussier": "BTC haussier",
    "pas_deja_monte_24h": "pas déjà +15 % en 24 h", "pas_deja_monte_7j": "pas déjà +30 % en 7 j",
    "stop_serre_8": "stop < 8 %", "liquide_5M": "liquidité > 5 M$", "heure_europe": "heures européennes",
    "mode_momentum": "mode hausse 24 h", "mode_avant_hausse": "mode avant la hausse", "mode_annonce": "mode annonce",
}
ACTION_FR = {"unlock": "débloquer", "risk_up": "augmenter le risque", "demote": "repasser en ombre",
             "stay_shadow": "rester en ombre", "split_change": "changer la découpe"}


def crit_fr(label):
    return " + ".join(CRITERIA_FR.get(x.strip(), x.strip()) for x in label.split("&"))


def glance(arms, t_book, per_tier, no_entry_reason):
    """Tableau « chaque stratégie en un coup d'œil » avec une phrase « pourquoi » en clair.
    arms : {A: dict(desc, open, closed_week, pnl_week, equity, halted)} ; t_book : même format ;
    per_tier : {P2: dict(n_events, need)} ou None."""
    L = ["\n**Chaque stratégie en un coup d'œil**\n",
         "| Stratégie | Règle | Positions ouvertes | Trades fermés (semaine) | PnL semaine | Statut / pourquoi |",
         "|---|---|---|---|---|---|"]

    def why(x):
        if x.get("halted"):
            return "⛔ Suspendu : perte > 15 % depuis le plus haut (garde-fou)."
        if x["open"] or x["closed_week"]:
            return "✅ Actif."
        return "💤 Aucune entrée : " + no_entry_reason
    for name, x in list(arms.items()) + ([("Palier P1 (portefeuille T)", t_book)] if t_book else []):
        L.append(f"| {name} | {x['desc']} | {x['open']} | {x['closed_week']} | {x['pnl_week']:+.2f} USDT | {why(x)} |")
    for tier, need, desc in (("P2", 40, "objectif 6 R, stop 3-6 %"), ("P3", 30, "objectif 10 R"), ("P4", 30, "objectif 50 R")):
        n = (per_tier or {}).get(tier, {}).get("n_events", 0)
        L.append(f"| Palier {tier} (ombre) | {desc} | – | – | – | 👻 Simulé sans capital : {n}/{need} résultats "
                 f"indépendants ; aucune décision avant {need}. |")
    return L
