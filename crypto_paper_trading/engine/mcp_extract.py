"""Extrait le JSON d'un résultat `execute_sql` que l'outil a enregistré dans un fichier (résultat trop long).

Usage : python3 -m engine.mcp_extract <fichier enregistré> <sortie.json> [colonne]
Pour forcer l'enregistrement d'un petit résultat : `select paper_state()::text as s, repeat('.', 60000) as pad;`
puis passer la colonne `s`. Évite de recopier le JSON à la main (économie de jetons)."""
import json
import sys


def extract(path, key=None):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, list):                          # format [{"type": "text", "text": "..."}]
        d = json.loads(d[0]["text"])
    raw = d["result"] if isinstance(d, dict) else d
    i = raw.index("\n\n<untrusted-data")
    i = raw.index(">", i) + 1
    j = raw.index("</untrusted-data", i)
    rows = json.loads(raw[i:j].strip())
    v = rows[0][key] if key else list(rows[0].values())[0]
    return json.loads(v) if isinstance(v, str) else v


if __name__ == "__main__":
    out = extract(sys.argv[1], sys.argv[3] if len(sys.argv) > 3 else None)
    json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
    print(sys.argv[2], list(out.keys()) if isinstance(out, dict) else len(out))
