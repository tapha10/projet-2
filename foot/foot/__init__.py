"""Système d'analyse plus/moins 2,5 buts — simulation papier uniquement.

Aucun pari réel, pas un conseil de pari. Parier de l'argent réel comporte un risque de perte.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AVERTISSEMENT = ("Simulation papier, pas un conseil de pari ; parier de l'argent réel "
                 "comporte un risque de perte.")


def load_config(path=None):
    p = Path(path) if path else ROOT / "config" / "config.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)
