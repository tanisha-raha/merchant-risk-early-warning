"""Phase 2 diagnostic: the operative baseline for "does the model predict
distress in advance" isn't chance (D13) -- it's the N=8 silence rule
itself, which is what a payments team would actually deploy without a
model. This script asks the comparison that matters: at a fixed row-level
false-alarm rate (set on the test-period censored-row pool, same
population used throughout Phase 2), how many weeks earlier does the
model's score cross an alarm threshold than the rule fires (which is
always exactly at event_week, by construction -- the rule is
deterministic)?

For each test-period event: scan every out-of-sample week in that seller's
history from TEST_CUTOFF+1 through event_week, score it with the
already-fitted primary model, and find the first week the score crosses
the threshold ("model alarm week"). Acceleration = event_week -
model_alarm_week, in weeks. An event the model never crosses the
threshold for (before or at event_week) gets no acceleration value --
reported as its own category, not silently dropped from an average.

Also reports the SELLER-level false-alarm rate this produces (fraction of
censored sellers flagged at least once anywhere in their test-period
history) alongside the row-level rate the threshold was actually set on --
these differ, and both matter operationally.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from features import build_features
from model import PRIMARY_N, TEST_CUTOFF, predict, run_for_n, transform_features
from panel import STUDY_END, build_panel

FALSE_ALARM_RATES = [0.01, 0.05, 0.10]
PRIMARY_FAR = 0.05


def compute_threshold(neg_scores: np.ndarray, false_alarm_rate: float) -> float:
    """Row-level: the score above which exactly `false_alarm_rate` of the
    censored-row pool would be (falsely) flagged."""
    return float(np.quantile(neg_scores, 1 - false_alarm_rate))


def acceleration_for_events(
    fit: dict, features_df: pd.DataFrame, threshold: float
) -> pd.DataFrame:
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]

    events = labels[labels["event_B"] & (labels["event_week"] > TEST_CUTOFF)].copy()

    rows = []
    for seller_id, row in events.iterrows():
        event_week = row["event_week"]
        history = features_df[
            (features_df["seller_id"] == seller_id)
            & (features_df["week"] > TEST_CUTOFF)
            & (features_df["week"] <= event_week)
        ].sort_values("week")
        if history.empty:
            rows.append({"seller_id": seller_id, "event_week": event_week, "model_alarm_week": pd.NaT, "n_weeks_scanned": 0})
            continue

        scored = transform_features(history, freq_map)
        scores = predict(clf, scaler, scored, feature_cols)
        above = history["week"].to_numpy()[scores >= threshold]

        alarm_week = pd.Timestamp(above.min()) if len(above) else pd.NaT
        rows.append(
            {
                "seller_id": seller_id,
                "event_week": event_week,
                "model_alarm_week": alarm_week,
                "n_weeks_scanned": len(history),
            }
        )

    out = pd.DataFrame(rows)
    out["acceleration_weeks"] = (out["event_week"] - out["model_alarm_week"]).dt.days / 7
    return out


def seller_level_false_alarm_rate(fit: dict, features_df: pd.DataFrame, threshold: float) -> dict:
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]
    censored = labels[~labels["event_B"]]

    rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    scored = transform_features(rows, freq_map)
    scores = predict(clf, scaler, scored, feature_cols)
    rows = rows.assign(_score=scores)

    flagged_at_least_once = rows.groupby("seller_id")["_score"].max() >= threshold
    return {
        "n_censored_sellers": len(censored),
        "n_flagged_at_least_once": int(flagged_at_least_once.sum()),
        "seller_level_false_alarm_rate": float(flagged_at_least_once.mean()),
    }


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    print(f"TEST_CUTOFF = {TEST_CUTOFF.date()}, STUDY_END = {STUDY_END.date()}, primary N={PRIMARY_N}\n")

    fit = run_for_n(panel, features_df, PRIMARY_N)
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]

    censored = labels[~labels["event_B"]]
    neg_rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    neg_rows_t = transform_features(neg_rows, freq_map)
    neg_scores = predict(clf, scaler, neg_rows_t, feature_cols)

    results = {}
    for far in FALSE_ALARM_RATES:
        threshold = compute_threshold(neg_scores, far)
        acc = acceleration_for_events(fit, features_df, threshold)
        seller_far = seller_level_false_alarm_rate(fit, features_df, threshold)

        n_events = len(acc)
        n_ever_flagged = acc["model_alarm_week"].notna().sum()
        earlier = acc[acc["model_alarm_week"].notna() & (acc["acceleration_weeks"] > 0)]
        at_confirmation_only = acc[
            acc["model_alarm_week"].notna() & (acc["acceleration_weeks"] == 0)
        ]

        print(f"=== row-level false-alarm rate = {far:.0%} (threshold={threshold:.5f}) ===")
        print(f"  seller-level false-alarm rate at this threshold: {seller_far['seller_level_false_alarm_rate']:.1%} "
              f"({seller_far['n_flagged_at_least_once']}/{seller_far['n_censored_sellers']} censored sellers "
              f"flagged at least once in the test period)")
        n_never = n_events - n_ever_flagged
        print(f"  events: {n_events} total")
        print(f"  never crosses threshold by event_week: {n_never} ({n_never / n_events:.1%})")
        print(f"  crosses threshold, but not before event_week (0 weeks early): {len(at_confirmation_only)}")
        print(
            f"  crosses threshold STRICTLY BEFORE event_week (genuine acceleration): "
            f"{len(earlier)} ({len(earlier) / n_events:.1%})"
        )
        if len(earlier):
            print(
                f"    acceleration (weeks earlier than the rule), among those: "
                f"median={earlier['acceleration_weeks'].median():.1f}, "
                f"p25={earlier['acceleration_weeks'].quantile(.25):.1f}, "
                f"p75={earlier['acceleration_weeks'].quantile(.75):.1f}, "
                f"max={earlier['acceleration_weeks'].max():.1f}"
            )
        print()

        results[far] = {
            "threshold": threshold,
            "seller_level_false_alarm_rate": seller_far,
            "n_events": n_events,
            "n_never_flagged_by_event_week": int(n_events - n_ever_flagged),
            "n_flagged_at_confirmation_only": int(len(at_confirmation_only)),
            "n_flagged_earlier": int(len(earlier)),
            "acceleration_weeks_median": float(earlier["acceleration_weeks"].median()) if len(earlier) else None,
            "acceleration_weeks_p25": float(earlier["acceleration_weeks"].quantile(.25)) if len(earlier) else None,
            "acceleration_weeks_p75": float(earlier["acceleration_weeks"].quantile(.75)) if len(earlier) else None,
            "acceleration_weeks_max": float(earlier["acceleration_weeks"].max()) if len(earlier) else None,
        }

    out_path = Path("figures") / "phase2_acceleration_vs_rule.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
