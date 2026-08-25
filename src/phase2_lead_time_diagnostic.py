"""Diagnostic only -- does NOT change model.py or any label/decision.
Answers the question raised by DECISIONS.md D12: is the discrete-time
hazard model's 0.89-0.97 test AUC genuine early warning, or mostly
detection of sellers who have already gone quiet?

Two checks, both run on the primary N=8 model:

1. Lead-time AUC. For k in {1, 2, 4, 8} weeks: take the prediction row
   exactly k weeks before each TEST-PERIOD event's confirmation date
   (event_week - k), score it with the already-fitted model, and compute
   AUC against a FIXED negative pool (every test-period row from censored
   sellers). The negative pool is the same across all k, so only the
   positive side changes -- if AUC collapses toward 0.5 as k grows, a
   soon-to-fail seller looks statistically normal until shortly before it
   fails, i.e. the model is mostly a "quiet detector," not an early-warning
   system. Both the prediction row and the events used are restricted to
   week > TEST_CUTOFF, so this is strictly out-of-sample -- no row used
   here was part of fitting the model.

2. Mechanism check. Refit with the order_volume family (level, trend,
   accel -- the direct "how many orders recently" signal) dropped
   entirely, rerun the same k-week curve. If it holds up without
   order_volume, the early-warning signal lives elsewhere (quality,
   latency, concentration trends). If it collapses to near the same shape
   as check 1 minus a fixed offset, order_volume was carrying most of it.

   Caveat, stated before the numbers, not after: several *other* feature
   families are zero-filled with a shared "this family's stats are
   missing" indicator when a seller had zero orders in the trailing
   window (DECISIONS.md D11 -- commitment_history_missing covers aov,
   first_time_buyer_share, and both concentration features; those
   indicators fire exactly when order_volume is 0 too). Those indicator
   columns stay in the ablated model, so this is not a fully clean
   "remove all traces of volume" cut -- it removes the *direct* volume
   signal, not every indirect trace of it. Reported as a limitation of
   this diagnostic, not fixed here per instruction.

No model is refit differently from model.py's own fitting procedure; this
script only adds a scoring pass over different (seller, week) rows using
the model.py-fitted classifiers, plus one additional classifier fit with
a reduced feature list, using the exact same fit_model()/predict() code.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from features import build_features
from model import (
    MODEL_FEATURE_COLUMNS,
    PRIMARY_N,
    TEST_CUTOFF,
    predict,
    run_for_n,
    transform_features,
)
from panel import build_panel

K_WEEKS = [1, 2, 4, 8]
VOLUME_COLS = ["order_volume_level", "order_volume_trend", "order_volume_accel"]
NO_VOLUME_FEATURE_COLUMNS = [c for c in MODEL_FEATURE_COLUMNS if c not in VOLUME_COLS]


def lead_time_auc(fit: dict, k_weeks_list: list[int], features_df: pd.DataFrame) -> dict:
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]

    events = labels[labels["event_B"] & (labels["event_week"] > TEST_CUTOFF)]
    censored = labels[~labels["event_B"]]

    neg_rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    neg_rows = transform_features(neg_rows, freq_map)
    neg_scores = predict(clf, scaler, neg_rows, feature_cols)

    out = {}
    for k in k_weeks_list:
        target_week = events["event_week"] - pd.Timedelta(weeks=k)
        lookup = pd.DataFrame({"seller_id": events.index, "week": target_week.to_numpy()})
        lookup = lookup[lookup["week"] > TEST_CUTOFF]  # keep the prediction row strictly out-of-sample too

        pos_rows = lookup.merge(features_df, on=["seller_id", "week"], how="inner")
        pos_rows = transform_features(pos_rows, freq_map)
        pos_scores = predict(clf, scaler, pos_rows, feature_cols)

        if len(pos_scores) >= 5:
            y_true = np.concatenate([np.ones(len(pos_scores)), np.zeros(len(neg_scores))])
            y_score = np.concatenate([pos_scores, neg_scores])
            auc = float(roc_auc_score(y_true, y_score))
        else:
            auc = float("nan")

        out[k] = {
            "n_events_available": int(len(events)),
            "n_events_scored": int(len(pos_scores)),
            "n_negative_rows": int(len(neg_scores)),
            "auc": auc,
            "mean_positive_score": float(pos_scores.mean()) if len(pos_scores) else None,
            "mean_negative_score": float(neg_scores.mean()),
        }
    return out


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    print(f"TEST_CUTOFF = {TEST_CUTOFF.date()}, primary N={PRIMARY_N}\n")

    print("=== full model (all 37 features) ===")
    full_fit = run_for_n(panel, features_df, PRIMARY_N)
    full_curve = lead_time_auc(full_fit, K_WEEKS, features_df)
    for k, stats in full_curve.items():
        print(
            f"k={k:>2} weeks before event: AUC={stats['auc']:.3f}  "
            f"(scored {stats['n_events_scored']}/{stats['n_events_available']} events vs "
            f"{stats['n_negative_rows']} censored rows; mean score pos={stats['mean_positive_score']:.4f} "
            f"neg={stats['mean_negative_score']:.4f})"
        )

    print(f"\n=== order_volume excluded ({len(NO_VOLUME_FEATURE_COLUMNS)} features) ===")
    no_volume_fit = run_for_n(panel, features_df, PRIMARY_N, feature_cols=NO_VOLUME_FEATURE_COLUMNS)
    no_volume_curve = lead_time_auc(no_volume_fit, K_WEEKS, features_df)
    for k, stats in no_volume_curve.items():
        print(
            f"k={k:>2} weeks before event: AUC={stats['auc']:.3f}  "
            f"(scored {stats['n_events_scored']}/{stats['n_events_available']} events vs "
            f"{stats['n_negative_rows']} censored rows; mean score pos={stats['mean_positive_score']:.4f} "
            f"neg={stats['mean_negative_score']:.4f})"
        )

    print(f"\nfull-model test AUC (from D12, at-event-week): {full_fit['test_eval']['auc']:.3f}")
    print(f"no-volume test AUC (at-event-week): {no_volume_fit['test_eval']['auc']:.3f}")

    out = {
        "test_cutoff": str(TEST_CUTOFF.date()),
        "primary_n": PRIMARY_N,
        "full_model_at_event_week_auc": full_fit["test_eval"]["auc"],
        "no_volume_at_event_week_auc": no_volume_fit["test_eval"]["auc"],
        "full_model_lead_time_curve": full_curve,
        "no_volume_lead_time_curve": no_volume_curve,
    }
    out_path = Path("figures") / "phase2_lead_time_diagnostic.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
