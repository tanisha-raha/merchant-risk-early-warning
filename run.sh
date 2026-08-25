#!/usr/bin/env bash
# Reproduces every number reported so far (Phase 0-4). Extended as later
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

echo "=== Phase 2: lead-time / order_volume-ablation diagnostic (DECISIONS.md D13-D14) ==="
python3 src/phase2_lead_time_diagnostic.py

echo "=== Phase 2: acceleration vs. the N=8 silence rule (DECISIONS.md D14 sec.2) ==="
python3 src/phase2_acceleration_vs_rule.py

echo "=== Phase 2: active-only-rows core-hypothesis check (DECISIONS.md D14 sec.3) ==="
python3 src/phase2_active_only_ablation.py

echo "=== Phase 3: false-alarm-rate sweep vs. the N=8 rule (DECISIONS.md D15-D16) ==="
python3 src/policy.py

echo "=== Phase 4: cost-parameter sensitivity + tornado plot (DECISIONS.md D17) ==="
python3 src/phase4_sensitivity.py

echo "=== Phase 4: ablation -- levels vs. trend vs. acceleration (DECISIONS.md D18) ==="
python3 src/phase4_ablation.py

echo "=== Phase 4: headline lead-time figure + calibration (DECISIONS.md D19) ==="
python3 src/phase4_calibration.py

echo "=== Phase 4: slice analysis and fairness (DECISIONS.md D20) ==="
python3 src/phase4_slices.py

echo "=== Phase 4: isotonic-calibrated FAR sweep (DECISIONS.md D21) ==="
python3 src/phase4_calibrated_sweep.py

echo "done."
