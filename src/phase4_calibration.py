"""Phase 4, priority 3: lead-time headline figure + calibration.

Why calibration matters more than AUC here: the decision layer (Phase 3)
doesn't rank merchants against each other -- it thresholds the model's
*absolute* predicted probability against a false-alarm-rate-derived cutoff,
and the brief's original design (before D13-D16 narrowed Phase 3's scope)
wanted a reserve percentage sized directly off the hazard value. Either
way, "the model says 3% risk this week" needs to actually mean 3%, not
just rank correctly relative to other weeks -- a model can have excellent
AUC while being badly miscalibrated (e.g. systematically over- or
under-confident), and that miscalibration would silently distort every
FAR threshold and every reserve figure downstream. AUC alone can't catch
that; a reliability diagram and Brier/ECE can.

Two outputs:
1. The lead-time headline figure -- NOT the raw "days of warning before
   the event" the brief's Phase 4 spec originally asked for (D14 sec.2
   already established the honest framing is acceleration over the N=8
   rule, not raw lead time) -- the full distribution of acceleration
   weeks at a fixed FAR (5%, the same operating point used throughout
   Phase 3/4), plus the last-order-anchored AUC-vs-k curve as the
   complementary "does discrimination hold before the seller goes quiet"
   view.
2. Reliability diagram, Brier score, and Expected Calibration Error (ECE)
   on the primary model's test-period, at-event-week predictions -- the
   same predictions the FAR threshold in Phase 3 is drawn from. Binned by
   quantile of predicted probability, not equal-width bins: event rate is
   ~0.5-0.7%, so equal-width bins over [0,1] would put almost every row
   in the first bin and say nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from features import build_features
from model import PRIMARY_N, TEST_CUTOFF, predict, run_for_n, transform_features
from panel import build_panel
from phase2_acceleration_vs_rule import acceleration_for_events, compute_threshold
from phase2_lead_time_diagnostic import K_WEEKS, lead_time_auc

PRIMARY_FAR = 0.05
N_CALIBRATION_BINS = 10


def reliability_table(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = N_CALIBRATION_BINS) -> pd.DataFrame:
    df = pd.DataFrame({"y_true": y_true, "y_pred": y_pred})
    df["bin"] = pd.qcut(df["y_pred"], n_bins, duplicates="drop")
    table = df.groupby("bin", observed=True).agg(
        n=("y_true", "size"),
        mean_predicted=("y_pred", "mean"),
        mean_actual=("y_true", "mean"),
    )
    table["abs_gap"] = (table["mean_predicted"] - table["mean_actual"]).abs()
    return table.reset_index(drop=True)


def expected_calibration_error(table: pd.DataFrame, n_total: int) -> float:
    return float((table["n"] / n_total * table["abs_gap"]).sum())


def plot_reliability(table: pd.DataFrame, brier: float, ece: float, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [2, 1]})

    ax = axes[0]
    max_val = max(table["mean_predicted"].max(), table["mean_actual"].max()) * 1.15
    ax.plot([0, max_val], [0, max_val], color="black", linestyle="--", linewidth=1, label="perfect calibration")
    sizes = table["n"] / table["n"].max() * 300 + 20
    ax.scatter(table["mean_predicted"], table["mean_actual"], s=sizes, color="#C44E52")
    for _, row in table.iterrows():
        ax.annotate(
            f"n={int(row['n'])}",
            (row["mean_predicted"], row["mean_actual"]),
            fontsize=7,
            xytext=(4, 4),
            textcoords="offset points",
        )
    ax.set_xlabel("mean predicted probability (quantile bin)")
    ax.set_ylabel("mean actual event rate (quantile bin)")
    ax.set_title(f"Reliability diagram (primary N=8, test period)\nBrier={brier:.4f}, ECE={ece:.4f}")
    ax.legend()

    ax2 = axes[1]
    ax2.bar(range(len(table)), table["n"], color="#4C72B0")
    ax2.set_xlabel("bin (low -> high predicted risk)")
    ax2.set_ylabel("rows in bin")
    ax2.set_title("Bin sizes")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def plot_headline_lead_time(
    acc_df: pd.DataFrame, far: float, curve: dict, out_path: Path
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    ax = axes[0]
    finite = acc_df["acceleration_weeks"].dropna()
    never = acc_df["model_alarm_week"].isna().sum()
    n_total = len(acc_df)
    ax.hist(finite, bins=range(0, int(finite.max()) + 2), color="#55A868", edgecolor="white")
    if len(finite):
        median = finite.median()
        ax.axvline(median, color="black", linestyle="--", linewidth=1, label=f"median = {median:.1f} weeks")
    ax.set_xlabel("weeks earlier than the N=8 rule (0 = same week or later)")
    ax.set_ylabel("events")
    ax.set_title(
        f"Headline: acceleration over the N=8 rule at FAR={far:.0%}\n"
        f"{never}/{n_total} events never flagged before the rule fires ({never/n_total:.0%})"
    )
    ax.legend()

    ax2 = axes[1]
    ks = list(curve.keys())
    aucs = [curve[k]["auc"] for k in ks]
    ax2.plot(ks, aucs, marker="o", color="#4C72B0")
    ax2.axhline(0.5, color="black", linestyle="--", linewidth=1, label="chance")
    ax2.set_xlabel("weeks before the seller's actual last order")
    ax2.set_ylabel("AUC")
    ax2.set_ylim(0.4, 1.0)
    ax2.set_title("The honest complementary view:\ndiscrimination while still genuinely trading (D14 sec.1)")
    ax2.legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)

    fit = run_for_n(panel, features_df, PRIMARY_N)
    clf, scaler, feature_cols = fit["_clf"], fit["_scaler"], fit["_feature_cols"]
    test = fit["_test"]
    y_true = test["label"].to_numpy()
    y_pred = predict(clf, scaler, test, feature_cols)

    table = reliability_table(y_true, y_pred)
    ece = expected_calibration_error(table, len(y_true))
    brier = fit["test_eval"]["brier"]

    pd.set_option("display.width", 160)
    print("=== reliability table (test period, at-event-week predictions) ===")
    print(table.to_string(index=False))
    print(f"\nBrier score: {brier:.4f}")
    print(f"Expected Calibration Error (ECE): {ece:.4f}")

    plot_reliability(table, brier, ece, Path("figures/phase4_reliability_diagram.png"))

    print(f"\n=== headline lead-time figure, FAR={PRIMARY_FAR:.0%} ===")
    labels = fit["_labels"]
    censored = labels[~labels["event_B"]]
    neg_rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    freq_map = fit["_freq_map"]
    neg_scored = transform_features(neg_rows, freq_map)
    neg_scores = predict(clf, scaler, neg_scored, feature_cols)
    threshold = compute_threshold(neg_scores, PRIMARY_FAR)

    acc_df = acceleration_for_events(fit, features_df, threshold)
    print(acc_df["acceleration_weeks"].describe())

    curve = lead_time_auc(fit, K_WEEKS, features_df, anchor_col="last_active_week")

    plot_headline_lead_time(acc_df, PRIMARY_FAR, curve, Path("figures/phase4_headline_lead_time.png"))

    out = {
        "reliability_table": table.to_dict(orient="records"),
        "brier": brier,
        "ece": ece,
        "primary_far": PRIMARY_FAR,
        "threshold": threshold,
        "acceleration_summary": {
            "n_events": len(acc_df),
            "n_never_beats_rule": int(acc_df["model_alarm_week"].isna().sum()),
            "median_acceleration_weeks": (
                float(acc_df["acceleration_weeks"].dropna().median())
                if acc_df["acceleration_weeks"].notna().any()
                else None
            ),
        },
        "last_order_anchored_curve": curve,
    }
    with open("figures/phase4_calibration.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote figures/phase4_calibration.json")


if __name__ == "__main__":
    main()
