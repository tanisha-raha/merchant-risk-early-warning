# Decisions

One entry per consequential choice: what we chose, what we rejected, why.
Ordered chronologically.

## Phase 0

### D1 — Study window trimmed to 2017-01-01 – 2018-08-26

**Chose:** build the seller-week panel only from orders with
`order_purchase_timestamp` in `[2017-01-01, 2018-08-26]`; discard everything
outside it as if it were never collected.

**Rejected:** using the raw dataset's full span (2016-09-04 to 2018-10-17).

**Why:** the weekly order-volume plot (`figures/phase0_calendar_coverage.png`)
shows two artefacts, not signal:
- 2016-09 through 2016-12 is a soft-launch: one week of ~320 orders
  (2016-10-03/09), then near-silence until January 2017. A seller only
  active in this period is indistinguishable from a seller who onboarded
  and immediately churned — there's no surrounding data to tell the
  difference.
- The week of 2018-08-27 onward collapses from ~1,900 orders/week to
  double, then single, digits inside two weeks. This is the dataset export
  cutting off mid-collection, not a mass simultaneous merchant failure.

Including either range would make cessation and truncation indistinguishable
by construction. Trimming costs us ~0.5% of (order, seller) rows and some
real seller history from late 2016, which is a real cost — it's a tradeoff,
not a free cleanup, and it's why it's logged here rather than done silently
inside the panel code.

**Consequence:** `STUDY_END` (2018-08-26) doubles as the administrative
censoring point — any seller still active near it is right-censored, not
observed to fail, regardless of how long the remaining silence looks. (This
turned out to be an incomplete fix — see D6.)

### D2 — Panel grain: one row per (seller_id, week), week = Mon–Sun ending Sunday

**Chose:** `pandas` `W-SUN` period, keyed off `order_purchase_timestamp`.
Panel starts at each seller's first order week (within the study window)
and runs to `STUDY_END`, including zero-order weeks explicitly.

**Why:** `order_purchase_timestamp` is the only order-table timestamp with
zero nulls (approval/carrier/delivery dates all have missing values), and
it's the earliest, most "as-of-safe" of the available timestamps — a good
anchor for later Phase 1 feature work.

**Consequence for multi-seller orders:** an order with items from more than
one seller produces one row per seller in the intermediate order-seller
frame; order-level fields (status, cancellation, delivery dates) are shared
across those rows since the raw data has no seller-specific order status.
This is a simplification — noted, not hidden.

### D3 — Eligibility filter for cessation-style definitions: ≥4 total orders and ≥3 distinct active weeks

**Chose:** a seller only enters the risk set for the cessation-based
candidates (A, B) if it placed at least 4 orders across at least 3 distinct
weeks within the study window. 1,919 of 3,065 sellers (62.6%) qualify.

**Rejected:** no floor (every seller with ≥1 order eligible).

**Why:** median seller lifetime spend is ~7 orders total and a quarter of
all sellers place only 1–2 orders ever. For those, "cessation" is not a
meaningful concept — a seller with one order trivially "ceases" the
following week regardless of health, since there was never a baseline
cadence to depart from. The threshold is a judgement call, not derived from
theory — **flagged for your sign-off**, along with the candidate-definition
choice in `PHASE0_FINDINGS.md`.

**Confirmed 2026-08-23, still an arbitrary default:** kept as-is. It
excludes 1,146 of 3,065 sellers (37.4% of the seller count) but only
$438,803 of $13,523,076 in-window GMV (3.2%). The floor is doing what it's
supposed to — dropping a large share of sellers who each carry almost no
revenue — but the specific numbers 4 and 3 are still not derived from
anything beyond "median seller places ~7 orders total," and should be
revisited if Phase 1/2 results look sensitive to it.

### D4 — "Elevated" quality thresholds: trailing 4-week cancel rate > 0.10 OR late-delivery rate > 0.50

**Chose:** these two cutoffs, applied to a trailing 4-week pooled rate
(sum of cancellations or late deliveries over the last 4 weeks, divided by
sum of orders/deliveries over the same weeks — not a mean of weekly rates,
which would be dominated by weeks with 1–2 orders).

**Why these numbers:** chosen from the empirical cross-sectional
distribution of trailing rates across all active-seller-weeks, roughly the
99th percentile for cancellation and 95th for late-delivery (see
`FAILURES.md` for why cancellation needed a much more extreme cutoff to
mean anything). Not a theoretically derived number — a candidate default,
open to revision once we see how much it drives Candidate A's event count
(see `PHASE0_FINDINGS.md`).

**Trailing window = 4 weeks:** chosen to match the Phase 1 trend-window
convention (brief specifies trailing-4-week slopes for feature trends), so
the same window means the same thing in the label definition and in the
features that will later predict it.

### D5 — Event definition: pure cessation (Candidate B), N=8 primary, N=4/N=12 carried as a robustness check

**Chose:** distress event = pure cessation, no quality precondition in the
label (Candidate B). N=8 weeks of silence is primary; N=4 and N=12 are not
dropped after Phase 0 — all three get carried through Phase 1–4 so the
headline lead-time/economic results can be checked for sensitivity to N,
not reported against a single arbitrarily-chosen threshold.

**Rejected:** Candidate A (cessation + elevated quality precondition) —
undershoots the ~150-event kill floor (71–91 events) and is circular if
cancel/late-rate features are later used as predictors of a label partly
defined by cancel/late rate (FAILURES.md F2). Candidate C (quality collapse,
no cessation) — same circularity, more acutely (its label *is* the
elevated-quality condition).

**Why N=8:** roughly the 95th percentile of the empirical gap distribution
between a still-active seller's consecutive order weeks (90th pct = 5
weeks, 95th = 8, 99th = 18) — chosen so an 8-week silence is genuinely
unusual rather than an ordinary lull. Still a judgement call on a noisy
distribution, not a hard boundary — hence carrying N=4/N=12 forward rather
than treating N=8 as settled.

### D6 — Right-edge event confirmation: excluded from the label

**Finding:** under pure cessation, 22–35% of confirmed events (depending on
N) had their confirmation date in just the last N weeks before `STUDY_END`
— a calendar-time window that is only 5–14% of the full 86-week study. The
weekly hazard rate visibly spiked in the final few weeks before `STUDY_END`
for every N tested (`figures/phase0_calendar_hazard.png`, `FAILURES.md`
F3). Trimming to `STUDY_END` (D1) removed the calendar-volume truncation
artefact but not this second, subtler one: events confirmed with the
bare-minimum N-week margin cluster right where that margin is thinnest.

**Chose:** exclude the edge window from the label entirely. An event whose
confirmation date (`last_active_week + N`) falls within the final N weeks
before `STUDY_END` is treated as **censored at STUDY_END**, not as an
event — same treatment as any other seller without enough follow-up to
confirm. Implemented in `src/distress_events.py`
(`compute_cessation_candidates`, `in_edge_zone`). Equivalent to requiring
`silence_weeks_observed >= 2*N`, but stated as "exclude the last N weeks of
possible confirmations" because that's the more legible framing of what's
being thrown out and why.

**Cost:** event counts drop from 858/665/550 (N=4/8/12, pre-exclusion) to
665/477/357 (post-exclusion) — all three remain comfortably above the
150-event kill floor. Confirmed via `src/phase0_calendar_hazard.py`: 0% of
events now fall in the excluded zone, by construction.

**Rejected alternative — calendar-time as a model covariate:** the other
option on the table was to leave the labels as-is and let the Phase 2
hazard model control for calendar time explicitly (alongside tenure), so
it could statistically absorb the right-edge effect rather than have it
bias raw estimates. **Rejected because it would let the model learn the
artefact rather than see past it.** The later (test) window is exactly
where the artefact concentrates (D7), so a model with calendar time as a
covariate — evaluated on a later window with the same directional bias
(hazard rising toward the boundary) baked into training — could pick up
"time is close to the data cutoff" as a predictive feature and inflate
apparent test-set performance without learning anything about real
merchant distress. That would not generalise to production, where there is
no future data cutoff to exploit. Removing the contaminated labels at the
source is more conservative than asking a covariate to statistically paper
over them. **This reasoning belongs in the README methodology/limitations
section, not just here.**

### D7 — Provisional Phase 2 test-window width: last 26 weeks (~30% of the study)

**Chose (provisional — Phase 2 will need to confirm the exact split
mechanics):** a ~26-week test window (test start ≈ 2018-02-25) as the
working assumption for how much calendar time to hold out, checked against
post-D6-exclusion event counts in `src/phase0_calendar_hazard.py`
(`CANDIDATE_TEST_WIDTHS_WEEKS`).

**Why:** the binding constraint is the strictest robustness variant,
N=12 — a 13-week test window gives it only 13 events (unusable; the whole
point of D5's robustness check is to detect if the headline result depends
on N, and 13 events can't support that on its own), 17 weeks gives 63, and
only 20+ weeks clears 100. A 26-week window gives 151/237/390 test events
for N=12/8/4 respectively — comparable in order of magnitude to the
original ~150-event viability floor for N=12, and comfortably above it for
N=8/4. This is not generous headroom for N=12 specifically, and Phase 4
should treat N=12's test-window results as the least statistically stable
of the three when they're compared.

**Not fully resolved:** this only checks raw event *counts* by confirmation
date in a naive calendar cutpoint — it does not yet address how
seller-weeks that straddle the boundary get assigned, how base-rate drift
between train/test gets reported (required by the brief), or whether 26
weeks is still right once Phase 1 features are in place. Phase 2 owns
finalising the split.

## Phase 1

### D8 — Feature attribution: event week, not purchase week; level/trend/acceleration convention

**Chose:** every feature is attributed to the week its underlying fact
became *knowable* (order → ship → deliver → review each get their own
attribution week; cancellation is attributed to the order's own
`order_estimated_delivery_date` week, the best available proxy given the
raw data has no cancellation timestamp), not to the order's purchase week.
`level(W)` = trailing-4-week pooled ratio; `trend(W)` = OLS slope of the
raw (unsmoothed) weekly value over the same 4 weeks; `acceleration(W)` =
`trend(W) - trend(W-1)`. Full rationale and the attribution table are in
`FEATURES.md` rather than duplicated here, since that file is the
per-column spec.

**Why logged as a decision, not just documentation:** this determines what
"leakage-free" even means for this project, and it's an interpretation of
the brief's words ("level, trend, acceleration... as-of the week in
question"), not something derivable from the data alone. Implemented
without a pre-approval question — flagged here for review rather than
gated on it, consistent with how Phase 0's D2/D4 windowing conventions were
handled. Say so if any part of it should change.

### D9 — Review rows dated before their own order's purchase are dropped

**Found by `tests/test_no_lookahead.py`** (written before features.py was
finished, per your instruction): 74 of 99,224 raw review rows (0.075%) have
`review_creation_date` earlier than their own order's
`order_purchase_timestamp` — a data-quality artefact (almost certainly a
reused/duplicated `order_id` in the reviews table), not a real event. One
such row caused the leakage test to fail during development: a review
dated January 2018 attached to an order actually purchased in April 2018,
which the test correctly flagged as a January feature value that
disappeared when April's data was hidden.

**Chose:** drop any review row where `review_creation_date <
order_purchase_timestamp`. Full writeup in `FAILURES.md`.

## Phase 2

### D10 — Correction to the brief: "no seller in both" is infeasible for a discrete-time hazard panel, and unnecessary

**The brief says** (Phase 2): "Split by time, never randomly... Group by
seller so no seller appears in both." That instruction was written with a
classification-style, one-row-per-subject setup in mind, where grouping by
subject prevents a subject's other rows from leaking into evaluation of
its held-out rows. **It doesn't transfer to a discrete-time hazard panel,
and enforcing it literally breaks the model.**

**Checked, not assumed:** at the provisional 26-week test cutoff
(2018-02-25, D7) with N=8, of 1,919 eligible sellers: 240 have their whole
observation window end before the cutoff (all 240 are events — a seller
only "ends" before the cutoff if it failed there; every censored seller's
window runs to `STUDY_END`, past the cutoff, by construction) — that's a
training set with **zero censored examples**, unusable for a hazard model,
which needs both outcomes to learn anything. 485 sellers start entirely
after the cutoff (only 9 events among them — barely anything to evaluate).
The remaining 1,194 (62%) straddle the boundary and can't be assigned to
either side without one of those two broken outcomes.

**Chose:** a row-level time split. Train = seller-week rows with
`week <= cutoff`; test = `week > cutoff`. A seller active on both sides of
the cutoff contributes rows to both sets.

**Why this doesn't reintroduce the leakage "group by seller" was meant to
prevent:** the classic risk is a model learning subject-specific
fingerprints from a subject's train rows, then getting unearned credit
recognizing the same subject in test. That requires the model to have
*something* that identifies the subject. No feature is `seller_id` or
functions as one — checked by `tests/test_no_seller_identity.py`
(confirms no column is literally a seller key, and that no column is
close to constant across a seller's own history, which would make it a
de facto fingerprint even without being named `seller_id`). Every feature
is a trailing-window, as-of-the-week statistic (Phase 1, D8) — a seller's
train-period rows carry information about that seller's *past*, and
predicting its *future* risk from a model that generalizes across all
sellers' past-to-future patterns is exactly what a hazard model is
supposed to do. That is not leakage; it's the task.

**Checked (per your request) — does the model actually perform
suspiciously better on straddling sellers than on the 485 test-only
ones?** No — if anything, the opposite. Test-set AUC by group
(`src/model.py`'s `straddler_check`, primary N=8): straddler rows (seller
also has train rows) AUC = 0.896 on 27,473 rows / 228 events;
test-only rows (seller never appears in train) AUC = 0.963 on 7,380 rows /
only 9 events. Same direction at N=4 (0.967 vs. 0.974) and N=12 (0.866 vs.
undefined — the test-only group has zero events at N=12, so no AUC is
computable there). Test-only performance is as good as or better than
straddler performance at every N checked, the opposite of what a seller-
fingerprint leak would produce. Caveat: the test-only groups are small and
event-sparse (9, 39, and 0 events respectively), so these comparisons are
noisy, especially at N=8/N=12 — but the direction is consistent across all
three, which is the relevant signal, not any single point estimate.
**No evidence the row-level split is leaking anything the no-fingerprint
argument missed.**

**This belongs in the README methodology section** as a stated correction
to the brief's original assumption, not a deviation quietly taken.

### D11 — Missingness: indicators + zero-fill, not imputation; category by frequency encoding; discrete-time hazard only

**Missingness.** Per your instruction: trend/acceleration missingness is
signal ("too young to have a trend"), not noise to impute away. Extended
the same logic to **level** missingness too (e.g. `aov_level` is NaN when
a seller had zero orders in the trailing 4 weeks) — "currently completely
inactive" is exactly the same kind of informative-missing case, just a
different cause (lull vs. youth) from trend/accel's.

Checked before implementing (not assumed) how much this costs against the
40-column ceiling you asked to track: a naive one-indicator-per-column
scheme would add up to 18 columns (32 + 18 = 50, blowing the ceiling).
Checked which columns' missingness masks are actually driven by the same
underlying cause and can share one indicator:
- `aov`, `first_time_buyer_share`, `top_sku_revenue_share`,
  `top_buyer_revenue_share` all key off the same denominator
  (orders-placed-that-week) — their trend-missingness masks are **exactly
  identical**, verified directly on the built feature table, not assumed
  from the formulas. One shared indicator.
- `deliver_latency` and `late_share` both key off delivered-that-week
  counts — masks identical except 1 row out of 133,734 (an order
  delivered without a recorded carrier date). One shared indicator (OR of
  the two conditions, so that one-row edge case is still covered).
- `cancel_rate`, `ship_latency`, `review_score` each key off a genuinely
  different event (resolution date, ship date, review date) — kept
  separate.
- `order_volume`'s trend/accel is only ever missing in a seller's first
  1-2 weeks of tenure (window too young to have 2 points) — which
  `tenure_weeks` (already a feature) captures exactly and losslessly. No
  indicator added; would be redundant.
- `volume_aov_interaction` is built from `order_volume_trend` (never
  missing) and `aov_trend` — reuses the `aov` group's indicator rather
  than adding its own.
- `category`'s 2.4% missingness (unmapped product category in the raw
  data) is folded into frequency encoding as its own "unknown" bucket
  (see below) rather than a separate indicator column.

**Result: 5 added indicator columns** (`cancel_rate_history_missing`,
`ship_latency_history_missing`, `delivery_history_missing`,
`commitment_history_missing`, `review_history_missing`), each 1/0 = "this
family's derived stats are zero-filled here, not real." **32 + 5 = 37
model-matrix columns**, still under the 40 ceiling. All NaN feature values
(level, trend, and accel alike) zero-filled after the indicators are set.

**Category: frequency encoding, not one-hot.** ~70 raw categories would
add ~70 columns for a one-hot scheme, blowing the ceiling for a feature
that's mostly stable per seller anyway (80.6% constant across a seller's
own history — see D10's fingerprint check). Encoded as each category's
share of eligible-seller-weeks (a single numeric column, replacing the
string `category` column in the model matrix — not an addition to the 37
count above, since `category` was already one of the 32). Missing category
(2.4%) mapped to its own "unknown" bucket before computing frequencies, so
it gets a real (low, since unknown is uncommon) frequency value rather
than a NaN needing separate handling.

**Discrete-time hazard only, this phase.** Per your instruction: no Cox,
no gradient-boosted survival model yet — logistic regression on the
seller-week panel with `tenure_weeks` as the time-in-study term. Cox (with
a proportional-hazards check) and gradient-boosted survival are Phase 4
comparisons, not built here.

### D12 — Phase 2 results: base-rate drift and a caution about the AUC numbers

**Base-rate drift, row-level, primary N=8** (required by the brief):
train (weeks ≤ 2018-02-25) has a 0.531% per-row event rate over 45,243
rows / 1,434 sellers; test (weeks > 2018-02-25) has 0.680% over 34,853
rows / 1,679 sellers — **1.28x**. At seller level the direction flips:
16.74% of train sellers have an event in-window vs. 14.12% of test
sellers, because the test window (26 weeks) is shorter than the train
window (~60 weeks), so fewer test sellers have had time to reach an event
even though the instantaneous weekly rate is higher. Both cuts are worth
keeping in the README — they tell different stories and neither is more
"correct."

Drift is larger at N=4 (row rate 1.92x train→test) and mildly reversed at
N=12 (0.92x) — expected, since N=12's stricter silence requirement pushes
more of its events past the test cutoff into unconfirmable territory
(D6), so the test window is comparatively short of them.

**AUC caution, logged so it isn't mistaken for a Phase 4 result:** test
AUC is 0.89–0.97 across N=4/8/12 — high, and worth being suspicious of
rather than pleased by. A meaningful share of this is almost certainly the
model detecting **that a seller has already gone quiet this week**
(`order_volume_level` ≈ 0 in the event row, by construction of the pure-
cessation label itself) rather than genuinely predicting distress in
advance. That's not leakage — the level features are legitimately as-of
safe — but it means a plain AUC overstates how useful this is as an
*early*-warning system. This is exactly why the brief scopes rigorous
evaluation into Phase 4 (time-dependent AUC at fixed horizons, and lead
time as the headline metric, not aggregate AUC) rather than trusting this
number. Not re-litigated here — flagged so Phase 4 doesn't get read as
"confirming" a result that was never rigorously established.
