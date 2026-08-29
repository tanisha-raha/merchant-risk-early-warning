"""Bounds the test-set threshold-selection concern raised after D21/D26:
Section 4/5's FAR thresholds are quantiles of the TEST set's own censored
rows, so the achieved test-set row-level FAR equals the nominal target
(1%/5%/10%) *by construction*, on that exact test set (DECISIONS.md D29).
That is not an independently-validated operating point.

This does not rebuild the pipeline around a third (validation) split --
that would mean re-deriving every Section 4/5/7 number against data none
of them have used before, a materially bigger job than the concern
warrants. Instead: derive thresholds from TRAIN negatives only (the
model already doesn't see TRAIN labels used any differently -- this adds
no new split, costs no train rows, and reuses exactly the population
definition `policy.score_censored_rows` already uses for TEST, just
computed over the TRAIN window instead) at the same three nominal FAR
targets, apply those thresholds UNCHANGED to the test set, and report
whatever row-level and seller-level FAR they actually achieve there --
honest numbers, not constructed ones. If train-derived and test-derived
land close together, that's the evidence the test-set selection concern
is small in practice, reported as a checked number, not an assertion.

Negative population, both windows: TEST_CUTOFF splits it, same
`event_B`-censored-seller definition (`_labels`, global across the whole
study -- a seller censored in TRAIN is censored in TEST too, since
`event_B` isn't computed per split) used everywhere else in this project.
Everything else -- the calibrator, the cost model, the acceleration
mechanics, the precision/recall accounting -- is reused verbatim from
`phase4_calibrated_sweep.py` and `phase4_precision_recall.py`, not
reimplemented.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from features import build_features
from model import PRIMARY_N, TEST_CUTOFF, predict, run_for_n, transform_features
from panel import build_panel
from phase4_calibrated_sweep import fit_calibrator
from policy import (
    acceleration_weeks_at_threshold,
    load_costs,
    per_seller_weekly_gmv,
    score_censored_rows,
    score_event_histories,
)

FAR_POINTS = [0.01, 0.05, 0.10]


def score_train_negative_rows(fit: dict, features_df: pd.DataFrame) -> pd.DataFrame:
    """Exact mirror of `policy.score_censored_rows`, TRAIN window instead
    of TEST: rows belonging to globally-censored sellers (never fail
    anywhere in the study, same `_labels`/`event_B` used throughout),
    restricted to `week <= TEST_CUTOFF`. This is the negative population
    the TRAIN-derived thresholds are quantiled from."""
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]
    censored = labels[~labels["event_B"]]
    rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] <= TEST_CUTOFF)
    ].copy()
    scored = transform_features(rows, freq_map)
    rows = rows.assign(score=predict(clf, scaler, scored, feature_cols))
    return rows


def economics_at_threshold(
    threshold: float,
    histories: dict,
    events: pd.DataFrame,
    event_gmv: pd.Series,
    censored_rows: pd.DataFrame,
    costs: dict,
    total_test_merchant_weeks: int,
) -> dict:
    """Same formulas as `phase4_calibrated_sweep.run_calibrated_sweep`'s
    per-FAR loop body, factored out so it can be evaluated at a threshold
    supplied from outside (TRAIN-derived) rather than only one derived
    internally from a TEST quantile. Not a new cost model -- the existing
    one, called with a different threshold."""
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)
    benefit_total = float((acc_weeks * event_gmv * reserve_pct * benefit_capture).sum())

    flagged = censored_rows["score"] >= threshold
    cost_total = float((censored_rows.loc[flagged, "weekly_gmv"] * reserve_pct * wc_rate).sum())

    net_delta = cost_total - benefit_total
    per_1000 = net_delta / total_test_merchant_weeks * 1000
    seller_far = flagged.groupby(censored_rows["seller_id"]).any().mean() if flagged.any() else 0.0

    return {
        "threshold": float(threshold),
        "n_events_accelerated": int((acc_weeks > 0).sum()),
        "n_events_total": len(events),
        "net_delta_cost_per_1000_merchant_weeks_reais": per_1000,
        "achieved_row_level_far": float(flagged.mean()),
        "achieved_seller_level_far": float(seller_far),
    }


def status_breakdown_at_threshold(threshold: float, histories: dict, events: pd.DataFrame) -> dict:
    """Exact same never_flagged/beats_rule/ties_rule classification as
    `prepare_demo_data.py` (which is what Section 3's 58%/36%/6% sentence
    and the demo's own banner are built from) -- reused here so the
    train-derived numbers are directly comparable to that sentence, not
    just to the aggregate net-cost figure."""
    n_never = n_beats = n_ties = 0
    accel_when_beats = []
    for seller_id in events.index:
        hist = histories[seller_id]
        above = hist.loc[hist["score"] >= threshold, "week"]
        alarm_week = above.min() if len(above) else pd.NaT
        event_week = events.loc[seller_id, "event_week"]
        if pd.isna(alarm_week):
            n_never += 1
        elif alarm_week < event_week:
            n_beats += 1
            accel_when_beats.append((event_week - alarm_week).days / 7)
        else:
            n_ties += 1
    n_total = len(events)
    return {
        "n_never_flagged": n_never,
        "n_beats_rule": n_beats,
        "n_ties_rule": n_ties,
        "pct_never_flagged": n_never / n_total,
        "pct_beats_rule": n_beats / n_total,
        "pct_ties_rule": n_ties / n_total,
        "median_acceleration_weeks_when_beats": float(np.median(accel_when_beats)) if accel_when_beats else float("nan"),
    }


def precision_recall_at_threshold(threshold: float, y_true: np.ndarray, scores: np.ndarray) -> dict:
    """Same TP/FP/FN accounting as `phase4_precision_recall.py`, factored
    out for reuse at an externally-supplied threshold."""
    flagged = scores >= threshold
    tp = int(((y_true == 1) & flagged).sum())
    fp = int(((y_true == 0) & flagged).sum())
    fn = int(((y_true == 1) & ~flagged).sum())
    n_flagged = tp + fp
    n_actual_events = int(y_true.sum())
    return {
        "n_flagged": n_flagged,
        "true_events_caught": tp,
        "false_positives": fp,
        "missed_events": fn,
        "precision": tp / n_flagged if n_flagged else float("nan"),
        "recall": tp / n_actual_events if n_actual_events else float("nan"),
    }


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)
    costs = load_costs()

    fit = run_for_n(panel, features_df, PRIMARY_N)
    calibrator = fit_calibrator(fit)
    drift = fit["drift"]

    print(
        f"row-level base rate, train: {drift['train_row_event_rate']:.4%}, "
        f"test: {drift['test_row_event_rate']:.4%} "
        f"({drift['row_rate_ratio_test_over_train']:.2f}x)\n"
    )

    # ---- TRAIN-derived thresholds ----
    train_neg = score_train_negative_rows(fit, features_df)
    train_neg_scores = calibrator.predict(train_neg["score"].to_numpy())
    train_thresholds = {far: float(np.quantile(train_neg_scores, 1 - far)) for far in FAR_POINTS}
    print(f"TRAIN negative population: {len(train_neg)} rows")
    for far, t in train_thresholds.items():
        print(f"  FAR={far:.0%} nominal -> TRAIN-derived threshold {t:.6f}")

    # ---- existing TEST-derived thresholds, reused not recomputed ----
    test_sweep = pd.read_csv("figures/phase4_calibrated_sweep.csv")
    test_thresholds = dict(zip(test_sweep["false_alarm_rate"], test_sweep["threshold"]))

    # ---- shared scoring, once, both threshold sets evaluated against it ----
    weekly_gmv = per_seller_weekly_gmv(panel)
    histories, events = score_event_histories(fit, features_df)
    for hist in histories.values():
        if len(hist):
            hist["score"] = calibrator.predict(hist["score"].to_numpy())
    event_gmv = events.index.to_series().map(weekly_gmv)

    censored_rows = score_censored_rows(fit, features_df)
    censored_rows = censored_rows.assign(weekly_gmv=censored_rows["seller_id"].map(weekly_gmv))
    censored_rows["score"] = calibrator.predict(censored_rows["score"].to_numpy())
    total_test_merchant_weeks = drift["test_rows"]

    clf, scaler, feature_cols = fit["_clf"], fit["_scaler"], fit["_feature_cols"]
    test_table = fit["_test"]
    y_true = test_table["label"].to_numpy()
    test_scores_calibrated = calibrator.predict(predict(clf, scaler, test_table, feature_cols))

    rows = []
    for far in FAR_POINTS:
        for origin, threshold in [("test_derived", test_thresholds[far]), ("train_derived", train_thresholds[far])]:
            econ = economics_at_threshold(
                threshold, histories, events, event_gmv, censored_rows, costs, total_test_merchant_weeks
            )
            pr = precision_recall_at_threshold(threshold, y_true, test_scores_calibrated)
            status = status_breakdown_at_threshold(threshold, histories, events)
            rows.append({"nominal_far": far, "threshold_origin": origin, **econ, **pr, **status})

    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", None)
    print()
    print(out.to_string(index=False))

    # ---- how much does the choice of origin actually move things ----
    pivot_net = out.pivot(index="nominal_far", columns="threshold_origin", values="net_delta_cost_per_1000_merchant_weeks_reais")
    pivot_row_far = out.pivot(index="nominal_far", columns="threshold_origin", values="achieved_row_level_far")
    print("\n=== net Δcost/1000mw: test-derived vs. train-derived ===")
    print(pivot_net.to_string())
    print("\n=== achieved row-level FAR: test-derived vs. train-derived (nominal is the index) ===")
    print(pivot_row_far.to_string())

    max_abs_net_diff = (pivot_net["train_derived"] - pivot_net["test_derived"]).abs().max()
    max_abs_far_diff = (pivot_row_far["train_derived"] - pivot_row_far.index.to_series()).abs().max()
    any_sign_flip = bool((np.sign(pivot_net["train_derived"]) != np.sign(pivot_net["test_derived"])).any())
    print(f"\nlargest |net Δcost| difference, train-derived vs. test-derived: R${max_abs_net_diff:.2f}/1000mw")
    print(f"largest |achieved row-level FAR - nominal|, train-derived: {max_abs_far_diff:.4%}")
    print(f"any sign flip in net Δcost between origins: {any_sign_flip}")

    out.to_csv("figures/phase4_train_derived_thresholds.csv", index=False)
    with open("figures/phase4_train_derived_thresholds.json", "w") as f:
        json.dump(
            {
                "rows": out.to_dict(orient="records"),
                "train_row_event_rate": drift["train_row_event_rate"],
                "test_row_event_rate": drift["test_row_event_rate"],
                "row_rate_ratio_test_over_train": drift["row_rate_ratio_test_over_train"],
                "max_abs_net_delta_diff_reais": float(max_abs_net_diff),
                "max_abs_row_far_diff": float(max_abs_far_diff),
                "any_sign_flip": any_sign_flip,
            },
            f,
            indent=2,
            default=str,
        )
    print("\nwrote figures/phase4_train_derived_thresholds.csv/.json")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x = np.arange(len(FAR_POINTS))
    width = 0.35
    ax1.bar(x - width / 2, pivot_net["test_derived"], width, label="test-derived (Section 4)", color="#4C72B0")
    ax1.bar(x + width / 2, pivot_net["train_derived"], width, label="train-derived (this check)", color="#C44E52")
    ax1.axhline(0, color="black", linewidth=1)
    ax1.set_xticks(x, [f"{f:.0%}" for f in FAR_POINTS])
    ax1.set_xlabel("nominal FAR")
    ax1.set_ylabel("net Δcost / 1,000 merchant-weeks (R$)")
    ax1.set_title("Economics: test-derived vs. train-derived threshold")
    ax1.legend()

    ax2.plot([f * 100 for f in FAR_POINTS], [f * 100 for f in FAR_POINTS], "k--", label="nominal = achieved")
    ax2.plot(
        [f * 100 for f in FAR_POINTS], pivot_row_far["test_derived"] * 100, marker="o", label="test-derived", color="#4C72B0"
    )
    ax2.plot(
        [f * 100 for f in FAR_POINTS],
        pivot_row_far["train_derived"] * 100,
        marker="s",
        label="train-derived",
        color="#C44E52",
    )
    ax2.set_xlabel("nominal FAR (%)")
    ax2.set_ylabel("achieved row-level FAR on test set (%)")
    ax2.set_title("Achieved vs. nominal FAR")
    ax2.legend()

    fig.tight_layout()
    fig.savefig("figures/phase4_train_derived_thresholds.png", dpi=150)
    print("wrote figures/phase4_train_derived_thresholds.png")


if __name__ == "__main__":
    main()
