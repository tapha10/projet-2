#!/usr/bin/env bash
# End-to-end, reproducible pipeline for the Bybit x10 prediction study.
# Re-running this script re-collects fresh data (resumable/incremental) and
# regenerates every downstream analysis, model, and report artifact.
set -euo pipefail
cd "$(dirname "$0")"
source ../.venv/bin/activate 2>/dev/null || { python3 -m venv ../.venv && source ../.venv/bin/activate && pip install -q -r requirements.txt; }

echo "== 1/10 init db =="
python3 src/db/db.py

echo "== 2/10 build Bybit universe (CoinGecko) =="
python3 src/collectors/build_universe.py

echo "== 3/10 collect 365d price/volume + snapshot (CoinGecko) =="
python3 src/collectors/history_collector.py

echo "== 4/10 collect multi-year OHLCV for Coinbase-cross-listed coins =="
python3 src/collectors/coinbase_history.py

echo "== 5/10 collect DeFiLlama TVL history =="
python3 src/collectors/defillama_collector.py

echo "== 6/10 market regime classification =="
python3 src/features/market_regime.py

echo "== 7/10 rally-leg event detection (x5/x10/x20/x50/x100) =="
python3 src/features/events.py

echo "== 8/10 feature engineering (Dataset A + Dataset B) =="
python3 src/features/engineering.py
python3 src/features/engineering_cb.py

echo "== 9/10 statistics, ML, scoring, timing, backtest =="
python3 src/analysis/correlations.py
python3 src/ml/train.py
python3 src/ml/scoring.py
python3 src/analysis/timing.py
python3 src/ml/score_oos.py
python3 src/backtest/engine.py

echo "== 10/10 figures + final report =="
python3 src/report/make_figures.py
python3 src/report/generate_report.py

echo "Pipeline complete. See reports/final_report.md"
