#!/usr/bin/env bash
# Routine économe : tout le travail en une commande (simulation papier, aucun pari réel).
#   bash foot/routine.sh quotidien   -> R3 résultats, R4 rapport, R1 prédictions + combiné du jour
#   bash foot/routine.sh hebdo       -> R5 optimisation approfondie (réentraînement) + R6 rapport hebdomadaire
set -uo pipefail
cd "$(dirname "$0")/.."
B=claude/foot-paper-analysis
git fetch -q origin $B && git checkout -q $B && git pull -q origin $B
cd foot
pip install -q -r requirements.txt >/dev/null 2>&1
export PYTHONPATH=.
if ! python -m pytest -q tests >/tmp/foot_tests.log 2>&1; then
  python -m foot.cli state-from-journal >/dev/null
  python -m foot.cli not-run "$1" "tests en échec : $(tail -1 /tmp/foot_tests.log)"
  python -m foot.cli journal-write "$1" >/dev/null
  git add etat && git commit -qm "$1 non exécutée (tests)" && git push -q origin $B
  echo "ÉCHEC : tests rouges ($(tail -1 /tmp/foot_tests.log)). Rien n'a été exécuté."; exit 1
fi
python -m foot.cli state-from-journal >/dev/null
run() { if ! python -m foot.cli "$@" > /tmp/foot_$1.log 2>&1; then echo "ÉCHEC $1 : $(tail -2 /tmp/foot_$1.log | tr '\n' ' ')"; return 1; fi; }
if [ "$1" = quotidien ]; then
  run r3; run r4; run r1
  python -m foot.cli journal-write quotidien >/dev/null
  echo "--- R1 ---"; grep -v "^Simulation" /tmp/foot_r1.log | head -8
elif [ "$1" = hebdo ]; then
  run train --rebuild; run r5 --deep; run r6
  python -m foot.cli journal-write hebdo >/dev/null
  head -25 /tmp/foot_r6.log
fi
cd ..
git add foot/etat foot/rapports foot/models_store foot/docs 2>/dev/null
git commit -qm "Routine $1 $(date -u +%F)" && for i in 1 2 3 4; do git push -q origin $B && break; git pull -q --rebase origin $B; sleep $((2**i)); done
echo "OK (simulation papier, pas un conseil de pari)"
