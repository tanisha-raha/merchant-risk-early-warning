"""Phase 1 feature pipeline. See FEATURES.md for the column list, the
level/trend/acceleration convention, and the as-of (event-attribution-week)
design that this module implements.

Deliberately does NOT reuse panel.py's weekly aggregates for anything
outcome-related (cancellation, lateness, etc.) -- those are purchase-week-
attributed FINAL-status labels, unsafe to reuse as features (see panel.py's
module docstring). Only panel.seller_week_grid() is shared: seller_id/week/
tenure_week carry no outcome information and are as-of safe by
construction.
"""

from __future__ import annotations

from collections import Counter, deque
from pathlib import Path

import numpy as np
import pandas as pd

from panel import STUDY_END, STUDY_START, WEEK_FREQ, seller_week_grid

TRAILING_WINDOW = 4

FEATURE_COLUMNS = [
    "cancel_rate_level", "cancel_rate_trend", "cancel_rate_accel",
    "ship_latency_level", "ship_latency_trend", "ship_latency_accel",
    "deliver_latency_level", "deliver_latency_trend", "deliver_latency_accel",
    "late_share_level", "late_share_trend", "late_share_accel",
    "order_volume_level", "order_volume_trend", "order_volume_accel",
    "aov_level", "aov_trend", "aov_accel",
    "volume_aov_interaction",
    "first_time_buyer_share_level", "first_time_buyer_share_trend", "first_time_buyer_share_accel",
    "review_score_level", "review_score_trend",
    "top_sku_revenue_share_level", "top_sku_revenue_share_trend", "top_sku_revenue_share_accel",
    "top_buyer_revenue_share_level", "top_buyer_revenue_share_trend", "top_buyer_revenue_share_accel",
    "tenure_weeks",
    "category",
]
assert len(FEATURE_COLUMNS) == 32, len(FEATURE_COLUMNS)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

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
    products = pd.read_csv(raw_dir / "olist_products_dataset.csv")
    category_translation = pd.read_csv(raw_dir / "product_category_name_translation.csv")
    customers = pd.read_csv(raw_dir / "olist_customers_dataset.csv")
    reviews = pd.read_csv(
        raw_dir / "olist_order_reviews_dataset.csv",
        parse_dates=["review_creation_date", "review_answer_timestamp"],
    )
    return {
        "orders": orders,
        "items": items,
        "products": products,
        "category_translation": category_translation,
        "customers": customers,
        "reviews": reviews,
    }


def _week_end(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period(WEEK_FREQ).dt.end_time.dt.normalize()


# --------------------------------------------------------------------------
# Base frames
# --------------------------------------------------------------------------

def build_item_frame(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per order item, with seller, order-lifecycle dates, category,
    and buyer identity attached. Trimmed to the study window by purchase
    timestamp, matching panel.py D1 so features and labels share the same
    seller/week universe.
    """
    orders = raw["orders"]
    items = raw["items"].merge(
        raw["products"][["product_id", "product_category_name"]], on="product_id", how="left"
    )
    items = items.merge(raw["category_translation"], on="product_category_name", how="left")
    items = items.merge(
        orders[
            [
                "order_id",
                "customer_id",
                "order_status",
                "order_purchase_timestamp",
                "order_delivered_carrier_date",
                "order_delivered_customer_date",
                "order_estimated_delivery_date",
            ]
        ],
        on="order_id",
        how="inner",
    )
    items = items.merge(raw["customers"][["customer_id", "customer_unique_id"]], on="customer_id", how="left")
    in_window = items["order_purchase_timestamp"].between(STUDY_START, STUDY_END)
    return items.loc[in_window].reset_index(drop=True)


def build_order_grain(item_frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per (order_id, seller_id): revenue summed across
    items, first-time-buyer flag computed from this seller's own order
    history strictly before this order (as-of safe by construction -- no
    future order can influence whether an earlier order counts as
    "first-time").
    """
    order_seller = item_frame.groupby(["order_id", "seller_id"], as_index=False).agg(
        order_status=("order_status", "first"),
        order_purchase_timestamp=("order_purchase_timestamp", "first"),
        order_delivered_carrier_date=("order_delivered_carrier_date", "first"),
        order_delivered_customer_date=("order_delivered_customer_date", "first"),
        order_estimated_delivery_date=("order_estimated_delivery_date", "first"),
        customer_unique_id=("customer_unique_id", "first"),
        revenue=("price", "sum"),
    )
    order_seller = order_seller.sort_values(["seller_id", "customer_unique_id", "order_purchase_timestamp"])
    order_seller["is_first_time_buyer"] = (
        order_seller.groupby(["seller_id", "customer_unique_id"]).cumcount() == 0
    )
    return order_seller


# --------------------------------------------------------------------------
# Weekly event tables, each attributed to the week its fact became knowable
# (see FEATURES.md's attribution table)
# --------------------------------------------------------------------------

def build_commitment_weekly(order_grain: pd.DataFrame) -> pd.DataFrame:
    df = order_grain.copy()
    df["week"] = _week_end(df["order_purchase_timestamp"])
    return df.groupby(["seller_id", "week"], as_index=False).agg(
        n_orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
        n_first_time=("is_first_time_buyer", "sum"),
    )


def build_ship_weekly(order_grain: pd.DataFrame) -> pd.DataFrame:
    df = order_grain[order_grain["order_delivered_carrier_date"].notna()].copy()
    df["week"] = _week_end(df["order_delivered_carrier_date"])
    df["ship_latency_days"] = (df["order_delivered_carrier_date"] - df["order_purchase_timestamp"]).dt.days
    return df.groupby(["seller_id", "week"], as_index=False).agg(
        n_shipped=("order_id", "nunique"),
        sum_ship_latency=("ship_latency_days", "sum"),
    )


def build_deliver_and_late_weekly(order_grain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    delivered = order_grain[order_grain["order_delivered_customer_date"].notna()].copy()
    delivered["week"] = _week_end(delivered["order_delivered_customer_date"])
    delivered["is_late"] = delivered["order_delivered_customer_date"] > delivered["order_estimated_delivery_date"]
    late_weekly = delivered.groupby(["seller_id", "week"], as_index=False).agg(
        n_delivered=("order_id", "nunique"),
        n_late=("is_late", "sum"),
    )

    latency = delivered[delivered["order_delivered_carrier_date"].notna()].copy()
    latency["deliver_latency_days"] = (
        latency["order_delivered_customer_date"] - latency["order_delivered_carrier_date"]
    ).dt.days
    deliver_latency_weekly = latency.groupby(["seller_id", "week"], as_index=False).agg(
        n_deliver_latency=("order_id", "nunique"),
        sum_deliver_latency=("deliver_latency_days", "sum"),
    )
    return deliver_latency_weekly, late_weekly


def build_resolution_weekly(order_grain: pd.DataFrame) -> pd.DataFrame:
    """Cancellation. Attributed to the order's own estimated_delivery_date
    week -- the best available proxy for "the point by which we'd expect to
    know the order's fate" (no cancellation timestamp exists in the raw
    data). See FEATURES.md.
    """
    df = order_grain.copy()
    df["week"] = _week_end(df["order_estimated_delivery_date"])
    df["is_cancelled"] = df["order_status"] == "canceled"
    return df.groupby(["seller_id", "week"], as_index=False).agg(
        n_resolved=("order_id", "nunique"),
        n_cancelled=("is_cancelled", "sum"),
    )


def build_review_weekly(order_grain: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    df = order_grain[["order_id", "seller_id", "order_purchase_timestamp"]].merge(
        reviews[["order_id", "review_score", "review_creation_date"]], on="order_id", how="inner"
    )
    # data-quality guard, not a leakage fix per se: ~0.075% of raw review
    # rows (74/99224) are dated before their own order's purchase timestamp
    # -- impossible (can't review something not yet bought), almost
    # certainly a duplicate/reused order_id artifact in the source data.
    # Caught by tests/test_no_lookahead.py: one such row attributed a
    # review to a week before the order (dated months later) had even been
    # placed, which the leakage test correctly flagged as inconsistent
    # between the full and future-hidden runs. Dropped here, not silently
    # -- see FAILURES.md.
    df = df[df["review_creation_date"] >= df["order_purchase_timestamp"]]
    df["week"] = _week_end(df["review_creation_date"])
    return df.groupby(["seller_id", "week"], as_index=False).agg(
        n_reviews=("review_score", "count"),
        sum_review_score=("review_score", "sum"),
    )


# --------------------------------------------------------------------------
# Generic level / trend / acceleration engine (see FEATURES.md for the
# convention: level = trailing-4-week pooled ratio, trend = OLS slope of
# the raw weekly ratio, accel = trend(W) - trend(W-1)).
# --------------------------------------------------------------------------

def _slope(y: np.ndarray) -> float:
    mask = ~np.isnan(y)
    if mask.sum() < 2:
        return np.nan
    x = np.arange(len(y))[mask]
    yv = y[mask]
    x_mean, y_mean = x.mean(), yv.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return np.nan
    return float(((x - x_mean) * (yv - y_mean)).sum() / denom)


def level_trend_accel(
    grid: pd.DataFrame, numerator: pd.Series, denominator: pd.Series, window: int = TRAILING_WINDOW
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """grid must be sorted by (seller_id, week), dense (every calendar week
    present per seller). numerator/denominator are aligned to grid's index,
    filled with 0 (not NaN) for weeks with no activity -- 0 is a valid
    count, "undefined" only arises from a 0 denominator.
    """
    seller = grid["seller_id"]
    g_num = numerator.groupby(seller)
    g_den = denominator.groupby(seller)

    roll_num = g_num.transform(lambda s: s.rolling(window, min_periods=1).sum())
    roll_den = g_den.transform(lambda s: s.rolling(window, min_periods=1).sum())
    level = roll_num / roll_den.replace(0, np.nan)

    raw_weekly = numerator / denominator.replace(0, np.nan)
    trend = raw_weekly.groupby(seller).transform(
        lambda s: s.rolling(window, min_periods=1).apply(_slope, raw=True)
    )
    accel = trend.groupby(seller).diff()  # NaN propagates automatically if either trend(W) or trend(W-1) is NaN
    return level, trend, accel


# --------------------------------------------------------------------------
# Concentration (top-1 revenue share by product_id / customer_unique_id)
# and expanding category mode -- both need per-seller sequential/windowed
# logic that doesn't reduce to a simple rolling sum, so implemented as an
# incremental sliding-window pass per seller.
# --------------------------------------------------------------------------

def _sliding_top_share(
    events: pd.DataFrame, grid: pd.DataFrame, key_col: str, window: int
) -> pd.Series:
    """events: seller_id, week, key_col, revenue (pre-aggregated).
    Returns a Series aligned to grid's index: top-1 revenue share within the
    trailing `window` calendar weeks (window=1 -> that single week only).
    """
    lookup: dict[tuple, dict] = {}
    for (seller_id, week, key), revenue in events.groupby(["seller_id", "week", key_col])["revenue"].sum().items():
        lookup.setdefault((seller_id, week), {})[key] = revenue

    out = np.full(len(grid), np.nan)
    pos = 0
    for seller_id, sub in grid.groupby("seller_id", sort=False):
        weeks = sub["week"].tolist()
        buf: deque = deque()
        combined: dict = {}
        for w in weeks:
            if len(buf) == window:
                old = buf.popleft()
                for k, v in old.items():
                    combined[k] -= v
                    if combined[k] <= 1e-9:
                        del combined[k]
            week_dict = lookup.get((seller_id, w), {})
            buf.append(week_dict)
            for k, v in week_dict.items():
                combined[k] = combined.get(k, 0.0) + v
            total = sum(combined.values())
            out[pos] = (max(combined.values()) / total) if combined and total > 0 else np.nan
            pos += 1
    return pd.Series(out, index=grid.index)


def _expanding_category_mode(item_frame: pd.DataFrame, grid: pd.DataFrame) -> pd.Series:
    items = item_frame.copy()
    items["week"] = _week_end(items["order_purchase_timestamp"])
    cats_by_seller_week = items.groupby(["seller_id", "week"])["product_category_name_english"].apply(list)

    out = np.full(len(grid), np.nan, dtype=object)
    pos = 0
    for seller_id, sub in grid.groupby("seller_id", sort=False):
        weeks = sub["week"].tolist()
        counter: Counter = Counter()
        for w in weeks:
            cats = cats_by_seller_week.get((seller_id, w), [])
            for c in cats:
                if pd.notna(c):
                    counter[c] += 1
            out[pos] = counter.most_common(1)[0][0] if counter else np.nan
            pos += 1
    return pd.Series(out, index=grid.index)


# --------------------------------------------------------------------------
# Top-level build
# --------------------------------------------------------------------------

def _attach(grid: pd.DataFrame, weekly: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    merged = grid.merge(weekly, on=["seller_id", "week"], how="left")
    merged[cols] = merged[cols].fillna(0.0)
    return merged


def build_features_from_raw(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    grid = seller_week_grid(raw).sort_values(["seller_id", "week"]).reset_index(drop=True)

    item_frame = build_item_frame(raw)
    order_grain = build_order_grain(item_frame)

    commitment_weekly = build_commitment_weekly(order_grain)
    ship_weekly = build_ship_weekly(order_grain)
    deliver_latency_weekly, late_weekly = build_deliver_and_late_weekly(order_grain)
    resolution_weekly = build_resolution_weekly(order_grain)
    review_weekly = build_review_weekly(order_grain, raw["reviews"])

    df = grid.copy()
    df = _attach(df, commitment_weekly, ["n_orders", "revenue", "n_first_time"])
    df = _attach(df, ship_weekly, ["n_shipped", "sum_ship_latency"])
    df = _attach(df, deliver_latency_weekly, ["n_deliver_latency", "sum_deliver_latency"])
    df = _attach(df, late_weekly, ["n_delivered", "n_late"])
    df = _attach(df, resolution_weekly, ["n_resolved", "n_cancelled"])
    df = _attach(df, review_weekly, ["n_reviews", "sum_review_score"])

    ones = pd.Series(1.0, index=df.index)

    out = df[["seller_id", "week", "tenure_week"]].copy()
    out["tenure_weeks"] = df["tenure_week"]

    out["cancel_rate_level"], out["cancel_rate_trend"], out["cancel_rate_accel"] = level_trend_accel(
        df, df["n_cancelled"], df["n_resolved"]
    )
    out["ship_latency_level"], out["ship_latency_trend"], out["ship_latency_accel"] = level_trend_accel(
        df, df["sum_ship_latency"], df["n_shipped"]
    )
    out["deliver_latency_level"], out["deliver_latency_trend"], out["deliver_latency_accel"] = level_trend_accel(
        df, df["sum_deliver_latency"], df["n_deliver_latency"]
    )
    out["late_share_level"], out["late_share_trend"], out["late_share_accel"] = level_trend_accel(
        df, df["n_late"], df["n_delivered"]
    )
    out["order_volume_level"], out["order_volume_trend"], out["order_volume_accel"] = level_trend_accel(
        df, df["n_orders"], ones
    )
    out["aov_level"], out["aov_trend"], out["aov_accel"] = level_trend_accel(
        df, df["revenue"], df["n_orders"]
    )
    out["volume_aov_interaction"] = out["order_volume_trend"].clip(lower=0) * (-out["aov_trend"]).clip(lower=0)

    out["first_time_buyer_share_level"], out["first_time_buyer_share_trend"], out["first_time_buyer_share_accel"] = (
        level_trend_accel(df, df["n_first_time"], df["n_orders"])
    )

    out["review_score_level"], out["review_score_trend"], _ = level_trend_accel(
        df, df["sum_review_score"], df["n_reviews"]
    )

    sku_events = item_frame.assign(week=_week_end(item_frame["order_purchase_timestamp"])).groupby(
        ["seller_id", "week", "product_id"], as_index=False
    )["price"].sum().rename(columns={"price": "revenue"})
    buyer_events = order_grain.assign(week=_week_end(order_grain["order_purchase_timestamp"])).groupby(
        ["seller_id", "week", "customer_unique_id"], as_index=False
    )["revenue"].sum()

    out["top_sku_revenue_share_level"] = _sliding_top_share(sku_events, grid, "product_id", TRAILING_WINDOW)
    sku_raw = _sliding_top_share(sku_events, grid, "product_id", 1)
    out["top_sku_revenue_share_trend"] = sku_raw.groupby(grid["seller_id"]).transform(
        lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).apply(_slope, raw=True)
    )
    out["top_sku_revenue_share_accel"] = out["top_sku_revenue_share_trend"].groupby(grid["seller_id"]).diff()

    out["top_buyer_revenue_share_level"] = _sliding_top_share(buyer_events, grid, "customer_unique_id", TRAILING_WINDOW)
    buyer_raw = _sliding_top_share(buyer_events, grid, "customer_unique_id", 1)
    out["top_buyer_revenue_share_trend"] = buyer_raw.groupby(grid["seller_id"]).transform(
        lambda s: s.rolling(TRAILING_WINDOW, min_periods=1).apply(_slope, raw=True)
    )
    out["top_buyer_revenue_share_accel"] = out["top_buyer_revenue_share_trend"].groupby(grid["seller_id"]).diff()

    out["category"] = _expanding_category_mode(item_frame, grid)

    out = out.drop(columns=["tenure_week"])
    return out[["seller_id", "week"] + FEATURE_COLUMNS]


def build_features(raw_dir: Path) -> pd.DataFrame:
    return build_features_from_raw(load_raw(raw_dir))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/seller_week_features.csv"))
    args = parser.parse_args()

    features = build_features(args.raw_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.out, index=False)
    print(f"[features] wrote {len(features)} rows, {len(FEATURE_COLUMNS)} feature columns -> {args.out}")


if __name__ == "__main__":
    main()
