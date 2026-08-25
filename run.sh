#!/usr/bin/env bash
# Reproduces every number reported so far (Phase 0-2). Extended as later
# phases land -- see README.md (once written) for the final, authoritative
# version of this file.
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH=src  # see FAILURES.md F4: sibling-module imports need src/ on the path

echo "=== lint ==="
ruff check src/ tests/

echo "=== tests ==="
pytest tests/ -q

echo "=== Phase 0: panel + candidate distress-event definitions ==="
python3 src/panel.py
python3 src/distress_events.py
python3 src/phase0_report.py
python3 src/phase0_calendar_hazard.py
python3 src/phase0_benign_exit.py

echo "=== Phase 1: feature pipeline ==="
python3 src/features.py

echo "=== Phase 2: discrete-time hazard model ==="
python3 src/model.py

echo "done."
