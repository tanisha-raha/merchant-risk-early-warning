"""Phase 0: candidate distress-event definitions over the seller-week panel.

Three candidates are computed side by side so the numbers can be compared,
not just the best one reported:

  A. Cessation preceded by elevated quality problems (the brief's starting
     suggestion). A seller "ceases" if it goes silent for >= N consecutive
     weeks and never places another order before the study ends, AND the
     trailing 4-week window before the last order shows an elevated
     cancellation or late-delivery rate. The quality condition is what
     tries to separate "distress" from "benign exit" (e.g. a seasonal
     seller, or one that simply moved to another marketplace in good
     standing).
  B. Cessation alone, same N-week rule, WITHOUT the quality filter. This is
     candidate A's superset -- comparing A and B shows exactly how much the
     "preceded by" clause removes, which the brief specifically asked us to
     interrogate rather than assume.
  C. Sustained quality collapse WITHOUT requiring cessation: an elevated
     late-delivery (or cancellation) rate sustained for M consecutive weeks
     while the seller keeps trading. This targets the other failure mode
     described in the brief -- a merchant that floods refunds/cancellations
     rather than going dark -- which A and B cannot detect by construction
     since they require the seller to stop ordering.

Eligibility: a seller only enters the risk set for A/B/C if it has placed
at least MIN_TOTAL_ORDERS orders across at least MIN_ACTIVE_WEEKS distinct
weeks within the study window. Below that, "cessation" is not a meaningful
concept -- a seller with one order ever trivially "ceases" the following
week regardless of health. Sellers excluded by this filter are reported
separately, not silently dropped from the denominator.

All thresholds are named constants at the top of the file, not buried in
logic, and every candidate is run at more than one parameter setting so the
Phase 0 report can show sensitivity rather than a single cherry-picked
number.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from panel import STUDY_END, build_panel

MIN_TOTAL_ORDERS = 4
MIN_ACTIVE_WEEKS = 3

TRAILING_WINDOW = 4  # weeks, matches the Phase 1 trend window for consistency

# "Elevated" thresholds for the trailing-window quality check, informed by
# the empirical distribution of roll4 rates across all active-seller-weeks
# (see FAILURES.md / DECISIONS.md for the numbers behind these choices).
# Cancellation is almost always exactly zero at seller-week grain in this
# dataset (95th percentile of the trailing rate is 0.0) -- included for
# completeness but expected to contribute little on its own.
CANCEL_ELEVATED_THRESHOLD = 0.10   # roughly the 99th percentile of trailing cancel rate
LATE_ELEVATED_THRESHOLD = 0.50     # roughly the 95th percentile of trailing late-delivery rate

CESSATION_N_CANDIDATES = [4, 8, 12]  # weeks of silence required to call it terminal
COLLAPSE_M_CANDIDATES = [2, 3]        # consecutive elevated weeks required for candidate C


def add_rolling_rates(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values(["seller_id", "week"]).copy()
    g = panel.groupby("seller_id")
    roll_orders = g["n_orders"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())
    roll_cancel = g["n_cancelled"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())
    roll_delivered = g["n_delivered"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())
    roll_late = g["n_late"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())

    panel["roll_orders"] = roll_orders
    panel["roll_cancel_rate"] = roll_cancel / roll_orders.replace(0, pd.NA)
    panel["roll_late_rate"] = roll_late / roll_delivered.replace(0, pd.NA)
    panel["roll_elevated"] = (
        panel["roll_cancel_rate"].fillna(0).gt(CANCEL_ELEVATED_THRESHOLD)
        | panel["roll_late_rate"].fillna(0).gt(LATE_ELEVATED_THRESHOLD)
    ) & (panel["roll_orders"] > 0)
    return panel


def compute_eligibility(panel: pd.DataFrame) -> pd.DataFrame:
    per_seller = panel.groupby("seller_id").agg(
        total_orders=("n_orders", "sum"),
        active_weeks=("n_orders", lambda s: (s > 0).sum()),
        first_week=("week", "min"),
        last_week=("week", "max"),
        panel_len_weeks=("week", "size"),
    )
    per_seller["eligible"] = (per_seller["total_orders"] >= MIN_TOTAL_ORDERS) & (
        per_seller["active_weeks"] >= MIN_ACTIVE_WEEKS
    )
    return per_seller


def compute_cessation_candidates(
    panel: pd.DataFrame, per_seller: pd.DataFrame, n_weeks: int
) -> pd.DataFrame:
    """Candidates A (quality-filtered) and B (unfiltered) for a given N.

    Edge exclusion (DECISIONS.md D6, approved 2026-08-23): an event
    confirmed with less than N weeks of margin beyond the bare N-week
    silence requirement -- i.e. whose confirmation date (last_active_week
    + N) falls within the final N calendar weeks before STUDY_END -- is
    NOT counted as an event. Those sellers are treated as censored at
    STUDY_END instead, same as any other seller without enough follow-up
    to confirm. This is equivalent to requiring silence_weeks_observed
    >= 2*n_weeks, stated here as "exclude the last N weeks of possible
    confirmations" because that's the more legible framing of what's being
    thrown out and why (see FAILURES.md F3).
    """
    active = panel[panel["n_orders"] > 0]
    last_active = active.groupby("seller_id")["week"].max().rename("last_active_week")
    last_active_tenure = active.groupby("seller_id")["tenure_week"].max().rename("last_active_tenure_week")

    out = per_seller.join(last_active).join(last_active_tenure)
    out["silence_weeks_observed"] = ((STUDY_END - out["last_active_week"]).dt.days // 7)
    out["cessation_confirmed"] = out["silence_weeks_observed"] >= n_weeks

    out["event_week"] = out["last_active_week"] + pd.Timedelta(weeks=n_weeks)
    edge_zone_start = STUDY_END - pd.Timedelta(weeks=n_weeks)
    out["in_edge_zone"] = out["cessation_confirmed"] & (out["event_week"] > edge_zone_start)

    # trailing quality at the last active week
    q = panel.set_index(["seller_id", "week"])[["roll_cancel_rate", "roll_late_rate", "roll_elevated"]]
    key = pd.MultiIndex.from_arrays([out.index, out["last_active_week"]])
    trailing = q.reindex(key)
    trailing.index = out.index
    out = out.join(trailing)

    out["event_B"] = out["eligible"] & out["cessation_confirmed"] & ~out["in_edge_zone"]
    out["event_A"] = out["event_B"] & out["roll_elevated"].fillna(False)

    # observation length in weeks (tenure_week at event, or at panel end if censored)
    end_tenure = (
        panel.groupby("seller_id")["tenure_week"].max().rename("panel_end_tenure_week")
    )
    out = out.join(end_tenure)
    out["obs_len_B"] = out["last_active_tenure_week"] + n_weeks
    out["obs_len_B"] = out["obs_len_B"].where(out["event_B"], out["panel_end_tenure_week"])
    out["obs_len_A"] = out["obs_len_B"]
    return out


def compute_collapse_candidate(panel: pd.DataFrame, per_seller: pd.DataFrame, m_weeks: int) -> pd.DataFrame:
    """Candidate C: sustained elevated quality window, M consecutive weeks, no cessation required."""
    panel = panel.sort_values(["seller_id", "week"]).copy()
    panel["elevated_streak"] = (
        panel.groupby("seller_id")["roll_elevated"]
        .transform(lambda s: s.astype(int).groupby((~s).cumsum()).cumsum())
    )
    hit = panel[panel["elevated_streak"] >= m_weeks]
    first_hit = hit.groupby("seller_id")["tenure_week"].min().rename("event_C_tenure_week")

    end_tenure = panel.groupby("seller_id")["tenure_week"].max().rename("panel_end_tenure_week")
    out = per_seller.join(first_hit).join(end_tenure)
    out["event_C"] = out["eligible"] & out["event_C_tenure_week"].notna()
    out["obs_len_C"] = out["event_C_tenure_week"].where(out["event_C"], out["panel_end_tenure_week"])
    return out


def summarize(flag_col: str, obs_col: str, table: pd.DataFrame) -> dict:
    elig = table[table["eligible"]]
    n_sellers = len(elig)
    n_events = int(elig[flag_col].sum())
    n_censored = n_sellers - n_events
    obs = elig[obs_col]
    return {
        "n_sellers_eligible": n_sellers,
        "n_events": n_events,
        "event_rate": n_events / n_sellers if n_sellers else float("nan"),
        "censoring_rate": n_censored / n_sellers if n_sellers else float("nan"),
        "obs_len_weeks_p25": obs.quantile(0.25),
        "obs_len_weeks_median": obs.quantile(0.50),
        "obs_len_weeks_p75": obs.quantile(0.75),
        "obs_len_weeks_max": obs.max(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    panel = build_panel(args.raw_dir)
    panel = add_rolling_rates(panel)
    per_seller = compute_eligibility(panel)

    n_total_sellers = len(per_seller)
    n_eligible = int(per_seller["eligible"].sum())
    print(f"total sellers in panel: {n_total_sellers}")
    print(
        f"eligible (>= {MIN_TOTAL_ORDERS} orders, >= {MIN_ACTIVE_WEEKS} active weeks): "
        f"{n_eligible} ({n_eligible / n_total_sellers:.1%})"
    )
    print()

    rows = []
    for n in CESSATION_N_CANDIDATES:
        cess = compute_cessation_candidates(panel, per_seller, n)
        for label, flag_col, obs_col in [
            (f"A: cessation(N={n}) + elevated quality", "event_A", "obs_len_A"),
            (f"B: cessation(N={n}) only", "event_B", "obs_len_B"),
        ]:
            stats = summarize(flag_col, obs_col, cess)
            rows.append({"definition": label, **stats})

    for m in COLLAPSE_M_CANDIDATES:
        coll = compute_collapse_candidate(panel, per_seller, m)
        stats = summarize("event_C", "obs_len_C", coll)
        rows.append({"definition": f"C: quality collapse(M={m}) no cessation required", **stats})

    report = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)
    print(report.to_string(index=False))

    out_path = Path("figures") / "phase0_candidate_definitions.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
