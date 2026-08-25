"""Phase 4, timeboxed follow-up: does the FAR-sweep economic result (D16)
survive once the top-decile over-confidence found in D19 is corrected?

D19: the model's highest-risk decile over-states risk by ~2x (predicted
0.080 vs. actual 0.039). Isotonic regression fit on TRAIN predictions and
labels ONLY (fitting on train+test would leak test-period label
information into the calibration used to score test-period rows).
Applied post-hoc to the exact same raw scores policy.py already computes
-- nothing else in the pipeline changes, and config/costs.yaml is
untouched, per instruction.

Mechanical note, checked here rather than assumed: isotonic regression is
a monotonic transform. Phase 3's cost/benefit accounting is built entirely
from REALIZED outcomes (a censored row that crosses threshold is an
unambiguous false alarm; an event row's acceleration is measured against
its actual confirmation date) -- the model's score is used only to RANK
rows against a quantile-defined threshold, never to weight cost/benefit by
the score's own magnitude. A monotonic recalibration preserves rank order,
so in the limit of no ties it cannot change which rows clear a
quantile-defined threshold, and therefore cannot change the sweep. Real
data has ties (isotonic fits are step functions with flat regions), so
this is checked empirically below rather than assumed to be an exact
no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from features import build_features
from model import PRIMARY_N, predict, run_for_n
from panel import build_panel
from policy import (
    FAR_SWEEP,
    acceleration_weeks_at_threshold,
    load_costs,
    per_seller_weekly_gmv,
    score_censored_rows,
    score_event_histories,
)


def fit_calibrator(fit: dict) -> IsotonicRegression:
    clf, scaler, feature_cols = fit["_clf"], fit["_scaler"], fit["_feature_cols"]
    train = fit["_train"]
    raw_scores = predict(clf, scaler, train, feature_cols)
    y_true = train["label"].to_numpy()
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_scores, y_true)
    return iso


def run_calibrated_sweep(
    fit: dict, features_df: pd.DataFrame, panel: pd.DataFrame, costs: dict, calibrator: IsotonicRegression
) -> pd.DataFrame:
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    weekly_gmv = per_seller_weekly_gmv(panel)

    histories, events = score_event_histories(fit, features_df)
    for hist in histories.values():
        if len(hist):
            hist["score"] = calibrator.predict(hist["score"].to_numpy())
    event_gmv = events.index.to_series().map(weekly_gmv)

    censored_rows = score_censored_rows(fit, features_df)
    censored_rows = censored_rows.assign(weekly_gmv=censored_rows["seller_id"].map(weekly_gmv))
    censored_rows["score"] = calibrator.predict(censored_rows["score"].to_numpy())
    neg_scores = censored_rows["score"].to_numpy()

    total_test_merchant_weeks = fit["drift"]["test_rows"]

    rows_out = []
    for far in FAR_SWEEP:
        threshold = float(np.quantile(neg_scores, 1 - far))

        acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)
        benefit_total = float((acc_weeks * event_gmv * reserve_pct * benefit_capture).sum())

        flagged = censored_rows["score"] >= threshold
        cost_total = float((censored_rows.loc[flagged, "weekly_gmv"] * reserve_pct * wc_rate).sum())

        net_delta = cost_total - benefit_total
        per_1000 = net_delta / total_test_merchant_weeks * 1000
        seller_far = flagged.groupby(censored_rows["seller_id"]).any().mean() if flagged.any() else 0.0

        rows_out.append(
            {
                "false_alarm_rate": far,
                "threshold": threshold,
                "n_events_accelerated": int((acc_weeks > 0).sum()),
                "n_events_total": len(events),
                "benefit_total_reais": benefit_total,
                "cost_total_reais": cost_total,
                "net_delta_cost_reais": net_delta,
                "net_delta_cost_per_1000_merchant_weeks_reais": per_1000,
                "seller_level_false_alarm_rate": float(seller_far),
            }
        )
    return pd.DataFrame(rows_out)


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)
    costs = load_costs()

    fit = run_for_n(panel, features_df, PRIMARY_N)
    calibrator = fit_calibrator(fit)

    uncalibrated = pd.read_csv("figures/phase3_far_sweep.csv")
    calibrated = run_calibrated_sweep(fit, features_df, panel, costs, calibrator)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)
    print("=== calibrated sweep ===")
    print(calibrated.to_string(index=False))

    compare = pd.DataFrame(
        {
            "false_alarm_rate": uncalibrated["false_alarm_rate"],
            "net_delta_per_1000mw_uncalibrated": uncalibrated["net_delta_cost_per_1000_merchant_weeks_reais"],
            "net_delta_per_1000mw_calibrated": calibrated["net_delta_cost_per_1000_merchant_weeks_reais"],
        }
    )
    compare["difference"] = compare["net_delta_per_1000mw_calibrated"] - compare["net_delta_per_1000mw_uncalibrated"]
    compare["sign_flip"] = np.sign(compare["net_delta_per_1000mw_calibrated"]) != np.sign(
        compare["net_delta_per_1000mw_uncalibrated"]
    )
    print("\n=== comparison ===")
    print(compare.to_string(index=False))

    any_flip = compare["sign_flip"].any()
    still_wins_everywhere = (calibrated["net_delta_cost_per_1000_merchant_weeks_reais"] < 0).all()
    print(f"\nany sign flip: {any_flip}")
    print(f"calibrated result still beats the rule at every FAR: {still_wins_everywhere}")
    max_abs_diff = compare["difference"].abs().max()
    print(f"largest absolute difference vs. uncalibrated: R${max_abs_diff:.4f} per 1,000 merchant-weeks")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        uncalibrated["false_alarm_rate"] * 100,
        uncalibrated["net_delta_cost_per_1000_merchant_weeks_reais"],
        marker="o",
        label="uncalibrated (D16)",
        color="#4C72B0",
    )
    ax.plot(
        calibrated["false_alarm_rate"] * 100,
        calibrated["net_delta_cost_per_1000_merchant_weeks_reais"],
        marker="s",
        label="isotonic-calibrated (this check)",
        color="#C44E52",
        linestyle="--",
    )
    ax.axhline(0, color="black", linestyle="--", linewidth=1, label="breakeven with N=8 rule")
    ax.set_xlabel("row-level false-alarm rate (%)")
    ax.set_ylabel("net delta cost per 1,000 merchant-weeks (R$)")
    ax.set_title("Does isotonic calibration change the FAR-sweep result?")
    ax.legend()
    fig.tight_layout()
    fig.savefig("figures/phase4_calibrated_sweep.png", dpi=150)
    print("\nwrote figures/phase4_calibrated_sweep.png")

    calibrated.to_csv("figures/phase4_calibrated_sweep.csv", index=False)
    compare.to_csv("figures/phase4_calibrated_sweep_comparison.csv", index=False)
    with open("figures/phase4_calibrated_sweep.json", "w") as f:
        json.dump(
            {
                "calibrated_sweep": calibrated.to_dict(orient="records"),
                "comparison": compare.to_dict(orient="records"),
                "any_sign_flip": bool(any_flip),
                "still_wins_everywhere": bool(still_wins_everywhere),
                "max_abs_difference_reais": float(max_abs_diff),
            },
            f,
            indent=2,
            default=str,
        )
    print("wrote figures/phase4_calibrated_sweep.csv/.json")


if __name__ == "__main__":
    main()
