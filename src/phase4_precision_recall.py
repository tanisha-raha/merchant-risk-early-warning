"""Precision and recall on the held-out test set, at the calibrated FAR
sweep's operating thresholds (1%, 5%, 10%) -- the numbers the evaluation
track asks for by name, not currently stated directly anywhere else in
this project (AUC, calibration, lead time, and cost were, but not these).

Uses the SAME isotonic calibrator and the SAME thresholds already
established in DECISIONS.md D21 (0.200000 / 0.054545 / 0.040389 at
1%/5%/10% FAR, fit on train only, thresholded against genuinely censored
sellers' test-period rows) -- reused here, not recomputed, so this table
is consistent with every other calibrated number already reported.

Precision/recall are computed on the full test-period row population
(fit["_test"] from model.run_for_n -- every eligible seller's test-period
rows, both the 237 event rows and every censored row), against the
original at-event-week label (1 only at the exact confirmation week),
which is the standard binary-classification framing "held-out test set"
implies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from features import build_features
from model import PRIMARY_N, predict, run_for_n
from panel import build_panel
from phase4_calibrated_sweep import fit_calibrator

FAR_POINTS = [0.01, 0.05, 0.10]


def load_calibrated_thresholds() -> dict[float, float]:
    """Reuse the exact thresholds already established in DECISIONS.md D21
    (figures/phase4_calibrated_sweep.csv) rather than recomputing them --
    keeps this table consistent with every other calibrated number
    already reported, to full float precision."""
    sweep = pd.read_csv("figures/phase4_calibrated_sweep.csv")
    return dict(zip(sweep["false_alarm_rate"], sweep["threshold"]))


def main() -> None:
    thresholds = load_calibrated_thresholds()

    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    fit = run_for_n(panel, features_df, PRIMARY_N)
    calibrator = fit_calibrator(fit)

    clf, scaler, feature_cols = fit["_clf"], fit["_scaler"], fit["_feature_cols"]
    test = fit["_test"]
    y_true = test["label"].to_numpy()
    raw_scores = predict(clf, scaler, test, feature_cols)
    calibrated_scores = calibrator.predict(raw_scores)

    n_test_rows = len(test)
    n_actual_events = int(y_true.sum())
    print(f"test window: {n_test_rows} rows, {n_actual_events} actual events (label=1 rows)\n")

    rows = []
    for far in FAR_POINTS:
        threshold = thresholds[far]
        flagged = calibrated_scores >= threshold

        tp = int(((y_true == 1) & flagged).sum())
        fp = int(((y_true == 0) & flagged).sum())
        fn = int(((y_true == 1) & ~flagged).sum())
        n_flagged = tp + fp

        precision = tp / n_flagged if n_flagged else float("nan")
        recall = tp / n_actual_events if n_actual_events else float("nan")

        rows.append(
            {
                "far": far,
                "threshold": threshold,
                "n_flagged": n_flagged,
                "true_events_caught": tp,
                "false_positives": fp,
                "missed_events": fn,
                "precision": precision,
                "recall": recall,
            }
        )
        print(
            f"FAR={far:.0%}: threshold={threshold:.6f}, flagged={n_flagged}, "
            f"TP={tp}, FP={fp}, FN={fn}, precision={precision:.4f} ({precision:.1%}), "
            f"recall={recall:.4f} ({recall:.1%})"
        )

    out = pd.DataFrame(rows)
    out.to_csv("figures/phase4_precision_recall.csv", index=False)
    with open("figures/phase4_precision_recall.json", "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print("\nwrote figures/phase4_precision_recall.csv/.json")


if __name__ == "__main__":
    main()
