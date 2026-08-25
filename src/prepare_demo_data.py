"""One-time data preparation for the Streamlit demo (app.py). Not part of
run.sh -- this is demo scaffolding, not part of the reproducibility path,
and its outputs (figures/demo_*.csv) are the "existing artefacts" app.py
reads. No new modeling decisions here: reuses the exact already-fitted
primary model (model.run_for_n), the exact isotonic calibrator (D21), and
the exact per-seller GMV and FAR-sweep economics already established
(policy.py, D16, D21). This script does the one legitimate round of
computation; app.py itself never refits, rescans, or resweeps anything --
it only reads what this script writes.

Outputs:
  figures/demo_test_predictions.csv -- one row per (seller, test-period
    week): calibrated hazard, raw score, label/outcome context, and each
    feature's exact linear contribution to the score (coefficient x
    standardised value -- an honest, exact decomposition for a linear
    model, not an approximation). app.py computes "what changed since
    last week" by subtracting two rows of this table -- arithmetic, not
    re-inference.
  figures/demo_seller_gmv.csv -- each seller's own mean weekly revenue
    (policy.per_seller_weekly_gmv, reused exactly).
  figures/demo_event_acceleration.csv -- for the 237 test-period events,
    whether/by how many weeks the model beat the N=8 rule, at each of the
    three already-established FAR operating points (1%/5%/10%) -- reuses
    policy.score_event_histories / acceleration_weeks_at_threshold with
    the D21 calibrated thresholds and calibrator, the same mechanism
    phase4_calibrated_sweep.py already used for the aggregate numbers.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from features import build_features
from model import PRIMARY_N, run_for_n
from panel import build_panel
from phase4_calibrated_sweep import fit_calibrator
from policy import acceleration_weeks_at_threshold, per_seller_weekly_gmv, score_event_histories

FIG_DIR = Path("figures")
FAR_POINTS = [0.01, 0.05, 0.10]


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    fit = run_for_n(panel, features_df, PRIMARY_N)
    calibrator = fit_calibrator(fit)

    clf, scaler, feature_cols = fit["_clf"], fit["_scaler"], fit["_feature_cols"]
    test = fit["_test"]

    # --- per-row calibrated hazard + exact linear feature contributions ---
    X = test[feature_cols].to_numpy(dtype=float)
    X_std = scaler.transform(X)
    raw_score = clf.predict_proba(X_std)[:, 1]
    calibrated_hazard = calibrator.predict(raw_score)
    contributions = X_std * clf.coef_[0]  # elementwise: exact per-feature contribution to the logit

    out = test[["seller_id", "week", "tenure_weeks", "category", "label", "event_B", "event_week"]].copy()
    out["raw_score"] = raw_score
    out["calibrated_hazard"] = calibrated_hazard
    for i, col in enumerate(feature_cols):
        out[f"contrib__{col}"] = contributions[:, i]
    out = out.sort_values(["seller_id", "week"]).reset_index(drop=True)
    out.to_csv(FIG_DIR / "demo_test_predictions.csv", index=False)
    print(f"wrote {FIG_DIR / 'demo_test_predictions.csv'} ({len(out)} rows)")

    # --- per-seller GMV, reused exactly from policy.py ---
    gmv = per_seller_weekly_gmv(panel).rename("weekly_gmv").reset_index()
    gmv.columns = ["seller_id", "weekly_gmv"]
    gmv.to_csv(FIG_DIR / "demo_seller_gmv.csv", index=False)
    print(f"wrote {FIG_DIR / 'demo_seller_gmv.csv'} ({len(gmv)} rows)")

    # --- acceleration outcome per event, at each established FAR point ---
    # Mirrors phase4_calibrated_sweep.run_calibrated_sweep's own mechanism
    # exactly (score histories with the raw model, then calibrate the
    # "score" column post-hoc) -- reused here to get the per-event detail
    # that script only aggregated.
    sweep = pd.read_csv(FIG_DIR / "phase4_calibrated_sweep.csv")
    thresholds = dict(zip(sweep["false_alarm_rate"], sweep["threshold"]))

    histories, events = score_event_histories(fit, features_df)
    for hist in histories.values():
        if len(hist):
            hist["score"] = calibrator.predict(hist["score"].to_numpy())

    accel_rows = []
    for far in FAR_POINTS:
        threshold = thresholds[far]
        acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)
        for seller_id in events.index:
            hist = histories[seller_id]
            above = hist.loc[hist["score"] >= threshold, "week"]
            alarm_week = above.min() if len(above) else pd.NaT
            weeks = acc_weeks.loc[seller_id]
            if pd.isna(alarm_week):
                status = "never_flagged"
            elif weeks > 0:
                status = "beats_rule"
            else:
                status = "ties_rule"
            accel_rows.append(
                {
                    "seller_id": seller_id,
                    "far": far,
                    "event_week": events.loc[seller_id, "event_week"],
                    "model_alarm_week": alarm_week,
                    "acceleration_weeks": weeks,
                    "status": status,
                }
            )

    accel_df = pd.DataFrame(accel_rows)
    accel_df.to_csv(FIG_DIR / "demo_event_acceleration.csv", index=False)
    print(f"wrote {FIG_DIR / 'demo_event_acceleration.csv'} ({len(accel_df)} rows)")


if __name__ == "__main__":
    main()
