"""Phase 2 diagnostic, timeboxed (per instruction, no further follow-ups
without discussion): does the core hypothesis -- trend/acceleration
predicts distress before a seller goes quiet -- hold up when quietness
itself is removed from the training population entirely?

Restriction: only rows with order_volume_level > 0 (non-zero orders in
the trailing 4 weeks -- i.e. the seller is still genuinely, visibly
trading) are used, for BOTH classes, in both train and test. This is a
harder cut than DECISIONS.md D13's ablation, which only removed the
order_volume FEATURE while still training on rows where the seller had
already gone silent. Here, no row in the population has gone silent.

Label change this forces, stated up front: the original label (1 only at
the exact event/confirmation week) is unusable under this restriction --
that week always has order_volume_level == 0 by construction of pure
cessation, so filtering to volume > 0 would leave zero positive examples.
Redefined as: label = 1 if the row is within H=8 weeks (matches N=8)
BEFORE a confirmed event, 0 otherwise (censored sellers' active rows, or
event-sellers' active rows more than H weeks before their event). H=8 is
the one arbitrary choice here, picked to match the primary N for
consistency, not tuned.

If AUC holds up (well above 0.5) under this restriction, trend/
acceleration features carry genuine multi-week predictive signal
independent of quietness. If it sits at chance, the core hypothesis gets
no support from the current feature set on this cut of the data --
reported plainly, not fixed here.
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
    apply_category_frequency,
    build_labels,
    build_person_period_table,
    evaluate,
    fit_category_frequencies,
    fit_model,
    predict,
    time_split,
)
from model import add_missing_indicators_and_fill as _add_missing_indicators_and_fill
from panel import build_panel

HORIZON_WEEKS = 8


def build_restricted_table(panel: pd.DataFrame, features_df: pd.DataFrame, n_weeks: int, horizon_weeks: int) -> pd.DataFrame:
    labels = build_labels(panel, n_weeks)
    table = build_person_period_table(panel, features_df, labels)

    weeks_to_event = (table["event_week"] - table["week"]).dt.days / 7
    table["label_restricted"] = (
        table["event_B"] & (weeks_to_event >= 1) & (weeks_to_event <= horizon_weeks)
    ).astype(int)

    active = table[table["order_volume_level"] > 0].copy()
    active = _add_missing_indicators_and_fill(active)
    return active


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    print(f"TEST_CUTOFF = {TEST_CUTOFF.date()}, primary N={PRIMARY_N}, horizon H={HORIZON_WEEKS}\n")

    table = build_restricted_table(panel, features_df, PRIMARY_N, HORIZON_WEEKS)
    print(f"rows with order_volume_level > 0: {len(table)} (of a full person-period table well over 45k)")
    pos_rate = table["label_restricted"].mean()
    print(f"positive rate (event within next {HORIZON_WEEKS} weeks, still actively trading): {pos_rate:.4%}")

    train, test = time_split(table, TEST_CUTOFF)
    train = train.rename(columns={"label": "label_at_event_week"}).rename(columns={"label_restricted": "label"})
    test = test.rename(columns={"label": "label_at_event_week"}).rename(columns={"label_restricted": "label"})

    print(f"train: {len(train)} rows, {int(train['label'].sum())} positive")
    print(f"test:  {len(test)} rows, {int(test['label'].sum())} positive")

    freq_map = fit_category_frequencies(train["category"])
    train = train.assign(category_freq=apply_category_frequency(train["category"], freq_map))
    test = test.assign(category_freq=apply_category_frequency(test["category"], freq_map))

    clf, scaler = fit_model(train, MODEL_FEATURE_COLUMNS)
    y_pred_train = predict(clf, scaler, train, MODEL_FEATURE_COLUMNS)
    y_pred_test = predict(clf, scaler, test, MODEL_FEATURE_COLUMNS)

    train_eval = evaluate(train["label"].to_numpy(), y_pred_train)
    test_eval = evaluate(test["label"].to_numpy(), y_pred_test)

    print(f"\ntrain fit: AUC={train_eval['auc']:.3f}, Brier={train_eval['brier']:.4f}, n_events={train_eval['n_events']}")
    print(f"test fit:  AUC={test_eval['auc']:.3f}, Brier={test_eval['brier']:.4f}, n_events={test_eval['n_events']}")

    # near (1-4 weeks out) vs far (5-8 weeks out) breakdown, among test rows,
    # scored with the same fitted model -- same restricted population, just
    # split by how close a positive row is to its event.
    test_scored = test.assign(_pred=y_pred_test)
    weeks_to_event_test = (test["event_week"] - test["week"]).dt.days / 7
    near_pos = test_scored[(test["label"] == 1) & (weeks_to_event_test <= 4)]
    far_pos = test_scored[(test["label"] == 1) & (weeks_to_event_test > 4)]
    neg = test_scored[test_scored["label"] == 0]

    for name, pos in [("near (1-4 weeks before event)", near_pos), ("far (5-8 weeks before event)", far_pos)]:
        if len(pos) >= 5 and len(neg) >= 5:
            y_true = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
            y_score = np.concatenate([pos["_pred"].to_numpy(), neg["_pred"].to_numpy()])
            auc = roc_auc_score(y_true, y_score)
            print(f"  {name}: n={len(pos)}, AUC vs all test negatives = {auc:.3f}")
        else:
            print(f"  {name}: n={len(pos)}, too few to score")

    out = {
        "primary_n": PRIMARY_N,
        "horizon_weeks": HORIZON_WEEKS,
        "train_rows": len(train),
        "train_positives": int(train["label"].sum()),
        "test_rows": len(test),
        "test_positives": int(test["label"].sum()),
        "train_eval": train_eval,
        "test_eval": test_eval,
    }
    out_path = Path("figures") / "phase2_active_only_ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
