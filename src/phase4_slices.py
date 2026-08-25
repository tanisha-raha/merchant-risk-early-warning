"""Phase 4, priority 4: slice analysis and fairness.

Slices assigned PER SELLER (not per row) by tenure, size (weekly GMV),
dominant category, and order-volume decile -- the question is "does this
policy treat different kinds of merchants differently," not "does it
treat different weeks of the same merchant differently."

At FAR=5% (primary), extends Phase 3's economic framework (D16) to each
slice: does the model-based policy still beat the naive N=8 rule within
this slice, or does it lose? "Lose to the rule" is necessarily economic
here, not AUC-based -- the rule has no AUC of its own (it's
deterministic), so a slice-level comparison against it has to use the
same net-cost accounting Phase 3 used for the whole population.
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
from model import PRIMARY_N, TEST_CUTOFF, run_for_n
from panel import build_panel
from policy import (
    acceleration_weeks_at_threshold,
    load_costs,
    per_seller_weekly_gmv,
    score_censored_rows,
    score_event_histories,
)

PRIMARY_FAR = 0.05
MIN_SELLERS_FOR_SLICE = 20  # below this, a slice's numbers are too noisy to report on their own


def _qcut_labeled(series: pd.Series, q: int, prefix: str) -> pd.Series:
    """pd.qcut with duplicates='drop' can silently produce fewer bins than
    requested when the underlying values have many ties (common here --
    e.g. many sellers share the same rounded order_volume_level). A fixed
    label list then mismatches the actual bin count and raises. Bin first,
    then label by however many bins actually resulted.
    """
    binned = pd.qcut(series, q, duplicates="drop")
    codes = binned.cat.codes  # -1 for NaN, 0..k-1 otherwise
    n_bins = codes.max() + 1
    labels = [f"{prefix}{i + 1}_of_{n_bins}" for i in range(n_bins)]
    return codes.map(lambda c: labels[c] if c >= 0 else pd.NA)


def assign_seller_slices(panel: pd.DataFrame, features_df: pd.DataFrame) -> pd.DataFrame:
    weekly_gmv = per_seller_weekly_gmv(panel)
    size_band = _qcut_labeled(weekly_gmv, 4, "size_q")

    tenure_at_test_start = panel[panel["week"] > TEST_CUTOFF].groupby("seller_id")["tenure_week"].min()
    tenure_band = pd.cut(
        tenure_at_test_start,
        bins=[-1, 12, 51, 100_000],
        labels=["new_lt13wk", "established_13to52wk", "veteran_gt52wk"],
    )

    def _mode_or_unknown(s: pd.Series) -> str:
        m = s.dropna().mode()
        return m.iat[0] if len(m) else "unknown"

    dominant_category = features_df.groupby("seller_id")["category"].agg(_mode_or_unknown)

    active_volume = features_df[features_df["order_volume_level"] > 0]
    volume_mean = active_volume.groupby("seller_id")["order_volume_level"].mean()
    volume_band = _qcut_labeled(volume_mean, 10, "vol_decile_")

    return pd.DataFrame(
        {
            "weekly_gmv": weekly_gmv,
            "size_band": size_band,
            "tenure_at_test_start": tenure_at_test_start,
            "tenure_band": tenure_band,
            "category": dominant_category,
            "volume_band": volume_band,
        }
    )


def slice_economics(
    events: pd.Series,
    acc_weeks: pd.Series,
    event_gmv: pd.Series,
    censored_rows: pd.DataFrame,
    flagged: pd.Series,
    slices: pd.DataFrame,
    slice_col: str,
    costs: dict,
) -> pd.DataFrame:
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    event_slice = events.index.to_series().map(slices[slice_col])
    censored_slice = censored_rows["seller_id"].map(slices[slice_col])
    n_sellers_per_slice = slices[slice_col].value_counts()

    rows = []
    for slice_val in slices[slice_col].dropna().unique():
        in_slice_events = event_slice == slice_val
        n_events = int(in_slice_events.sum())
        benefit = float(
            (acc_weeks[in_slice_events] * event_gmv[in_slice_events] * reserve_pct * benefit_capture).sum()
        )

        in_slice_flagged = flagged & (censored_slice == slice_val)
        cost = float((censored_rows.loc[in_slice_flagged, "weekly_gmv"] * reserve_pct * wc_rate).sum())

        n_test_rows_slice = int((censored_slice == slice_val).sum())
        net = cost - benefit
        per_1000 = (net / n_test_rows_slice * 1000) if n_test_rows_slice else float("nan")

        rows.append(
            {
                "slice": str(slice_val),
                "n_sellers": int(n_sellers_per_slice.get(slice_val, 0)),
                "n_events": n_events,
                "n_censored_test_rows": n_test_rows_slice,
                "n_flagged": int(in_slice_flagged.sum()),
                "benefit_reais": benefit,
                "cost_reais": cost,
                "net_delta_reais": net,
                "net_delta_per_1000_merchant_weeks_reais": per_1000,
                "model_wins": net < 0,
            }
        )
    out = pd.DataFrame(rows).sort_values("net_delta_per_1000_merchant_weeks_reais", ascending=False)
    return out


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)
    costs = load_costs()

    fit = run_for_n(panel, features_df, PRIMARY_N)
    slices = assign_seller_slices(panel, features_df)

    histories, events = score_event_histories(fit, features_df)
    censored_rows = score_censored_rows(fit, features_df)
    weekly_gmv = per_seller_weekly_gmv(panel)
    censored_rows = censored_rows.assign(weekly_gmv=censored_rows["seller_id"].map(weekly_gmv))
    event_gmv = events.index.to_series().map(weekly_gmv)

    neg_scores = censored_rows["score"].to_numpy()
    threshold = float(np.quantile(neg_scores, 1 - PRIMARY_FAR))
    acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)
    flagged = censored_rows["score"] >= threshold

    slice_cols = ["tenure_band", "size_band", "category", "volume_band"]
    all_results = {}
    losing_slices = []

    for col in slice_cols:
        result = slice_economics(events, acc_weeks, event_gmv, censored_rows, flagged, slices, col, costs)
        all_results[col] = result
        print(f"=== slice: {col} ===")
        pd.set_option("display.width", 200)
        pd.set_option("display.max_columns", None)
        print(result.to_string(index=False))
        print()
        for _, row in result.iterrows():
            if not row["model_wins"] and row["n_sellers"] >= MIN_SELLERS_FOR_SLICE:
                losing_slices.append({"dimension": col, **row.to_dict()})

    print(f"=== slices (>= {MIN_SELLERS_FOR_SLICE} sellers) where the model LOSES to the N=8 rule ===")
    for ls in losing_slices:
        print(
            f"  {ls['dimension']}={ls['slice']}: n_sellers={ls['n_sellers']}, n_events={ls['n_events']}, "
            f"net_delta/1000mw=R${ls['net_delta_per_1000_merchant_weeks_reais']:.2f}"
        )
    if not losing_slices:
        print("  none found at this sample-size floor")

    out = {col: df.to_dict(orient="records") for col, df in all_results.items()}
    out["losing_slices"] = losing_slices
    out["threshold"] = threshold
    out["far"] = PRIMARY_FAR
    with open("figures/phase4_slices.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    for col, df in all_results.items():
        df.to_csv(f"figures/phase4_slices_{col}.csv", index=False)
    print("\nwrote figures/phase4_slices.json and per-dimension CSVs")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, col in zip(axes.flat, slice_cols):
        df = all_results[col].sort_values("slice")
        colors = ["#C44E52" if not w else "#4C72B0" for w in df["model_wins"]]
        ax.bar(df["slice"].astype(str), df["net_delta_per_1000_merchant_weeks_reais"], color=colors)
        ax.axhline(0, color="black", linewidth=1)
        ax.set_title(col)
        ax.set_ylabel("net Δcost / 1000 mw (R$)\nred = model loses")
        ax.tick_params(axis="x", rotation=60, labelsize=7)
    fig.suptitle(f"Slice economics at FAR={PRIMARY_FAR:.0%} (red = model loses to N=8 rule)", y=1.01)
    fig.tight_layout()
    fig.savefig("figures/phase4_slices.png", dpi=150, bbox_inches="tight")
    print("wrote figures/phase4_slices.png")


if __name__ == "__main__":
    main()
