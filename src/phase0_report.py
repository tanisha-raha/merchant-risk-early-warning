"""Phase 0 figures: calendar coverage (with the truncation flagged) and the
observation-length / event distribution for each candidate distress
definition. Run after distress_events.py; reads raw CSVs directly for the
calendar plot since that one deliberately shows data OUTSIDE the trimmed
study window, to make the truncation visible.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from panel import STUDY_END, STUDY_START, WEEK_FREQ, build_panel, load_raw
from distress_events import (
    CESSATION_N_CANDIDATES,
    add_rolling_rates,
    compute_cessation_candidates,
    compute_collapse_candidate,
    compute_eligibility,
)

FIG_DIR = Path("figures")


def plot_calendar_coverage(raw_dir: Path) -> None:
    raw = load_raw(raw_dir)
    orders = raw["orders"]
    items = raw["items"][["order_id", "seller_id"]]
    df = items.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    df["week"] = df["order_purchase_timestamp"].dt.to_period(WEEK_FREQ).dt.end_time.dt.normalize()

    weekly_orders = df.groupby("week")["order_id"].nunique()
    weekly_sellers = df.groupby("week")["seller_id"].nunique()

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)

    axes[0].bar(weekly_orders.index, weekly_orders.values, width=6, color="#4C72B0")
    axes[0].set_ylabel("orders / week")
    axes[0].set_title("Calendar coverage: weekly order volume, full raw range")

    axes[1].bar(weekly_sellers.index, weekly_sellers.values, width=6, color="#55A868")
    axes[1].set_ylabel("distinct sellers / week")

    for ax in axes:
        ax.axvspan(weekly_orders.index.min(), STUDY_START, color="grey", alpha=0.25)
        ax.axvspan(STUDY_END, weekly_orders.index.max(), color="grey", alpha=0.25)
        ax.axvline(STUDY_START, color="black", linestyle="--", linewidth=1)
        ax.axvline(STUDY_END, color="black", linestyle="--", linewidth=1)

    axes[0].text(
        weekly_orders.index.min(),
        axes[0].get_ylim()[1] * 0.9,
        " excluded: soft-launch pilot",
        fontsize=8,
    )
    axes[0].text(
        STUDY_END,
        axes[0].get_ylim()[1] * 0.9,
        " excluded: extract truncation",
        fontsize=8,
    )
    axes[0].text(
        STUDY_START,
        axes[0].get_ylim()[1] * 0.7,
        f" study window: {STUDY_START.date()} to {STUDY_END.date()}",
        fontsize=8,
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    FIG_DIR.mkdir(exist_ok=True)
    fig.savefig(FIG_DIR / "phase0_calendar_coverage.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIG_DIR / 'phase0_calendar_coverage.png'}")


def plot_definition_comparison(panel: pd.DataFrame) -> None:
    per_seller = compute_eligibility(panel)
    n = CESSATION_N_CANDIDATES[1]  # N=8, the middle/primary setting
    cess = compute_cessation_candidates(panel, per_seller, n)
    coll = compute_collapse_candidate(panel, per_seller, 3)

    elig_cess = cess[cess["eligible"]]
    elig_coll = coll[coll["eligible"]]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    labels = [f"A: cessation(N={n})\n+ elevated quality", f"B: cessation(N={n})\nonly", "C: quality collapse\n(M=3), no cessation"]
    event_counts = [
        int(elig_cess["event_A"].sum()),
        int(elig_cess["event_B"].sum()),
        int(elig_coll["event_C"].sum()),
    ]
    n_elig = len(elig_cess)
    bars = axes[0].bar(labels, event_counts, color=["#C44E52", "#4C72B0", "#55A868"])
    axes[0].axhline(150, color="black", linestyle="--", linewidth=1, label="kill-criteria floor (150)")
    axes[0].set_ylabel("distress events")
    axes[0].set_title(f"Events by candidate definition (n eligible sellers = {n_elig})")
    axes[0].legend(fontsize=8)
    for b, c in zip(bars, event_counts):
        axes[0].text(b.get_x() + b.get_width() / 2, c + 5, str(c), ha="center", fontsize=9)

    axes[1].hist(
        elig_cess.loc[elig_cess["event_B"], "obs_len_B"],
        bins=20,
        alpha=0.6,
        label="B: cessation, observation length to event",
        color="#4C72B0",
    )
    axes[1].hist(
        elig_cess.loc[~elig_cess["event_B"], "panel_end_tenure_week"],
        bins=20,
        alpha=0.6,
        label="censored, observation length to panel end",
        color="grey",
    )
    axes[1].set_xlabel("weeks since first order")
    axes[1].set_ylabel("sellers")
    axes[1].set_title("Observation length distribution (definition B)")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    FIG_DIR.mkdir(exist_ok=True)
    fig.savefig(FIG_DIR / "phase0_definition_comparison.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIG_DIR / 'phase0_definition_comparison.png'}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    plot_calendar_coverage(args.raw_dir)

    panel = build_panel(args.raw_dir)
    panel = add_rolling_rates(panel)
    plot_definition_comparison(panel)


if __name__ == "__main__":
    main()
