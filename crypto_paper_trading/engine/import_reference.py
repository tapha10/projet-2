"""Import des cas historiques de référence (ex. base_gainers_2026-10-03.xlsx) dans `signals`.

Usage : python -m engine.import_reference base_gainers_2026-10-03.xlsx --out ref.sql
        (puis exécuter ref.sql via le connecteur Supabase)

Les lignes sont marquées `is_reference = true` : elles servent d'historique de
comparaison et ne déclenchent aucune position. Les colonnes sont reconnues par
leur nom (insensible à la casse) ; les colonnes inconnues vont dans `metrics`.
Accepte .xlsx (nécessite openpyxl : pip install openpyxl) ou .csv.
"""
from __future__ import annotations

import argparse
import csv
import re

from .market import canonical
from .sqlgen import q, qarr, qts

ALIASES = {
    "pair": ("pair", "paire", "symbol", "symbole", "ticker", "token", "coin", "crypto"),
    "detected_at": ("detected_at", "date_signal", "signal_date", "date", "date du signal"),
    "info_published_at": ("info_published_at", "date_info", "date_publication", "publication", "date annonce"),
    "price_at_detection": ("price_at_detection", "prix", "price", "prix_signal", "prix au signal", "entry"),
    "signal_types": ("signal_types", "signal", "type", "types", "catalyseur", "catalyst"),
    "evidence": ("evidence", "source", "sources", "url", "lien"),
    "decision_reason": ("notes", "note", "commentaire", "comment", "raison"),
}


def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def read_rows(path):
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    import openpyxl  # noqa: import tardif, seulement pour .xlsx
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            continue
        for r in it:
            if any(v is not None for v in r):
                rows.append({str(h): v for h, v in zip(header, r) if h is not None} | {"_sheet": ws.title})
    return rows


def to_sql(rows):
    out = []
    for r in rows:
        lower = {norm(k): v for k, v in r.items()}
        got = {}
        for field, names in ALIASES.items():
            for n in names:
                if lower.get(n) not in (None, ""):
                    got[field] = lower[n]
                    break
        if "pair" not in got:
            continue
        try:
            pair = canonical(str(got["pair"]) if "USDT" in str(got["pair"]).upper() else str(got["pair"]) + "USDT")
        except ValueError:
            continue
        types = [t.strip() for t in re.split(r"[,;/|]", str(got.get("signal_types") or "reference")) if t.strip()]
        ev = got.get("evidence")
        evidence = [{"url": u, "titre": None, "date_publication": None}
                    for u in re.findall(r"https?://\S+", str(ev))] if ev else []
        used = {norm(n) for names in ALIASES.values() for n in names}
        metrics = {k: (v if isinstance(v, (int, float, str)) or v is None else str(v))
                   for k, v in r.items() if norm(k) not in used}
        price = got.get("price_at_detection")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        det = got.get("detected_at")
        info = got.get("info_published_at")
        out.append(
            "insert into signals(detected_at, pair, signal_types, info_published_at, evidence, "
            "price_at_detection, decision, decision_reason, data_source, metrics, is_reference) values ("
            f"{qts(str(det)) if det else 'now()'}, {q(pair)}, {qarr(types)}, {qts(str(info)) if info else 'null'}, "
            f"{q(evidence)}, {q(price)}, null, {q(str(got.get('decision_reason') or 'cas de référence importé'))}, "
            f"'import_reference', {q(metrics)}, true);")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sql = to_sql(read_rows(a.path))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("begin;\n" + "\n".join(sql) + "\ncommit;\n")
    print(f"{len(sql)} cas de référence prêts -> {a.out}")


if __name__ == "__main__":
    main()
