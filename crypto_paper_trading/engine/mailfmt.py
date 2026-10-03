"""Convertit le rapport markdown en HTML d'e-mail (styles en ligne, compatible Gmail).

python3 -m engine.mailfmt report.md > report.html
Sous-ensemble géré : titres #/##/###, citations >, listes -, tableaux |, **gras**, *italique*,
`code`, [liens](url), paragraphes.
"""
from __future__ import annotations

import html
import re
import sys

C = dict(bg="#f4f6f8", card="#ffffff", text="#1f2933", muted="#52606d", accent="#0b6bcb",
         border="#d9e2ec", head="#eef2f7", warn_bg="#fff4e5", warn_border="#f0a020")


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: f'<a href="{html.escape(m.group(2))}" style="color:{C["accent"]};text-decoration:none">{m.group(1)}</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`", r'<code style="background:#eef2f7;padding:1px 4px;border-radius:3px">\1</code>', t)
    return t


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [r for r in cells[2:]]
    th = "".join(f'<th style="text-align:left;padding:6px 8px;background:{C["head"]};border-bottom:1px solid {C["border"]};'
                 f'font-size:12px;color:{C["muted"]};white-space:nowrap">{inline(h)}</th>' for h in head)
    trs = []
    for i, r in enumerate(body):
        tds = "".join(f'<td style="padding:6px 8px;border-bottom:1px solid {C["border"]};font-size:13px;'
                      f'vertical-align:top">{inline(c)}</td>' for c in r)
        trs.append(f"<tr>{tds}</tr>")
    return (f'<div style="overflow-x:auto"><table cellspacing="0" cellpadding="0" style="border-collapse:collapse;'
            f'width:100%;margin:8px 0 14px">{"<tr>" + th + "</tr>"}{"".join(trs)}</table></div>')


def convert(md):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*-", lines[i + 1].strip()):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(table(block))
            continue
        if s.startswith("# "):
            out.append(f'<h1 style="font-size:20px;margin:0 0 12px;color:{C["text"]}">{inline(s[2:])}</h1>')
        elif s.startswith("## "):
            out.append(f'<h2 style="font-size:16px;margin:22px 0 8px;padding-top:12px;border-top:1px solid {C["border"]};'
                       f'color:{C["text"]}">{inline(s[3:])}</h2>')
        elif s.startswith("### "):
            out.append(f'<h3 style="font-size:14px;margin:16px 0 6px;color:{C["text"]}">{inline(s[4:])}</h3>')
        elif s.startswith(">"):
            out.append(f'<div style="background:{C["warn_bg"]};border-left:4px solid {C["warn_border"]};padding:10px 12px;'
                       f'margin:8px 0 12px;font-size:13px;color:{C["text"]}">{inline(s.lstrip("> ").strip())}</div>')
        elif s.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(f'<li style="margin:3px 0">{inline(lines[i].strip()[2:])}</li>')
                i += 1
            out.append(f'<ul style="margin:6px 0 12px;padding-left:20px;font-size:14px">{"".join(items)}</ul>')
            continue
        else:
            out.append(f'<p style="margin:6px 0 10px;font-size:14px;line-height:1.5">{inline(s)}</p>')
        i += 1
    body = "\n".join(out)
    return (f'<div style="background:{C["bg"]};padding:16px 8px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
            f'color:{C["text"]}"><div style="max-width:860px;margin:0 auto;background:{C["card"]};border:1px solid {C["border"]};'
            f'border-radius:8px;padding:20px 18px">{body}</div></div>')


if __name__ == "__main__":
    print(convert(open(sys.argv[1], encoding="utf-8").read()))
