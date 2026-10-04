"""Sections « Mes positions » et « En attente » du rapport (et du courriel) : pour chaque position
ouverte, entrée, dernier prix, latent, stop et objectif avec leur distance, progression, taille,
levier, risque, liquidation, règles actives et date de sortie maximale ; pour chaque signal en
attente, la date de réévaluation et ce qui le fera entrer. Démo uniquement."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import stats

PARIS = ZoneInfo("Europe/Paris")
DAY = 86400
ARM_FR = {"A": "A (stop large)", "B": "B (stop serré)", "C": "C (adaptatif)", "T": "T / palier P1", "K": "K (chaîne)"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def paris(ts_or_iso):
    ts = stats.parse_ts(ts_or_iso) if isinstance(ts_or_iso, str) else ts_or_iso
    return datetime.fromtimestamp(ts, PARIS).strftime("%d/%m %H:%M")


def px(x):
    if x is None:
        return "—"
    x = float(x)
    if x >= 100:
        return f"{x:,.2f}".replace(",", " ")
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6g}"


def pct(x, sign=True):
    return "—" if x is None else (f"{x:+.1%}" if sign else f"{x:.1%}")


def _rules(p):
    out = []
    be = _f(p.get("breakeven_trigger_price"))
    if be:
        out.append(f"stop remonté à l'entrée si le prix touche {px(be)}")
    ta = _f(p.get("trailing_activate_price"))
    if ta:
        out.append(f"stop suiveur ({pct(_f(p.get('trailing_pct')), False)} sous le plus haut) dès {px(ta)}")
    tr = (p.get("tranches") or {}).get("tranches") if isinstance(p.get("tranches"), dict) else None
    if tr:
        parts = []
        for k in ("A", "B", "C"):
            t = tr.get(k) or {}
            sh = _f(t.get("share")) or 0
            if sh > 0:
                tgt = f"objectif {px(t.get('target'))}" if t.get("target") else "coureur, stop chandelier 3 x ATR"
                parts.append(f"tranche {k} {sh:.0%} ({tgt}, {t.get('status')})")
        if parts:
            out.append("; ".join(parts))
    if _f(p.get("stop_price")) and _f(p.get("initial_stop_price")) and \
            abs(float(p["stop_price"]) - float(p["initial_stop_price"])) > 1e-12:
        out.append(f"stop déplacé (initial {px(p['initial_stop_price'])})")
    return " ; ".join(out) or "aucune règle spéciale"


def positions_section(open_positions, signals, prices, now):
    """open_positions : positions ouvertes de tous les portefeuilles ; prices : {pair: dernier prix}."""
    L = ["## Mes positions ouvertes (détail)\n"]
    if not open_positions:
        return L + ["Aucune position ouverte.\n"]
    by_sig = {s["id"]: s for s in signals}
    tot_latent = 0.0
    tot_risk = 0.0
    pairs = []
    for p in open_positions:
        if p["pair"] not in pairs:
            pairs.append(p["pair"])
    for pair in pairs:
        ps = sorted([p for p in open_positions if p["pair"] == pair], key=lambda p: p["arm"])
        p0 = ps[0]
        last = prices.get(pair)
        entry0 = float(p0["entry_price"])
        sig = by_sig.get(p0.get("signal_id")) or {}
        why = sig.get("decision_reason") or "—"
        L.append(f"### {pair.replace('USDT', '')} — entrée le {paris(p0['opened_at'])} (Paris) à {px(entry0)}")
        L.append(f"Dernier prix : **{px(last)}** ({pct(last / entry0 - 1) if last else '—'} depuis l'entrée) · "
                 f"plus haut depuis l'entrée {px(max(_f(p.get('highest_price')) or 0 for p in ps) or None)} · "
                 f"raison de l'entrée : {why}\n")
        L.append("| Portefeuille | Stop (SL) | Distance SL | Objectif (TP) | Distance TP | Progression vers TP | "
                 "Taille · levier | Risque au stop | Latent (hors frais) | Liquidation estimée | Sortie max |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for p in ps:
            entry = float(p["entry_price"])
            sl, tp = _f(p.get("stop_price")), _f(p.get("tp_price"))
            size = _f(p.get("size_usd")) or 0
            risk = _f(p.get("risk_usd"))
            if risk is None and sl:
                risk = size * (entry - sl) / entry
            lat = size * (last / entry - 1) if last else None
            if lat is not None:
                tot_latent += lat
            tot_risk += risk or 0
            prog = (last - entry) / (tp - entry) if (last and tp and tp != entry) else None
            left = stats.parse_ts(p["max_hold_until"]) - now if p.get("max_hold_until") else None
            L.append(f"| {ARM_FR.get(p['arm'], p['arm'])} | {px(sl)} | "
                     f"{pct(sl / last - 1) if (sl and last) else pct(sl / entry - 1) if sl else '—'} | {px(tp)} | "
                     f"{pct(tp / last - 1) if (tp and last) else pct(tp / entry - 1) if tp else '—'} | "
                     f"{'—' if prog is None else f'{prog:.0%}'} | {size:.0f} $ · x{float(p.get('leverage') or 1):g} | "
                     f"{'—' if risk is None else f'{risk:.2f} $'} | "
                     f"{'—' if lat is None else f'{lat:+.2f} $'} | {px(p.get('liquidation_price'))} | "
                     f"{paris(p['max_hold_until']) if p.get('max_hold_until') else '—'}"
                     f"{f' ({left / DAY:.1f} j)' if left is not None else ''} |")
        rules = {p["arm"]: _rules(p) for p in ps}
        L.append("\nRègles actives : " + " · ".join(f"**{arm}** : {r}" for arm, r in rules.items()) + "\n")
    L.append(f"**Total** : {len(open_positions)} position(s) sur {len(pairs)} crypto(s) · latent "
             f"{tot_latent:+.2f} $ (hors frais et funding) · perte maximale si tous les stops sont touchés ≈ "
             f"{tot_risk:.2f} $.\n")
    L.append("*Lecture* : distance SL = baisse à subir avant le stop ; distance TP = hausse qu'il reste à faire ; "
             "progression 0 % = au prix d'entrée, 100 % = objectif atteint (négative si le prix est sous l'entrée). "
             "Les sorties sont vérifiées 4 fois par jour sur des bougies de 15 min fermées, rejouées à la minute.\n")
    return L


def waits_section(signals, now, rules):
    waits = [s for s in signals if s.get("decision") == "wait" and s.get("reevaluate_after")]
    latest = {}
    for s in sorted(waits, key=lambda s: s["id"]):
        latest[s["pair"]] = s
    pending = [s for s in latest.values() if stats.parse_ts(s["reevaluate_after"]) > now - 2 * DAY]
    L = ["## En attente (réévaluation prévue)\n"]
    if not pending:
        return L + ["Aucun signal en attente.\n"]
    drop = float(rules.get("max_drop_from_signal_close", 0.15))
    vmin = float(rules.get("vol_ratio_min", 2))
    wmax = int(rules.get("wait_max_days", 2))
    L.append("| Crypto | Score | Détecté le | Pourquoi on attend | Réévaluation à partir de | Abandon après |")
    L.append("|---|---|---|---|---|---|")
    for s in sorted(pending, key=lambda s: stats.parse_ts(s["reevaluate_after"])):
        det = stats.parse_ts(s["detected_at"])
        L.append(f"| {s['pair'].replace('USDT', '')} | {float(s.get('score') or 0):g} | {paris(det)} | "
                 f"{(s.get('decision_reason') or '').split(':')[0]} | {paris(s['reevaluate_after'])} | "
                 f"{paris(det + (wmax + 1) * DAY)} |")
    L.append(f"\nConditions d'entrée à la réévaluation : aucune nouvelle bougie journalière ≥ +15 %, volume toujours "
             f"≥ {vmin:g}x la moyenne, prix pas plus de {drop:.0%} sous la clôture du jour du signal, aucune alerte "
             f"(déblocage, transfert de l'équipe, avertissement d'exchange). Sinon le signal est abandonné.\n")
    return L


def deadlines_section(open_positions, signals, cfg_get, now):
    ev = []
    grp = {}
    for p in open_positions:
        if p.get("max_hold_until"):
            k = (p["pair"], paris(p["max_hold_until"]))
            grp.setdefault(k, [stats.parse_ts(p["max_hold_until"]), []])[1].append(p["arm"])
    for (pair, _), (ts, arms) in grp.items():
        ev.append((ts, f"sortie au plus tard de {pair.replace('USDT', '')} ({', '.join(sorted(arms))}) "
                       f"si ni stop ni objectif n'est touché"))
    for s in signals:
        if s.get("decision") == "wait" and s.get("reevaluate_after") and stats.parse_ts(s["reevaluate_after"]) > now:
            ev.append((stats.parse_ts(s["reevaluate_after"]), f"réévaluation de {s['pair'].replace('USDT', '')}"))
    for key, label in (("r6_readonly_until", "fin de la lecture seule des paliers (routine 6)"),
                       ("chain_readonly_until", "fin de la lecture seule des chaînes (routine 7)")):
        v = cfg_get(key)
        if v and stats.parse_ts(str(v)) > now:
            ev.append((stats.parse_ts(str(v)), label))
    L = ["## Prochaines échéances\n"]
    if not ev:
        return L + ["Aucune.\n"]
    for ts, txt in sorted(ev):
        L.append(f"- **{paris(ts)}** — {txt}")
    return L + [""]
