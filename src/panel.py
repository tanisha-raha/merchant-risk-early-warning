"""Build the seller-week panel from the raw Olist CSVs.

One row per (seller_id, week) for every week a seller is "in the risk set":
from the week of their first order (within the study window) through the
administrative end of the study window. Weeks with zero orders are included
explicitly -- that is the whole point of a panel meant to detect cessation.

Study window
------------
The raw purchase timestamps span 2016-09-04 to 2018-10-17, but the ends are
data-collection artefacts, not signal:

- 2016-09 through 2016-12 is a soft-launch: a few hundred orders in one week
  (2016-10-03/09), then near silence until January 2017. Sellers active only
  in this period look identical to sellers who churned immediately after
  onboarding; there isn't enough surrounding data to tell.
- 2018-09 onward collapses from ~1-2k orders/week to single digits within
  two weeks. This is the dataset extract cutting off mid-week, not every
  seller on the platform failing simultaneously.

We therefore truncate the study window to [STUDY_START, STUDY_END] below and
drop orders outside it entirely, as if they were never collected. Sellers
whose only activity falls outside the window do not enter the panel. This
means real (pre-truncation) seller history from late 2016 is discarded --
that is a real cost, flagged in the Phase 0 report, not hidden.

STUDY_END is also the administrative censoring point: any seller still
active in the weeks immediately before STUDY_END is right-censored, not
observed to fail, no matter how long their apparent silence looks once the
window is over.

IMPORTANT -- this module builds panels for two different purposes and they
must not be confused:
  1. Label construction (Phase 0 distress-event definitions, Phase 2 targets):
     uses the FINAL order status / delivery outcome as recorded in the CSVs.
     That is the ground truth of what happened to the order, full stop.
  2. As-of feature construction (Phase 1): must NOT use this final status
     directly for weeks close to the order date, because in production you
     would not yet know whether a just-placed order will later be cancelled
     or delivered late. Phase 1 will need its own as-of-safe aggregation
     with an explicit reporting lag. Do not reuse these columns as features
     without re-deriving them -- that would be exactly the look-ahead leak
     the brief calls out as the most likely failure mode.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

STUDY_START = pd.Timestamp("2017-01-01")
STUDY_END = pd.Timestamp("2018-08-26")  # last week with >1k orders; see module docstring

WEEK_FREQ = "W-SUN"  # weeks labelled by their Sunday end date, Monday-Sunday


def load_raw(raw_dir: Path) -> dict[str, pd.DataFrame]:
    raw_dir = Path(raw_dir)
    orders = pd.read_csv(
        raw_dir / "olist_orders_dataset.csv",
        parse_dates=[
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    items = pd.read_csv(raw_dir / "olist_order_items_dataset.csv")
    return {"orders": orders, "items": items}


def build_order_seller_frame(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per (order_id, seller_id) with the order-level fields needed
    for weekly aggregation. An order with items from multiple sellers
    produces one row per seller; order-level fields (status, cancellation,
    delivery dates) are shared across those rows -- a simplification, since
    the raw data has no seller-level order status.
    """
    orders = raw["orders"]
    items = raw["items"][["order_id", "seller_id", "price", "freight_value"]].copy()

    df = items.merge(
        orders[
            [
                "order_id",
                "order_status",
                "order_purchase_timestamp",
                "order_delivered_customer_date",
                "order_estimated_delivery_date",
            ]
        ],
        on="order_id",
        how="inner",
        validate="many_to_one",
    )

    # collapse multi-item orders to one row per (order_id, seller_id): items
    # from the same seller in the same order are one commercial transaction.
    agg = df.groupby(["order_id", "seller_id"], as_index=False).agg(
        order_status=("order_status", "first"),
        order_purchase_timestamp=("order_purchase_timestamp", "first"),
        order_delivered_customer_date=("order_delivered_customer_date", "first"),
        order_estimated_delivery_date=("order_estimated_delivery_date", "first"),
        item_price=("price", "sum"),
        item_freight=("freight_value", "sum"),
    )

    in_window = agg["order_purchase_timestamp"].between(STUDY_START, STUDY_END)
    dropped = (~in_window).sum()
    if dropped:
        print(
            f"[panel] dropping {dropped} (order, seller) rows outside study "
            f"window [{STUDY_START.date()}, {STUDY_END.date()}] "
            f"({dropped / len(agg):.1%} of all rows)"
        )
    return agg.loc[in_window].reset_index(drop=True)


def _week_end(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period(WEEK_FREQ).dt.end_time.dt.normalize()


def build_weekly_aggregates(order_seller: pd.DataFrame) -> pd.DataFrame:
    df = order_seller.copy()
    df["week"] = _week_end(df["order_purchase_timestamp"])

    df["is_cancelled"] = df["order_status"].eq("canceled")
    df["is_unavailable"] = df["order_status"].eq("unavailable")
    df["is_delivered"] = df["order_status"].eq("delivered")
    df["is_late"] = df["is_delivered"] & (
        df["order_delivered_customer_date"] > df["order_estimated_delivery_date"]
    )

    weekly = df.groupby(["seller_id", "week"], as_index=False).agg(
        n_orders=("order_id", "nunique"),
        n_cancelled=("is_cancelled", "sum"),
        n_unavailable=("is_unavailable", "sum"),
        n_delivered=("is_delivered", "sum"),
        n_late=("is_late", "sum"),
        revenue=("item_price", "sum"),
    )
    return weekly


def build_seller_week_panel(weekly: pd.DataFrame) -> pd.DataFrame:
    """Expand each seller's activity to a dense weekly grid, filling
    zero-order weeks explicitly, from the seller's first order week (within
    the study window) through STUDY_END.
    """
    all_weeks = pd.period_range(STUDY_START, STUDY_END, freq=WEEK_FREQ).end_time.normalize()

    rows = []
    for seller_id, g in weekly.groupby("seller_id"):
        first_week = g["week"].min()
        seller_weeks = all_weeks[all_weeks >= first_week]
        grid = pd.DataFrame({"seller_id": seller_id, "week": seller_weeks})
        rows.append(grid)
    grid = pd.concat(rows, ignore_index=True)

    panel = grid.merge(weekly, on=["seller_id", "week"], how="left")
    count_cols = ["n_orders", "n_cancelled", "n_unavailable", "n_delivered", "n_late"]
    panel[count_cols] = panel[count_cols].fillna(0).astype(int)
    panel["revenue"] = panel["revenue"].fillna(0.0)

    panel = panel.sort_values(["seller_id", "week"]).reset_index(drop=True)
    panel["tenure_week"] = panel.groupby("seller_id").cumcount()  # 0-indexed weeks since first order
    return panel


def build_panel_from_raw(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Core label-panel logic, taking already-loaded raw tables. Split out
    from build_panel() so callers (notably features.py and the leakage
    tests) can pass in-memory, possibly-truncated raw data instead of
    always reading from disk.
    """
    order_seller = build_order_seller_frame(raw)
    weekly = build_weekly_aggregates(order_seller)
    panel = build_seller_week_panel(weekly)
    return panel


def build_panel(raw_dir: Path) -> pd.DataFrame:
    return build_panel_from_raw(load_raw(raw_dir))


def seller_week_grid(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The (seller_id, week, tenure_week) grid only -- no label/outcome
    columns. This is what features.py builds on: it's derived purely from
    *when* a seller's first order happened and the fixed study window, both
    as-of-safe, so it's safe to share between the label pipeline and the
    feature pipeline without coupling features.py to panel.py's
    final-status label columns.
    """
    return build_panel_from_raw(raw)[["seller_id", "week", "tenure_week"]]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/seller_week_panel.csv"))
    args = parser.parse_args()

    panel = build_panel(args.raw_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.out, index=False)
    print(f"[panel] wrote {len(panel)} rows, {panel['seller_id'].nunique()} sellers -> {args.out}")


if __name__ == "__main__":
    main()
