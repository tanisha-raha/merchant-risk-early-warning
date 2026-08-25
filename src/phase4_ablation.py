"""Phase 4, priority 2: the ablation -- the direct test of the brief's
stated hypothesis ("trend and acceleration predict distress better than
levels"). Current evidence (D13/D14) says the model shows no genuine
multi-week advance warning at all, which would already suggest trend/
accel aren't earning their keep -- this makes it precise: three nested
feature tiers, evaluated the same two ways used throughout Phase 2/4 (at-
event-week AUC, and the last-order-anchored lead-time curve, the
methodologically clean one per D14 sec.1).

Tiers (nested, nothing removed from lower tiers):
  1. levels only        -- level columns + tenure_weeks + category_freq
  2. levels + trend      -- tier 1 + trend columns + volume_aov_interaction
                            + the 5 missingness indicators (D11; these
                            primarily flag trend/accel unavailability, so
                            grouped with trend, not levels)
  3. levels + trend + accel -- tier 2 + accel columns = the full 37-column
                            model used throughout Phase 2/3

Plus the corrected active-only test D14 sec.3 flagged as needed: the
original attempt filtered on order_volume_level (a trailing POOLED
average) and got contaminated by 2-3 weeks of post-silence echo. Fixed
here by filtering on the RAW current week's order count (panel.py's
n_orders, safe to reuse for this restriction -- not as a predictive
feature, just to define "was still genuinely trading that exact week")
and by anchoring the label window to weeks BEFORE last_active_week
(matching D14 sec.1's clean anchor) rather than before event_week.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from features import build_features
from model import (
    MISSING_GROUPS,
    MODEL_FEATURE_COLUMNS,
    PRIMARY_N,
    TEST_CUTOFF,
    apply_category_frequency,
    build_labels,
    build_person_period_table,
    evaluate,
    fit_category_frequencies,
    fit_model,
    predict,
    run_for_n,
    time_split,
)
from model import add_missing_indicators_and_fill as _add_missing_indicators_and_fill
from panel import build_panel
from phase2_lead_time_diagnostic import K_WEEKS, lead_time_auc

LEVEL_COLS = [c for c in MODEL_FEATURE_COLUMNS if c.endswith("_level")] + ["tenure_weeks", "category_freq"]
TREND_COLS = [c for c in MODEL_FEATURE_COLUMNS if c.endswith("_trend")] + [
    "volume_aov_interaction",
    *MISSING_GROUPS.keys(),
]
ACCEL_COLS = [c for c in MODEL_FEATURE_COLUMNS if c.endswith("_accel")]

TIER_1_LEVELS = LEVEL_COLS
TIER_2_LEVELS_TREND = LEVEL_COLS + TREND_COLS
TIER_3_LEVELS_TREND_ACCEL = LEVEL_COLS + TREND_COLS + ACCEL_COLS

assert set(TIER_3_LEVELS_TREND_ACCEL) == set(MODEL_FEATURE_COLUMNS), "tiers must reconstruct the full column set"
assert len(TIER_3_LEVELS_TREND_ACCEL) == len(MODEL_FEATURE_COLUMNS)

TIERS = {
    "1_levels_only": TIER_1_LEVELS,
    "2_levels_plus_trend": TIER_2_LEVELS_TREND,
    "3_levels_trend_accel": TIER_3_LEVELS_TREND_ACCEL,
}

HORIZON_WEEKS = 8  # matches primary N, for the corrected active-only test


def run_ablation(panel: pd.DataFrame, features_df: pd.DataFrame) -> dict:
    results = {}
    for tier_name, cols in TIERS.items():
        fit = run_for_n(panel, features_df, PRIMARY_N, feature_cols=cols)
        curve = lead_time_auc(fit, K_WEEKS, features_df, anchor_col="last_active_week")
        results[tier_name] = {
            "n_features": len(cols),
            "at_event_week_test_auc": fit["test_eval"]["auc"],
            "at_event_week_test_brier": fit["test_eval"]["brier"],
            "last_order_anchored_curve": curve,
        }
    return results


def build_corrected_active_only_table(
    panel: pd.DataFrame, features_df: pd.DataFrame, n_weeks: int, horizon_weeks: int
) -> pd.DataFrame:
    labels = build_labels(panel, n_weeks)
    table = build_person_period_table(panel, features_df, labels)
    table = table.merge(panel[["seller_id", "week", "n_orders"]], on=["seller_id", "week"], how="left")

    last_active = (
        panel[panel["n_orders"] > 0].groupby("seller_id")["week"].max().rename("last_active_week")
    )
    table = table.merge(last_active, on="seller_id", how="left")

    weeks_before_last_order = (table["last_active_week"] - table["week"]).dt.days / 7
    table["label_restricted"] = (
        table["event_B"] & (weeks_before_last_order >= 0) & (weeks_before_last_order < horizon_weeks)
    ).astype(int)

    active = table[table["n_orders"] > 0].copy()  # RAW current-week count, not the pooled level -- the fix
    active = _add_missing_indicators_and_fill(active)
    return active


def run_corrected_active_only(
    panel: pd.DataFrame, features_df: pd.DataFrame, feature_cols: list[str] = MODEL_FEATURE_COLUMNS
) -> dict:
    table = build_corrected_active_only_table(panel, features_df, PRIMARY_N, HORIZON_WEEKS)

    train, test = time_split(table, TEST_CUTOFF)
    train = train.assign(label=train["label_restricted"])
    test = test.assign(label=test["label_restricted"])

    freq_map = fit_category_frequencies(train["category"])
    train = train.assign(category_freq=apply_category_frequency(train["category"], freq_map))
    test = test.assign(category_freq=apply_category_frequency(test["category"], freq_map))

    clf, scaler = fit_model(train, feature_cols)
    y_pred_train = predict(clf, scaler, train, feature_cols)
    y_pred_test = predict(clf, scaler, test, feature_cols)

    train_eval = evaluate(train["label"].to_numpy(), y_pred_train)
    test_eval = evaluate(test["label"].to_numpy(), y_pred_test)

    return {
        "n_features": len(feature_cols),
        "horizon_weeks": HORIZON_WEEKS,
        "active_rows_total": len(table),
        "train_rows": len(train),
        "train_positives": int(train["label"].sum()),
        "test_rows": len(test),
        "test_positives": int(test["label"].sum()),
        "train_eval": train_eval,
        "test_eval": test_eval,
    }


def run_corrected_active_only_by_tier(panel: pd.DataFrame, features_df: pd.DataFrame) -> dict:
    return {tier_name: run_corrected_active_only(panel, features_df, cols) for tier_name, cols in TIERS.items()}


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    print("=== ablation: levels vs. levels+trend vs. levels+trend+accel ===")
    print(f"tier sizes: {[(k, len(v)) for k, v in TIERS.items()]}\n")

    ablation = run_ablation(panel, features_df)
    for tier_name, r in ablation.items():
        print(f"--- {tier_name} ({r['n_features']} features) ---")
        print(f"  at-event-week test AUC={r['at_event_week_test_auc']:.3f}, Brier={r['at_event_week_test_brier']:.4f}")
        print("  last-order-anchored lead-time curve:")
        for k, stats in r["last_order_anchored_curve"].items():
            print(f"    k={k:>2}: AUC={stats['auc']:.3f} (n={stats['n_events_scored']})")
        print()

    print("=== corrected active-only test (raw current-week order count, last-active-week anchored) ===")
    print("run per tier -- this IS the direct hypothesis test the ablation is for\n")
    active_by_tier = run_corrected_active_only_by_tier(panel, features_df)
    for tier_name, r in active_by_tier.items():
        print(f"--- {tier_name} ({r['n_features']} features) ---")
        print(f"  train: n={r['train_rows']}, positives={r['train_positives']}")
        print(f"  test:  n={r['test_rows']}, positives={r['test_positives']}")
        print(f"  train fit: AUC={r['train_eval']['auc']:.3f}, Brier={r['train_eval']['brier']:.4f}")
        print(f"  test fit:  AUC={r['test_eval']['auc']:.3f}, Brier={r['test_eval']['brier']:.4f}")
        print()

    out = {"ablation": ablation, "corrected_active_only_by_tier": active_by_tier}
    out_path = Path("figures") / "phase4_ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
