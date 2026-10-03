"""Génération de SQL littéral sûr (les routines l'exécutent via le connecteur Supabase)."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone


def q(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return "null"
        return repr(v)
    if isinstance(v, (dict, list)):
        return q(json.dumps(v, ensure_ascii=False, default=str)) + "::jsonb"
    return "'" + str(v).replace("'", "''") + "'"


def qts(ts):
    if ts is None:
        return "null"
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return q(ts) + "::timestamptz"


def qarr(items):
    items = [i for i in (items or []) if i]
    if not items:
        return "array[]::text[]"
    return "array[" + ",".join(q(str(i)) for i in items) + "]::text[]"


def load_json_loose(path):
    """Charge un JSON enregistré depuis une sortie d'outil : accepte le JSON brut,
    une liste de lignes [{"paper_state": {...}}] ou du texte entourant le JSON."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"[\[{]", raw)
        if not m:
            raise
        data, _ = json.JSONDecoder().raw_decode(raw[m.start():])
    # dépliage des enveloppes usuelles
    for _ in range(3):
        if isinstance(data, dict) and "result" in data and isinstance(data["result"], str):
            return load_json_text(data["result"])
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) and len(data[0]) == 1:
            data = next(iter(data[0].values()))
            if isinstance(data, str):
                data = json.loads(data)
            continue
        break
    return data


def load_json_text(text):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        m = re.search(r"\[\s*\{", text)
        f.write(text[m.start():] if m else text)
        name = f.name
    return load_json_loose(name)
