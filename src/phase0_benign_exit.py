"""Phase 0 follow-up: quantify how much of the pure-cessation label (N=8,
Candidate B) looks like genuine distress versus benign exit, using signals
that were NOT used to build the label itself (to avoid the circularity
flagged in FAILURES.md F2).

Four angles, each independent of the label:
  1. Overlap with Candidate A's elevated cancel/late-rate flag (already
     computed) -- a lower bound on "looks like distress by the brief's own
     quality proxy."
  2. Trailing review score before exit vs. the cross-sectional baseline --
     review score was never used in any candidate definition.
  3. Seasonality of cessation onset -- do cessations cluster right after
     known seasonal peaks (a one-shot seasonal seller pattern), more than
     order volume itself does?
  4. Size/tenure of ceasing sellers vs. still-active (censored) sellers --
     are cessations concentrated in marginal, low-volume sellers?
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from distress_events import (
    TRAILING_WINDOW,
    add_rolling_rates,
    compute_cessation_candidates,
    compute_eligibility,
)
from panel import STUDY_END, STUDY_START, WEEK_FREQ, build_panel

N = 8  # the adopted primary definition


def load_review_weekly(raw_dir: Path) -> pd.DataFrame:
    orders = pd.read_csv(raw_dir / "olist_orders_dataset.csv", parse_dates=["order_purchase_timestamp"])
    items = pd.read_csv(raw_dir / "olist_order_items_dataset.csv")[["order_id", "seller_id"]].drop_duplicates()
    reviews = pd.read_csv(raw_dir / "olist_order_reviews_dataset.csv")[["order_id", "review_score"]]
    reviews = reviews.groupby("order_id", as_index=False)["review_score"].mean()  # a few dup review rows per order

    df = items.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    df = df.merge(reviews, on="order_id", how="inner")
    df["week"] = df["order_purchase_timestamp"].dt.to_period(WEEK_FREQ).dt.end_time.dt.normalize()
    df = df[df["week"].between(STUDY_START, STUDY_END)]

    weekly = df.groupby(["seller_id", "week"], as_index=False).agg(
        review_score_sum=("review_score", "sum"), n_reviews=("review_score", "count")
    )
    return weekly


def main() -> None:
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    panel = add_rolling_rates(panel)
    per_seller = compute_eligibility(panel)
    cess = compute_cessation_candidates(panel, per_seller, N)
    elig = cess[cess["eligible"]].copy()
    events = elig[elig["event_B"]]
    survivors = elig[~elig["event_B"]]

    print(f"=== Candidate B, N={N}: benign-exit quantification ===")
    print(f"eligible sellers: {len(elig)}, events: {len(events)}, censored: {len(survivors)}\n")

    # --- 1. overlap with Candidate A's elevated-quality flag -----------------
    elevated_share = events["roll_elevated"].fillna(False).mean()
    print("1. Elevated cancel/late rate in the trailing window before exit")
    print(f"   {events['roll_elevated'].fillna(False).sum()}/{len(events)} events "
          f"({elevated_share:.1%}) show elevated cancel/late rate before ceasing.")
    print(f"   {1 - elevated_share:.1%} of pure-cessation events show NO such signal "
          f"-- consistent with a benign exit by this proxy, though absence of the "
          f"proxy is not proof of a benign exit (F1: cancellation is sparse).\n")

    # --- 2. review score before exit vs. baseline -----------------------------
    review_weekly = load_review_weekly(raw_dir)
    panel_r = panel.merge(review_weekly, on=["seller_id", "week"], how="left")
    g = panel_r.groupby("seller_id")
    roll_score_sum = g["review_score_sum"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())
    roll_n_reviews = g["n_reviews"].transform(lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).sum())
    panel_r["roll_avg_review_score"] = roll_score_sum / roll_n_reviews.replace(0, pd.NA)

    baseline_scores = panel_r.loc[roll_n_reviews.fillna(0) > 0, "roll_avg_review_score"]
    key = pd.MultiIndex.from_arrays([events.index, events["last_active_week"]])
    trailing_scores = panel_r.set_index(["seller_id", "week"])["roll_avg_review_score"].reindex(key)

    print("2. Trailing review score before exit vs. cross-sectional baseline")
    print(f"   baseline (all active-seller-weeks with >=1 review in trailing window): "
          f"mean={baseline_scores.mean():.2f}, median={baseline_scores.median():.2f}, n={baseline_scores.notna().sum()}")
    print(f"   pre-exit (events, trailing window ending at last order): "
          f"mean={trailing_scores.mean():.2f}, median={trailing_scores.median():.2f}, "
          f"n={trailing_scores.notna().sum()}/{len(events)} (rest had no review in that window)\n")

    # --- 3. seasonality of cessation onset ------------------------------------
    events_by_month = events["last_active_week"].dt.to_period("M").value_counts().sort_index()
    overall_orders_by_month = panel[panel["n_orders"] > 0].groupby(panel["week"].dt.to_period("M"))["n_orders"].sum()
    seasonality = pd.DataFrame({
        "n_cessation_onsets": events_by_month,
        "share_of_cessations": events_by_month / events_by_month.sum(),
        "share_of_order_volume": overall_orders_by_month / overall_orders_by_month.sum(),
    }).dropna(subset=["n_cessation_onsets"])
    seasonality["cessation_vs_volume_ratio"] = (
        seasonality["share_of_cessations"] / seasonality["share_of_order_volume"]
    )
    print("3. Seasonality: month of last order, cessation share vs. order-volume share")
    print(seasonality.to_string())
    top_months = seasonality.sort_values("cessation_vs_volume_ratio", ascending=False).head(3)
    print("\n   months where cessation onsets over-index most vs. their share of order volume:")
    print(f"   {list(top_months.index.astype(str))}\n")

    # --- 4. size/tenure of ceasing vs. surviving sellers ----------------------
    print("4. Seller size (total orders) and tenure at risk-set entry: events vs. censored")
    for label, df in [("events (ceased)", events), ("censored (still active/right-censored)", survivors)]:
        print(f"   {label}: n={len(df)}")
        orders_q = df["total_orders"].quantile([.25, .5, .75])
        weeks_q = df["active_weeks"].quantile([.25, .5, .75])
        print(f"     total_orders  p25/median/p75 = {orders_q[.25]:.0f} / {orders_q[.5]:.0f} / {orders_q[.75]:.0f}")
        print(f"     active_weeks  p25/median/p75 = {weeks_q[.25]:.0f} / {weeks_q[.5]:.0f} / {weeks_q[.75]:.0f}")


if __name__ == "__main__":
    main()
