"""Phase 4 addendum: a capacity check, not a model upgrade. Fits ONE
gradient-boosted model (sklearn's HistGradientBoostingClassifier,
essentially default hyperparameters -- only random_state set, nothing
tuned) on the exact same features, exact same row-level time split, and
exact same two evaluations already used for the logistic-regression
ablation (D18) and the honest advance-warning horizon (D14 sec.1).

The question is not whether it scores higher -- it's whether a learner
that can capture nonlinearities and interactions the logistic regression
can't finds signal the linear model missed on these features. If it lands
near the same numbers, that strengthens the ablation's negative result:
the ceiling is in the data/features, not the linearity of the model. If
it comes out meaningfully higher anywhere, that's reported as a finding
to discuss, not resolved here -- this model is not promoted to primary
regardless of the result.

No class-weighting, no tuning: the logistic regression wasn't given any
special imbalance handling either (model.fit_model just calls
LogisticRegression(max_iter=2000) on the raw label), so this stays an
apples-to-apples "same treatment" comparison, not a tuned model against
an untuned one.

Two evaluations, mirroring the two already reported for the linear model:
1. Pooled active-only task (D18): event-within-8-weeks, restricted to
   rows with a real current-week order count -- the direct ablation
   comparison. Linear model: train 0.714, test 0.678.
2. Honest advance-warning horizon (D14 sec.1): fit on the standard
   at-event-week task, scored at k=1/2/4/8 weeks before the seller's
   actual last order. Linear model: 0.584 / 0.586 / 0.534 / 0.555.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from features import build_features
from model import (
    MODEL_FEATURE_COLUMNS,
    PRIMARY_N,
    TEST_CUTOFF,
    add_missing_indicators_and_fill,
    apply_category_frequency,
    build_labels,
    build_person_period_table,
    evaluate,
    fit_category_frequencies,
    time_split,
)
from panel import build_panel
from phase2_lead_time_diagnostic import K_WEEKS, lead_time_auc
from phase4_ablation import HORIZON_WEEKS, build_corrected_active_only_table

# Reference numbers already reported for the linear model, printed
# alongside the GBM's for direct comparison -- not recomputed here.
LOGISTIC_ACTIVE_ONLY = {"train_auc": 0.714, "test_auc": 0.678}
LOGISTIC_LAST_ORDER_CURVE = {1: 0.584, 2: 0.586, 4: 0.534, 8: 0.555}


class _IdentityScaler:
    """GBMs (tree-based) don't need feature scaling. This no-op lets the
    existing model.predict() / lead_time_auc() machinery be reused
    unmodified rather than duplicated for a different classifier type."""

    def transform(self, X):
        return X


def fit_gbm(train: pd.DataFrame, feature_cols: list[str]) -> HistGradientBoostingClassifier:
    X = train[feature_cols].to_numpy(dtype=float)
    y = train["label"].to_numpy()
    clf = HistGradientBoostingClassifier(random_state=0)  # sklearn defaults otherwise, nothing tuned
    clf.fit(X, y)
    return clf


def predict_gbm(clf: HistGradientBoostingClassifier, df: pd.DataFrame, feature_cols: list[str]):
    X = df[feature_cols].to_numpy(dtype=float)
    return clf.predict_proba(X)[:, 1]


def run_standard_task_gbm(panel: pd.DataFrame, features_df: pd.DataFrame) -> dict:
    """Mirrors model.run_for_n exactly, GBM instead of logistic
    regression: same person-period table, same row-level split, same
    37-feature set, category frequencies fit on train only."""
    labels = build_labels(panel, PRIMARY_N)
    table = build_person_period_table(panel, features_df, labels)
    table = add_missing_indicators_and_fill(table)
    train, test = time_split(table, TEST_CUTOFF)

    freq_map = fit_category_frequencies(train["category"])
    train = train.assign(category_freq=apply_category_frequency(train["category"], freq_map))
    test = test.assign(category_freq=apply_category_frequency(test["category"], freq_map))

    clf = fit_gbm(train, MODEL_FEATURE_COLUMNS)
    y_pred_train = predict_gbm(clf, train, MODEL_FEATURE_COLUMNS)
    y_pred_test = predict_gbm(clf, test, MODEL_FEATURE_COLUMNS)

    return {
        "train_eval": evaluate(train["label"].to_numpy(), y_pred_train),
        "test_eval": evaluate(test["label"].to_numpy(), y_pred_test),
        "_clf": clf,
        "_scaler": _IdentityScaler(),
        "_feature_cols": MODEL_FEATURE_COLUMNS,
        "_freq_map": freq_map,
        "_labels": labels,
        "_train": train,
        "_test": test,
    }


def run_active_only_task_gbm(panel: pd.DataFrame, features_df: pd.DataFrame) -> dict:
    """Mirrors phase4_ablation.run_corrected_active_only exactly, GBM
    instead of logistic regression."""
    table = build_corrected_active_only_table(panel, features_df, PRIMARY_N, HORIZON_WEEKS)
    train, test = time_split(table, TEST_CUTOFF)
    train = train.assign(label=train["label_restricted"])
    test = test.assign(label=test["label_restricted"])

    freq_map = fit_category_frequencies(train["category"])
    train = train.assign(category_freq=apply_category_frequency(train["category"], freq_map))
    test = test.assign(category_freq=apply_category_frequency(test["category"], freq_map))

    clf = fit_gbm(train, MODEL_FEATURE_COLUMNS)
    y_pred_train = predict_gbm(clf, train, MODEL_FEATURE_COLUMNS)
    y_pred_test = predict_gbm(clf, test, MODEL_FEATURE_COLUMNS)

    return {
        "train_eval": evaluate(train["label"].to_numpy(), y_pred_train),
        "test_eval": evaluate(test["label"].to_numpy(), y_pred_test),
        "train_rows": len(train),
        "train_positives": int(train["label"].sum()),
        "test_rows": len(test),
        "test_positives": int(test["label"].sum()),
    }


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    print("=== capacity check 1: pooled active-only task (mirrors D18) ===")
    active_fit = run_active_only_task_gbm(panel, features_df)
    gbm_active_train = active_fit["train_eval"]["auc"]
    gbm_active_test = active_fit["test_eval"]["auc"]
    print(
        f"GBM:      train AUC={gbm_active_train:.3f}  test AUC={gbm_active_test:.3f}  "
        f"(n_train={active_fit['train_rows']}, pos={active_fit['train_positives']}; "
        f"n_test={active_fit['test_rows']}, pos={active_fit['test_positives']})"
    )
    print(
        f"logistic: train AUC={LOGISTIC_ACTIVE_ONLY['train_auc']:.3f}  "
        f"test AUC={LOGISTIC_ACTIVE_ONLY['test_auc']:.3f}  (D18, full 37-feature tier)"
    )

    print("\n=== capacity check 2: honest advance-warning horizon (mirrors D14 sec.1) ===")
    standard_fit = run_standard_task_gbm(panel, features_df)
    print(
        f"GBM at-event-week: train AUC={standard_fit['train_eval']['auc']:.3f} "
        f"test AUC={standard_fit['test_eval']['auc']:.3f}"
    )
    curve = lead_time_auc(standard_fit, K_WEEKS, features_df, anchor_col="last_active_week")
    print("last-order-anchored curve:")
    for k, stats in curve.items():
        print(
            f"  k={k:>2}: GBM AUC={stats['auc']:.3f} (n={stats['n_events_scored']})   "
            f"logistic AUC={LOGISTIC_LAST_ORDER_CURVE[k]:.3f}"
        )

    out = {
        "active_only_task": {
            "gbm_train_auc": gbm_active_train,
            "gbm_test_auc": gbm_active_test,
            "logistic_train_auc": LOGISTIC_ACTIVE_ONLY["train_auc"],
            "logistic_test_auc": LOGISTIC_ACTIVE_ONLY["test_auc"],
        },
        "standard_task_at_event_week": {
            "gbm_train_auc": standard_fit["train_eval"]["auc"],
            "gbm_test_auc": standard_fit["test_eval"]["auc"],
        },
        "last_order_anchored_curve_gbm": curve,
        "last_order_anchored_curve_logistic_reference": LOGISTIC_LAST_ORDER_CURVE,
    }
    out_path = Path("figures") / "phase4_gbm_capacity_check.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
