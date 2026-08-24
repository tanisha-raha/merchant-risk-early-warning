# Features

32 columns (brief's ceiling is 40) over the seller-week panel. Built by
`src/features.py`, tested for look-ahead leakage by
`tests/test_no_lookahead.py` — written before `features.py`'s
implementation was finished, per instruction. Two checks: rebuild features
from raw data with every timestamp after a cutoff surgically hidden and
require every feature value at or before the cutoff to be byte-identical
to the full run; and a single synthetic future order injected 6 weeks
ahead, checked not to move an earlier week's row. Both runs caught real
bugs during development (one in the test itself, one in the review-date
data) — see `FAILURES.md` F5/F6 and `DECISIONS.md` D9.

## Design: level / trend / acceleration, and why they're not the same window

For every family below (except review score, per the brief's literal
wording, and the interaction term, which is derived from two already-built
trend columns):

- **level(W)** = a trailing 4-week *pooled* aggregate ending at week W —
  for rate features, `sum(numerator, W-3..W) / sum(denominator, W-3..W)`,
  not a mean of weekly rates. Matches the convention already used and
  justified for the Phase 0 label definitions (`DECISIONS.md` D4): most
  sellers place 1-2 orders/week, so a single week's rate is almost always
  exactly 0 or 1 and not meaningfully "the level" of anything.
- **trend(W)** = OLS slope of the **raw, unsmoothed weekly value** over
  weeks [W-3, W] (4 points, x = 0..3), dropping weeks where the weekly
  value is undefined (e.g. a rate with zero orders that week). Deliberately
  *not* the slope of the smoothed level series — the brief's hypothesis is
  about catching "2% → 4% → 7% over three weeks," which is a statement
  about the raw week-to-week series, not a slope-of-a-moving-average.
  Requires ≥2 non-null weekly points in the window; else NaN.
- **acceleration(W)** = `trend(W) - trend(W-1)`. Requires trend to be
  defined at both W and W-1.

Consequence: `level` is available as soon as a seller has ≥1 order in the
trailing window; `trend` needs data spread over ≥2 of the 4 trailing
weeks; `acceleration` needs that at W and at W-1, i.e. meaningfully often
not available until ~7-8 weeks of tenure. This is a real, informative kind
of missingness (a brand-new seller genuinely has no trend yet), not a bug
— Phase 2 needs to decide how the model handles it (missing-indicator vs.
tree-based NaN handling), not features.py.

## As-of design: event-attribution week, not purchase week

`panel.py` builds the **label** panel using each order's *final* recorded
outcome (status, delivered date, etc.), attributed to the order's
*purchase* week — correct for a label (we're allowed to know the full
outcome when defining ground truth) and explicitly documented as unsafe to
reuse as a feature (`panel.py` module docstring).

Features must reflect what would actually be knowable at week W in
production, so every feature here is attributed to the week its
**underlying fact became knowable**, not the order's purchase week:

| Signal | Attributed to | Why |
|---|---|---|
| Order placed (volume, AOV, first-time-buyer, concentration, category) | purchase week | Known the instant the order is placed — nothing to wait for. |
| Shipped (order → ship latency) | week of `order_delivered_carrier_date` | Doesn't exist until the seller actually ships. |
| Delivered / late (ship → delivery latency, late-delivery share) | week of `order_delivered_customer_date` | Doesn't exist until the order actually arrives. An order still in transit past its estimate contributes to *nothing* yet — it's genuinely unresolved, which is the correct real-time state, not a gap to fill in. |
| Cancelled (refund/cancellation rate) | week of `order_estimated_delivery_date` | The raw data has no cancellation timestamp — this is the best available proxy for "the point by which we'd expect to know the order's fate." An order isn't counted as cancelled-or-not until its own estimated delivery date has passed. This likely places cancellation knowledge *later* than it would be in reality (a real payments system would learn of some cancellations near-instantly) — a conservative, documented approximation, not a precise one. |
| Review submitted (review score) | week of `review_creation_date` | Doesn't exist until the buyer actually reviews — typically after delivery, so review-score features lag by construction. |

This is why features.py does **not** reuse `panel.py`'s weekly aggregates
(D2's `n_cancelled`, `n_late`, etc. are purchase-week-attributed finals) —
it rebuilds its own event tables from the raw CSVs, each dated by the
column above, and only borrows the (seller_id, week, tenure_week) grid
(`panel.seller_week_grid`), which carries no outcome information and is
as-of safe by construction.

## Columns

### Refund / cancellation (1 family, 3 cols)
- `cancel_rate_level`, `cancel_rate_trend`, `cancel_rate_accel` — share of
  orders (with resolution week ≤ W) that ended cancelled. Olist has no
  refund table; cancellation is the only available proxy for the brief's
  "refund and cancellation rate" — a real dataset-vs-target mismatch, not
  hidden (see `PHASE0_FINDINGS.md` limitations).

### Fulfilment latency + late-delivery (3 families, 9 cols)
- `ship_latency_level/trend/accel` — days from purchase to carrier
  handoff, among orders shipped by week W.
- `deliver_latency_level/trend/accel` — days from carrier handoff to
  customer delivery, among orders delivered by week W.
- `late_share_level/trend/accel` — share of orders delivered by week W
  where `delivered_customer_date > estimated_delivery_date`.

### Volume and AOV (2 families + interaction, 7 cols)
- `order_volume_level/trend/accel` — orders placed, purchase-week
  attributed.
- `aov_level/trend/accel` — mean order value (item price sum per order),
  purchase-week attributed.
- `volume_aov_interaction` — `max(order_volume_trend, 0) * max(-aov_trend, 0)`.
  Zero unless volume is rising *and* AOV is falling simultaneously; grows
  with both magnitudes. Built from the two trend columns above, not
  recomputed from raw — as-of safety inherits from them directly.

### First-time buyer share (1 family, 3 cols)
- `first_time_buyer_share_level/trend/accel` — share of a week's orders
  from a `customer_unique_id` who has never bought from this seller before
  (checked against that seller's own order history strictly before the
  order's own timestamp — as-of safe by construction, no future orders
  involved even implicitly).

### Review score (1 family, 2 cols — no acceleration, per the brief's literal wording)
- `review_score_level`, `review_score_trend` — mean review score,
  review-submission-week attributed. Sparse: most seller-weeks have zero
  reviews landing in them even when orders are flowing, since reviews lag
  delivery by design. Review rows dated before their own order's purchase
  timestamp (74/99,224, a raw-data artefact) are dropped before attribution
  — found by `tests/test_no_lookahead.py`, see `DECISIONS.md` D9.

### Concentration (2 families, 6 cols)
- `top_sku_revenue_share_level/trend/accel` — revenue share of the
  single best-selling `product_id`, computed within the same trailing
  4-week window as everything else.
- `top_buyer_revenue_share_level/trend/accel` — same, by
  `customer_unique_id`.

Caveat, stated plainly rather than hidden: with a median seller placing
1-2 orders/week, a 4-week window often contains only a handful of orders,
so concentration will be trivially close to 100% for many small-seller
rows. That's an accurate reflection of small-seller reality, not a
computation bug, but it means this feature mostly discriminates for
higher-volume sellers — worth checking in Phase 4's slice analysis.

### Tenure and category (2 cols)
- `tenure_weeks` — weeks since first order (0-indexed), from the shared
  grid. Monotonic by construction; no trend/accel form (a constant slope
  of 1 tells you nothing).
- `category` — the seller's most common `product_category_name_english`
  among items sold from tenure start **through week W** (expanding count,
  not all-time), so a seller who shifts category mix over time doesn't
  leak its future dominant category into earlier weeks. Left as a single
  categorical column here; Phase 2's `model.py` owns the encoding
  (dummy/target/frequency) — that's a modelling decision, not a Phase 1
  one, and one-hot-encoding ~70 raw categories here would blow well past
  the 40-column ceiling for no benefit at this stage.

**Total: 32 columns** (3+3+3+3+3+3+1+3+2+3+3+1+1), plus `seller_id` and
`week` as identifiers (not counted as features).
