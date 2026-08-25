"""No-look-ahead leakage tests for the Phase 1 feature pipeline.

Written before features.py's implementation is finished, per the working
agreement: leakage should be caught by a test that fails loudly, not found
by inspection after the fact.

Two complementary checks:

1. test_features_unchanged_when_future_hidden -- the general check. Build
   features once from the full raw data, once from raw data with every
   date field after a cutoff surgically blanked out (orders that hadn't
   happened yet are dropped; lifecycle dates that hadn't happened yet by
   the cutoff are set to NaT; order_status is masked wherever its
   resolution point, estimated_delivery_date, is still in the future).
   Every feature value for a week at or before the cutoff must be
   IDENTICAL between the two runs -- if it isn't, that column depended on
   information that, at the cutoff, didn't exist yet.

2. test_synthetic_future_order_does_not_leak -- a single, easy-to-reason-
   about injection: add one extreme synthetic order dated after a target
   week, rebuild, and check the target week's row is untouched, while
   confirming the synthetic order DOES show up in a later week (so the
   test isn't vacuously passing because the injected row was dropped for
   an unrelated reason).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from features import FEATURE_COLUMNS, build_features_from_raw

# A cutoff well inside the study window, chosen arbitrarily but fixed so
# the test is deterministic. Set to the END of that W-SUN week (23:59:59),
# not midnight -- "week" values from _week_end() are midnight-normalized
# week-end dates, so a midnight cutoff would wrongly clip same-day orders
# that occur later on the cutoff week's own last day (found by this test
# during development: 236 orders on 2018-03-04 alone occur after 00:00:00).
CUTOFF = pd.Timestamp("2018-03-04 23:59:59.999999")

# `raw` fixture (session-scoped) lives in conftest.py, shared with
# test_no_seller_identity.py.


def truncate_raw(raw: dict[str, pd.DataFrame], cutoff: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Simulate standing at `cutoff` with nothing after it known yet.

    - Orders purchased after cutoff: dropped entirely (they haven't
      happened).
    - Orders purchased by cutoff, but whose carrier/delivery dates are
      after cutoff: those specific dates blanked to NaT (hasn't shipped /
      hasn't arrived yet, even though the order itself exists).
    - order_status masked to NaN wherever its resolution point
      (estimated_delivery_date) is still after cutoff -- we can't yet know
      an order's final fate before we've even reached the point we'd
      expect to know it (see FEATURES.md's cancellation-attribution note).
    - order_items / reviews: filtered to rows whose parent order survives
      / whose review was actually submitted by cutoff.
    """
    orders = raw["orders"].copy()
    orders = orders[orders["order_purchase_timestamp"] <= cutoff].copy()

    future_carrier = orders["order_delivered_carrier_date"] > cutoff
    orders.loc[future_carrier, "order_delivered_carrier_date"] = pd.NaT

    future_delivered = orders["order_delivered_customer_date"] > cutoff
    orders.loc[future_delivered, "order_delivered_customer_date"] = pd.NaT

    future_resolution = orders["order_estimated_delivery_date"] > cutoff
    orders.loc[future_resolution, "order_status"] = np.nan

    surviving_orders = set(orders["order_id"])

    items = raw["items"]
    items = items[items["order_id"].isin(surviving_orders)].copy()

    reviews = raw["reviews"]
    reviews = reviews[reviews["order_id"].isin(surviving_orders)].copy()
    reviews = reviews[reviews["review_creation_date"] <= cutoff].copy()

    out = dict(raw)
    out["orders"] = orders
    out["items"] = items
    out["reviews"] = reviews
    return out


def _assert_columns_match(full_row: pd.Series, trunc_row: pd.Series, context: str) -> None:
    mismatches = []
    for col in FEATURE_COLUMNS:
        a, b = full_row[col], trunc_row[col]
        both_nan = (pd.isna(a) and pd.isna(b))
        if both_nan:
            continue
        if isinstance(a, (int, float, np.floating, np.integer)) and isinstance(b, (int, float, np.floating, np.integer)):
            if not np.isclose(a, b, equal_nan=True, atol=1e-9, rtol=1e-9):
                mismatches.append((col, a, b))
        elif a != b:
            mismatches.append((col, a, b))
    assert not mismatches, (
        f"look-ahead leakage detected at {context}: feature value(s) changed when "
        f"future data was hidden -- {mismatches}"
    )


def test_features_unchanged_when_future_hidden(raw):
    full = build_features_from_raw(raw)
    truncated = build_features_from_raw(truncate_raw(raw, CUTOFF))

    full_upto = full[full["week"] <= CUTOFF].set_index(["seller_id", "week"])
    trunc_upto = truncated[truncated["week"] <= CUTOFF].set_index(["seller_id", "week"])

    common_idx = full_upto.index.intersection(trunc_upto.index)
    assert len(common_idx) > 100, "sanity check: too few overlapping rows to test meaningfully"

    checked = 0
    for idx in common_idx:
        _assert_columns_match(full_upto.loc[idx], trunc_upto.loc[idx], context=f"seller={idx[0]}, week={idx[1].date()}")
        checked += 1
    assert checked == len(common_idx)


def test_truncation_actually_removed_information(raw):
    """Sanity check that truncate_raw isn't a no-op -- if it were, the test
    above would pass vacuously."""
    truncated = truncate_raw(raw, CUTOFF)
    assert len(truncated["orders"]) < len(raw["orders"])
    assert (truncated["orders"]["order_purchase_timestamp"] <= CUTOFF).all()
    assert truncated["orders"]["order_delivered_carrier_date"].max() <= CUTOFF or pd.isna(
        truncated["orders"]["order_delivered_carrier_date"].max()
    )


def test_synthetic_future_order_does_not_leak(raw):
    orders = raw["orders"].copy()
    items = raw["items"].copy()

    # pick a real seller with orders on both sides of an interior week, so
    # the panel already has a well-formed row for it at TARGET_WEEK
    target_week = pd.Timestamp("2018-02-04")
    seller_id = raw["items"]["seller_id"].value_counts().index[0]  # a high-volume seller

    future_purchase = target_week + pd.Timedelta(weeks=6)
    synthetic_order_id = "SYNTHETIC-FUTURE-ORDER-0001"
    synthetic_order = pd.DataFrame([{
        "order_id": synthetic_order_id,
        "customer_id": "SYNTHETIC-CUSTOMER-0001",
        "order_status": "canceled",
        "order_purchase_timestamp": future_purchase,
        "order_approved_at": future_purchase,
        "order_delivered_carrier_date": pd.NaT,
        "order_delivered_customer_date": pd.NaT,
        "order_estimated_delivery_date": future_purchase + pd.Timedelta(days=1),
    }])
    synthetic_item = pd.DataFrame([{
        "order_id": synthetic_order_id,
        "order_item_id": 1,
        "product_id": "SYNTHETIC-PRODUCT-0001",
        "seller_id": seller_id,
        "shipping_limit_date": future_purchase,
        "price": 999999.0,  # extreme value -- would visibly distort AOV/volume/concentration if it leaked
        "freight_value": 0.0,
    }])

    raw_baseline = dict(raw)
    raw_injected = dict(raw)
    raw_injected["orders"] = pd.concat([orders, synthetic_order], ignore_index=True)
    raw_injected["items"] = pd.concat([items, synthetic_item], ignore_index=True)

    baseline_features = build_features_from_raw(raw_baseline)
    injected_features = build_features_from_raw(raw_injected)

    baseline_row = baseline_features[
        (baseline_features["seller_id"] == seller_id) & (baseline_features["week"] == target_week)
    ]
    injected_row = injected_features[
        (injected_features["seller_id"] == seller_id) & (injected_features["week"] == target_week)
    ]
    assert len(baseline_row) == 1 and len(injected_row) == 1

    _assert_columns_match(
        baseline_row.iloc[0], injected_row.iloc[0],
        context=f"synthetic future order injected 6 weeks after target week for seller={seller_id}",
    )

    # sanity: the synthetic order DOES change a later week's volume, proving
    # the injection itself was live and the test above wasn't vacuous.
    future_week = future_purchase.to_period("W-SUN").end_time.normalize()
    baseline_future = baseline_features[
        (baseline_features["seller_id"] == seller_id) & (baseline_features["week"] == future_week)
    ]
    injected_future = injected_features[
        (injected_features["seller_id"] == seller_id) & (injected_features["week"] == future_week)
    ]
    assert len(baseline_future) == 1 and len(injected_future) == 1
    assert (
        injected_future.iloc[0]["order_volume_level"] != baseline_future.iloc[0]["order_volume_level"]
    ), "sanity check failed: synthetic order had no effect anywhere -- test may be vacuous"
