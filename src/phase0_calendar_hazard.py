"""Phase 0 follow-up: check whether pure-cessation events cluster at the
right edge of the study window -- i.e. whether trimming to STUDY_END
(panel.py, DECISIONS.md D1) actually fixed the truncation-vs-cessation
confound, or just pushed it into the last few weeks before the cutoff.

For each N in CESSATION_N_CANDIDATES:
  - count and share of events whose event week falls in the final N weeks
    before STUDY_END
  - event rate (hazard) by calendar week across the whole study window,
    plotted against the number of sellers at risk that week

An event's calendar week is defined as last_active_week + N weeks -- the
week the Nth consecutive silent week completes, i.e. the earliest point the
event is confirmed under that N. By construction no event can be confirmed
after STUDY_END, so a right-edge spike here would mean sellers whose last
*observed* order happens to land near STUDY_END - N are being
disproportionately confirmed as events -- a sign the window is still too
short for the N in question, not that sellers really are failing more
right before the cutoff.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from distress_events import (
    CESSATION_N_CANDIDATES,
    add_rolling_rates,
    compute_cessation_candidates,
    compute_eligibility,
)
from panel import STUDY_END, build_panel

FIG_DIR = Path("figures")


def event_calendar_week(cess: pd.DataFrame, n_weeks: int) -> pd.Series:
    return cess["last_active_week"] + pd.Timedelta(weeks=n_weeks)


def right_edge_check(panel: pd.DataFrame, per_seller: pd.DataFrame, n_weeks: int) -> dict:
    cess = compute_cessation_candidates(panel, per_seller, n_weeks)
    elig = cess[cess["eligible"]].copy()
    elig["event_week"] = event_calendar_week(elig, n_weeks)

    events = elig[elig["event_B"]]
    cutoff = STUDY_END - pd.Timedelta(weeks=n_weeks)
    in_final_window = events["event_week"] > cutoff
    return {
        "n": n_weeks,
        "n_events": len(events),
        "n_events_in_final_window": int(in_final_window.sum()),
        "share_in_final_window": in_final_window.mean() if len(events) else float("nan"),
    }, elig


def build_weekly_hazard(panel: pd.DataFrame, elig: pd.DataFrame, n_weeks: int) -> pd.DataFrame:
    """At-risk count and event count per calendar week, for one N."""
    exit_week = elig["event_week"].where(elig["event_B"], STUDY_END)
    exit_week = exit_week.combine(pd.Series(STUDY_END, index=elig.index), min)
    elig = elig.assign(exit_week=exit_week)

    p = panel.merge(elig[["exit_week", "event_B"]], left_on="seller_id", right_index=True, how="inner")
    at_risk = p[p["week"] <= p["exit_week"]]

    by_week = at_risk.groupby("week").size().rename("n_at_risk").to_frame()
    event_weeks = elig.loc[elig["event_B"], "exit_week"].value_counts().rename("n_events")
    by_week = by_week.join(event_weeks).fillna({"n_events": 0})
    by_week["n_events"] = by_week["n_events"].astype(int)
    by_week["hazard"] = by_week["n_events"] / by_week["n_at_risk"]
    by_week["n"] = n_weeks
    return by_week.reset_index()


# Candidate Phase 2 test-window widths, purely for this pre-Phase-1 check --
# NOT a committed split. Widths chosen to bracket a plausible late-window
# holdout (roughly 3 to 6 months of the 86-week study).
CANDIDATE_TEST_WIDTHS_WEEKS = [13, 17, 20, 26]


def test_window_event_counts(elig_by_n: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for n, elig in elig_by_n.items():
        events = elig[elig["event_B"]]
        for width in CANDIDATE_TEST_WIDTHS_WEEKS:
            cutoff = STUDY_END - pd.Timedelta(weeks=width)
            n_in_test = int((events["event_week"] > cutoff).sum())
            rows.append(
                {
                    "N": n,
                    "test_width_weeks": width,
                    "test_start": cutoff.date(),
                    "events_in_test_window": n_in_test,
                    "events_in_train_window": len(events) - n_in_test,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    panel = build_panel(Path("data/raw"))
    panel = add_rolling_rates(panel)
    per_seller = compute_eligibility(panel)

    print(f"STUDY_END = {STUDY_END.date()}\n")

    hazard_tables = []
    elig_by_n = {}
    for n in CESSATION_N_CANDIDATES:
        stats, elig = right_edge_check(panel, per_seller, n)
        print(
            f"N={n}: {stats['n_events']} events total, "
            f"{stats['n_events_in_final_window']} ({stats['share_in_final_window']:.1%}) "
            f"confirmed in the final {n} weeks before STUDY_END"
        )
        hazard_tables.append(build_weekly_hazard(panel, elig, n))
        elig_by_n[n] = elig

    hazard = pd.concat(hazard_tables, ignore_index=True)
    hazard.to_csv(FIG_DIR / "phase0_calendar_hazard.csv", index=False)

    print("\n--- provisional test-window event counts (NOT a committed Phase 2 split) ---")
    test_counts = test_window_event_counts(elig_by_n)
    pd.set_option("display.width", 160)
    print(test_counts.to_string(index=False))
    test_counts.to_csv(FIG_DIR / "phase0_test_window_check.csv", index=False)

    fig, axes = plt.subplots(len(CESSATION_N_CANDIDATES), 1, figsize=(11, 3 * len(CESSATION_N_CANDIDATES)), sharex=True)
    for ax, n in zip(axes, CESSATION_N_CANDIDATES):
        sub = hazard[hazard["n"] == n]
        ax2 = ax.twinx()
        ax2.bar(sub["week"], sub["n_at_risk"], width=6, color="lightgrey", alpha=0.6, label="n at risk")
        ax.plot(sub["week"], sub["hazard"], color="#C44E52", marker="o", markersize=3, linewidth=1, label="hazard")
        # post-D6, no event can be confirmed after STUDY_END - 2*n (the edge
        # exclusion doubles the effective margin) -- mark that, not the old N-only line
        ax.axvline(STUDY_END - pd.Timedelta(weeks=2 * n), color="black", linestyle="--", linewidth=1)
        ax.set_ylabel(f"hazard, N={n}")
        ax2.set_ylabel("n at risk")
        if n == CESSATION_N_CANDIDATES[0]:
            ax.set_title("Weekly hazard rate (pure cessation) vs. sellers at risk, by N")
    axes[-1].set_xlabel("calendar week")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "phase0_calendar_hazard.png", dpi=150)
    plt.close(fig)
    print(f"\nwrote {FIG_DIR / 'phase0_calendar_hazard.png'}")
    print(f"wrote {FIG_DIR / 'phase0_calendar_hazard.csv'}")


if __name__ == "__main__":
    main()
