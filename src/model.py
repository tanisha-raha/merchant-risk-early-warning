"""Phase 2: discrete-time hazard model.

Logistic regression on the seller-week panel (person-period table), with
`tenure_weeks` as the time-in-study term, per the brief. No Cox, no
gradient-boosted survival here -- those are Phase 4 comparisons, deferred
on instruction so that phase gets the time budget instead.

Split: row-level time split (DECISIONS.md D10), not a seller-grouped
split -- a seller active on both sides of the cutoff contributes rows to
both train and test. See D10 for why the brief's original "no seller in
both" instruction doesn't transfer to a discrete-time hazard panel and was
corrected rather than followed literally.

Missingness: explicit indicator columns + zero-fill, not imputation
(DECISIONS.md D11) -- missing trend/accel/level is itself informative
("too young" or "currently inactive"), not noise to smooth over.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from distress_events import add_rolling_rates, compute_cessation_candidates, compute_eligibility
from features import FEATURE_COLUMNS, build_features
from panel import STUDY_END, build_panel

TEST_WEEKS = 26  # provisional width, DECISIONS.md D7
TEST_CUTOFF = STUDY_END - pd.Timedelta(weeks=TEST_WEEKS)

PRIMARY_N = 8
ROBUSTNESS_N = [4, 12]

# Shared missingness-indicator groups (DECISIONS.md D11): indicator name ->
# columns whose NaN-ness it reflects (indicator = 1 if ANY column in the
# group is NaN for that row, i.e. this family's derived stats are
# zero-filled here rather than real).
MISSING_GROUPS: dict[str, list[str]] = {
    "cancel_rate_history_missing": ["cancel_rate_level", "cancel_rate_trend", "cancel_rate_accel"],
    "ship_latency_history_missing": ["ship_latency_level", "ship_latency_trend", "ship_latency_accel"],
    "delivery_history_missing": [
        "deliver_latency_level", "deliver_latency_trend", "deliver_latency_accel",
        "late_share_level", "late_share_trend", "late_share_accel",
    ],
    "commitment_history_missing": [
        "aov_level", "aov_trend", "aov_accel",
        "first_time_buyer_share_level", "first_time_buyer_share_trend", "first_time_buyer_share_accel",
        "top_sku_revenue_share_level", "top_sku_revenue_share_trend", "top_sku_revenue_share_accel",
        "top_buyer_revenue_share_level", "top_buyer_revenue_share_trend", "top_buyer_revenue_share_accel",
        "volume_aov_interaction",
    ],
    "review_history_missing": ["review_score_level", "review_score_trend"],
}

# order_volume_trend/accel are zero-filled but get no indicator: missing
# only in a seller's first 1-2 weeks, fully redundant with tenure_weeks
# (already a feature) -- see DECISIONS.md D11.
ZERO_FILL_NO_INDICATOR = ["order_volume_trend", "order_volume_accel"]

MODEL_FEATURE_COLUMNS = (
    [c for c in FEATURE_COLUMNS if c != "category"]
    + ["category_freq"]
    + list(MISSING_GROUPS.keys())
)
assert len(MODEL_FEATURE_COLUMNS) == 37, len(MODEL_FEATURE_COLUMNS)


def add_missing_indicators_and_fill(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for indicator_col, cols in MISSING_GROUPS.items():
        df[indicator_col] = df[cols].isna().any(axis=1).astype(int)
    fillable = [c for cols in MISSING_GROUPS.values() for c in cols] + ZERO_FILL_NO_INDICATOR
    df[fillable] = df[fillable].fillna(0.0)
    return df


def fit_category_frequencies(train_category: pd.Series) -> pd.Series:
    """Fit on TRAIN only -- fitting on the full dataset would leak the
    test period's category distribution into a feature used to predict
    test-period rows."""
    return train_category.fillna("unknown").value_counts(normalize=True)


def apply_category_frequency(category: pd.Series, freq_map: pd.Series) -> pd.Series:
    # a category with zero train-period presence gets frequency 0 -- an
    # honest "never seen this in training" signal, not an error.
    return category.fillna("unknown").map(freq_map).fillna(0.0)


def build_labels(panel: pd.DataFrame, n_weeks: int) -> pd.DataFrame:
    panel_r = add_rolling_rates(panel)
    per_seller = compute_eligibility(panel_r)
    cess = compute_cessation_candidates(panel_r, per_seller, n_weeks)
    return cess[cess["eligible"]].copy()


def build_person_period_table(panel: pd.DataFrame, features_df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """One row per (seller, week) for every week an eligible seller is in
    the risk set: from tenure start through the week of its event (label=1
    there) or through STUDY_END if censored (label=0 throughout). Rows
    after an event are dropped -- once failed, a seller leaves the risk
    set, standard discrete-time hazard convention.
    """
    labels = labels.copy()
    labels["exit_week"] = labels["event_week"].where(labels["event_B"], STUDY_END)

    grid = panel[panel["seller_id"].isin(labels.index)][["seller_id", "week"]].copy()
    grid = grid.merge(
        labels[["exit_week", "event_B", "event_week"]], left_on="seller_id", right_index=True, how="inner"
    )
    grid = grid[grid["week"] <= grid["exit_week"]].copy()
    grid["label"] = (grid["event_B"] & (grid["week"] == grid["event_week"])).astype(int)

    table = grid.merge(features_df, on=["seller_id", "week"], how="left")
    return table


def time_split(table: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = table[table["week"] <= cutoff].copy()
    test = table[table["week"] > cutoff].copy()
    return train, test


def report_base_rate_drift(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    train_rate = train["label"].mean()
    test_rate = test["label"].mean()
    train_seller_event_rate = train.groupby("seller_id")["label"].max().mean()
    test_seller_event_rate = test.groupby("seller_id")["label"].max().mean()
    return {
        "train_rows": len(train),
        "test_rows": len(test),
        "train_row_event_rate": train_rate,
        "test_row_event_rate": test_rate,
        "row_rate_ratio_test_over_train": test_rate / train_rate if train_rate else float("nan"),
        "train_sellers": train["seller_id"].nunique(),
        "test_sellers": test["seller_id"].nunique(),
        "train_seller_event_rate": train_seller_event_rate,
        "test_seller_event_rate": test_seller_event_rate,
    }


def fit_model(train: pd.DataFrame) -> tuple[LogisticRegression, StandardScaler]:
    X = train[MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
    y = train["label"].to_numpy()
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=2000)
    clf.fit(scaler.transform(X), y)
    return clf, scaler


def predict(clf: LogisticRegression, scaler: StandardScaler, df: pd.DataFrame) -> np.ndarray:
    X = df[MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
    return clf.predict_proba(scaler.transform(X))[:, 1]


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        auc = float("nan")
    else:
        auc = roc_auc_score(y_true, y_pred)
    return {
        "n": len(y_true),
        "n_events": int(y_true.sum()),
        "auc": auc,
        "log_loss": log_loss(y_true, y_pred, labels=[0, 1]),
        "brier": brier_score_loss(y_true, y_pred),
        "mean_predicted": float(y_pred.mean()),
        "actual_rate": float(y_true.mean()),
    }


def straddler_check(test: pd.DataFrame, train: pd.DataFrame, y_pred_test: np.ndarray) -> dict:
    """Per your request: do test-window rows from sellers ALSO seen in
    train perform suspiciously better than rows from the 485 (at N=8)
    sellers who only ever appear in test? If so, the row-level split
    (D10) may be leaking something the no-fingerprint argument missed.
    """
    train_sellers = set(train["seller_id"])
    test = test.assign(_pred=y_pred_test)
    is_straddler = test["seller_id"].isin(train_sellers)

    out = {}
    groups = [
        ("straddler_rows (seller also in train)", is_straddler),
        ("test_only_rows (seller never in train)", ~is_straddler),
    ]
    for label, mask in groups:
        sub = test[mask]
        if len(sub) == 0 or sub["label"].nunique() < 2:
            out[label] = {"n": len(sub), "n_events": int(sub["label"].sum()), "auc": float("nan")}
            continue
        out[label] = evaluate(sub["label"].to_numpy(), sub["_pred"].to_numpy())
        out[label]["n_sellers"] = sub["seller_id"].nunique()
    return out


def run_for_n(panel: pd.DataFrame, features_df: pd.DataFrame, n_weeks: int) -> dict:
    labels = build_labels(panel, n_weeks)
    table = build_person_period_table(panel, features_df, labels)
    table = add_missing_indicators_and_fill(table)

    train, test = time_split(table, TEST_CUTOFF)
    drift = report_base_rate_drift(train, test)

    freq_map = fit_category_frequencies(train["category"])
    train = train.assign(category_freq=apply_category_frequency(train["category"], freq_map))
    test = test.assign(category_freq=apply_category_frequency(test["category"], freq_map))

    clf, scaler = fit_model(train)
    y_pred_train = predict(clf, scaler, train)
    y_pred_test = predict(clf, scaler, test)

    train_eval = evaluate(train["label"].to_numpy(), y_pred_train)
    test_eval = evaluate(test["label"].to_numpy(), y_pred_test)
    straddler = straddler_check(test, train, y_pred_test)

    return {
        "n_weeks": n_weeks,
        "n_eligible_sellers": len(labels),
        "n_events_total": int(labels["event_B"].sum()),
        "drift": drift,
        "train_eval": train_eval,
        "test_eval": test_eval,
        "straddler_check": straddler,
        "coef": dict(zip(MODEL_FEATURE_COLUMNS, clf.coef_[0])),
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    panel = build_panel(args.raw_dir)
    features_df = build_features(args.raw_dir)

    print(f"TEST_CUTOFF = {TEST_CUTOFF.date()} (last {TEST_WEEKS} weeks held out)\n")

    results = {}
    for n_weeks in [PRIMARY_N] + ROBUSTNESS_N:
        print(f"=== N={n_weeks} {'(primary)' if n_weeks == PRIMARY_N else '(robustness)'} ===")
        r = run_for_n(panel, features_df, n_weeks)
        results[n_weeks] = r

        d = r["drift"]
        print(
            f"eligible sellers: {r['n_eligible_sellers']}, events: {r['n_events_total']}\n"
            f"train: {d['train_rows']} rows / {d['train_sellers']} sellers, "
            f"row event rate {d['train_row_event_rate']:.4%}, seller event rate {d['train_seller_event_rate']:.2%}\n"
            f"test:  {d['test_rows']} rows / {d['test_sellers']} sellers, "
            f"row event rate {d['test_row_event_rate']:.4%}, seller event rate {d['test_seller_event_rate']:.2%}\n"
            f"test/train row-rate ratio: {d['row_rate_ratio_test_over_train']:.2f}x"
        )
        print(f"train fit: AUC={r['train_eval']['auc']:.3f}, Brier={r['train_eval']['brier']:.4f}")
        print(f"test fit:  AUC={r['test_eval']['auc']:.3f}, Brier={r['test_eval']['brier']:.4f}")
        for label, stats in r["straddler_check"].items():
            print(f"  {label}: n={stats['n']}, events={stats.get('n_events')}, AUC={stats['auc']}")
        print()

    out_path = Path("figures") / "phase2_model_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, (np.floating, np.integer)):
            return obj.item()
        if isinstance(obj, float) and np.isnan(obj):
            return None
        return obj

    with open(out_path, "w") as f:
        json.dump(_clean(results), f, indent=2, default=str)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
