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

### D13 — D12's AUC concern is real: confirmed, not fixed, per instruction

Checked before touching Phase 3, per your instruction, with
`src/phase2_lead_time_diagnostic.py`: for each test-period event (N=8),
scored the prediction row exactly k weeks before its confirmation date
against a fixed pool of every test-period censored-seller row, for
k=1/2/4/8. Strictly out-of-sample both ways (event and prediction row both
required to be after `TEST_CUTOFF`).

**Result — AUC collapses toward chance as k grows:**

| k (weeks before event) | AUC, full model (37 feat.) | AUC, order_volume excluded (34 feat.) | events scored |
|---|---:|---:|---:|
| 1 | 0.909 | 0.909 | 232/237 |
| 2 | 0.876 | 0.876 | 224/237 |
| 4 | 0.804 | 0.806 | 202/237 |
| 8 | **0.499** | **0.518** | 145/237 |

Figure: `figures/phase2_lead_time_diagnostic.png`. At k=8 the full model is
statistically indistinguishable from a coin flip (0.499). Real
discriminative power is concentrated in the last ~1-2 weeks before an
event (0.88-0.91) and has substantially eroded by 4 weeks out (0.80). The
mean predicted score for soon-to-fail sellers at k=8 (0.0001) is actually
*below* the mean for censored sellers (0.0099) — 8 weeks out, these
sellers don't read as "borderline," they read as unusually low-risk by
this model's own scoring, which is a stronger version of "no early signal"
than AUC=0.5 alone conveys.

**Mechanism check — removing `order_volume` entirely changes almost
nothing** (0.909/0.876/0.806/0.518 vs. 0.909/0.876/0.804/0.499, full curve
in the table above, visually overlapping in the figure). This rules out
the specific hypothesis that direct order-volume features are *the*
mechanism — but it does not rescue the early-warning story. If anything it
sharpens the "quiet detector" reading: the collapse-toward-chance shape
persists almost identically whether or not the model can see raw order
volume, which means the "seller has gone quiet" signal is redundantly
encoded elsewhere too — most likely the shared missingness indicators
(`commitment_history_missing`, `delivery_history_missing`, D11), which
fire on exactly the same condition (zero recent orders) that
`order_volume_level` would have flagged directly. Removing one carrier of
that signal didn't remove the signal, because it wasn't the only carrier.
This diagnostic did not test removing the indicators too — a stricter cut
than what was asked for here, and explicitly not done, per instruction to
report before fixing.

**Verdict, stated plainly: this is substantially a quiet-detector past a
~2-week horizon, not an early-warning system in the sense the brief's
core hypothesis is about.** Genuine predictive lead time, as currently
built, looks like roughly 1-2 weeks, not the longer horizon the project's
premise assumes. This is a finding about the *current* feature set and
label, not a verdict on the underlying hypothesis (trend/acceleration
features *might* still carry real multi-week signal that a single pooled
logistic regression across all tenure lengths isn't extracting cleanly —
untested here). Not fixed. Implications for Phase 3 (a cost model
consuming these probabilities) and the ablation/lead-time work reserved
for Phase 4 are yours to decide, not mine to resolve by building forward.

### D14 — Three follow-ups on D13, reported, nothing fixed

#### 1. Anchor clarification: `k` was anchored to the confirmation week, not the last order

`event_week = last_active_week + N` (`distress_events.py`). D13's k values
were `event_week - k`, so **k=N (=8) lands exactly on `last_active_week`
itself** — the week of the seller's actual final order. Every k<8 tested
in D13 was a week *inside the silence period* (k=4 → 4 weeks already
quiet; k=1 → 7 weeks already quiet), not before it. D13's framing ("does
skill collapse toward chance as k grows") was still a fair question, but
none of its k values tested genuine advance warning while the seller was
still trading.

**Same table, anchored to `last_active_week` instead** (k weeks *before*
the seller's actual last order, still actively trading), full model:

| k (weeks before last order) | AUC | events scored |
|---|---:|---:|
| 1 | 0.584 | 133/237 |
| 2 | 0.586 | 120/237 |
| 4 | 0.534 | 97/237 |
| 8 | 0.555 | 39/237 |

order_volume-excluded model: 0.581 / 0.593 / 0.539 / 0.580 — same shape.
**This is the cleaner test, and it's near-null at every horizon.** For
reference, confirmation-anchored k=8 (0.499) and last-order-anchored k=0
describe the same row by construction (both = `last_active_week`) — the
two tables agree exactly where they overlap, which is a consistency check
that the reimplementation is correct, not a new result.
`figures/phase2_lead_time_diagnostic.json` has both curves in full, for
both feature sets. Script: `src/phase2_lead_time_diagnostic.py`.

#### 2. The operative baseline: acceleration over the N=8 rule, at fixed false-alarm rates

`src/phase2_acceleration_vs_rule.py`: threshold set on the row-level
false-alarm rate over the test-period censored-row pool; for each
test-period event (237 total), scanned every out-of-sample week from
`TEST_CUTOFF` through `event_week` for the first week the model's score
crosses that threshold, compared to the rule's fixed fire time
(`event_week`, always — the rule is deterministic).

| row-level FAR | threshold | seller-level FAR | never beats the rule | beats the rule | median acceleration (of those that do) |
|---|---:|---:|---:|---:|---:|
| 1% | 0.1239 | 6.9% (99/1442) | 226/237 (95.4%) | 10/237 (4.2%) | 1.5 weeks |
| 5% | 0.0714 | 17.1% (247/1442) | 153/237 (64.6%) | 71/237 (30.0%) | 2.0 weeks |
| 10% | 0.0383 | 32.0% (462/1442) | 83/237 (35.0%) | 139/237 (58.6%) | 2.0 weeks |

At every false-alarm rate checked, the **majority of events get zero
benefit over the naive silence rule** — 5% FAR (a reasonable operational
choice) beats the rule for only 30% of events, and even then the median
gain is 2 weeks, p75 = 3 weeks, max = 17 weeks (a long tail, not the
typical case). Reaching a majority (58.6%) requires a 10% FAR, which costs
a 32% seller-level false-alarm rate — a third of healthy sellers flagged
at least once. **The honest headline, if this holds up: "accelerates
confirmation by a median of ~2 weeks, for a minority of cases, at a
reasonable false-alarm rate" — not "predicts distress in advance."**
Full numbers: `figures/phase2_acceleration_vs_rule.json`.

#### 3. Timeboxed core-hypothesis check: restrict to actively-trading rows — result caveated, likely still contaminated

`src/phase2_active_only_ablation.py`: refit restricted to rows with
`order_volume_level > 0`, relabelled as "event within next 8 weeks" (the
at-event-week label is unusable under this filter — it's always
volume-zero by construction). Result: **test AUC = 0.730** (train 0.772),
n=25,780 test rows / 658 positive.

**This number should not be read at face value — checked directly and
found a likely confound before reporting it as clean.** `order_volume_level`
is a trailing 4-week *pooled* average (D8), so it stays above zero for
2-3 weeks *after* a seller's actual last order — verified on 5 sample
events directly (e.g. seller `002100f7...`: `last_active_week`=2018-04-15,
`order_volume_level` is still 0.75 that week, 0.75 the week after, 0.50
two weeks after, and only reaches exactly 0 at four weeks after). The
"event within 8 weeks" label window (`last_active_week` through
`last_active_week`+7) overlaps almost entirely with this echo period.
**So `order_volume_level > 0` did not cleanly exclude "recently gone
quiet" rows — it let several weeks of decaying-toward-zero silence back
in**, which is close to the same signal D13/D14§1 already showed is easy
to detect. That's the likely reason 0.730 is so much higher than
§1's clean last-order-anchored numbers (0.53-0.59): §1 uses a single row
strictly *before* the last order (no echo possible, by construction);
this check's label window mostly sits *after* it.

**Conclusion: §1's last-order-anchored curve is the trustworthy version
of this question, and it says no — no discriminative power detected while
a seller is still visibly, currently trading, at any of the horizons
tested (1-8 weeks).** This check does not overturn that; if anything, the
mechanism found for its own inflated number reinforces it. A corrected
version (require the *current single week's* raw order count > 0, not the
trailing pooled level, or just restrict to rows several weeks clear of
`last_active_week`) is the obvious next step, not done here — timeboxed,
and instructed to report before fixing.

**Bottom line across all three: no evidence survives that this model
provides genuine multi-week advance warning.** What does survive: a
real but modest ability to detect distress 1-2 weeks before the N=8 rule
would confirm it anyway, for a minority of cases, at a cost in false
alarms. That is a different, smaller claim than the project's premise, and
the README needs to say so if Phase 3/4 proceed on the current feature
set and label. Not decided here.

## Phase 3

### D15 — Phase 3 rescoped: acceleration-vs-rule, not a reserve-sizing surface

**Chose:** given D13/D14, the brief's original Phase 3 design (a reserve
percentage sized as a function of hazard and merchant size) is not built.
It presumes the model carries continuous, multi-week hazard information
worth turning into a nuanced sizing surface — D14 found that past ~2
weeks, it doesn't. Built instead: a sweep of the row-level false-alarm
rate from 1% to 10%, reporting expected cost per 1,000 merchant-weeks of
a model-triggered early-reserve policy against the N=8 rule as the
zero-point baseline (the rule has no false alarms by construction — the
label *is* its output — so its cost is 0 and its acceleration is 0; the
sweep is measured as a delta from that). `src/policy.py`,
`config/costs.yaml`.

**Currency note:** figures are in R$ (Brazilian Real), the actual
currency of the Olist transaction data, not converted to Rupees — see the
comment at the top of `config/costs.yaml`. Flagged, not silently decided
either way; happy to add an explicit FX-converted view if that's actually
wanted for the write-up.

**Confirmed 2026 (Phase 4 kickoff):** keep everything in R$. Converting
would imply a transfer to Indian payments the underlying data can't
justify. This is a README limitations item, not just a code comment —
carry it into README requirement #2 (dataset/context mismatch) when the
README is written.

### D16 — Sweep result: the model beats the rule at every false-alarm rate tested, and the win grows with FAR

| FAR | events accelerated | benefit (R$) | cost (R$) | net Δcost / 1,000 merchant-weeks (R$) | seller-level FAR |
|---:|---:|---:|---:|---:|---:|
| 1% | 10/237 | 300 | 17 | **-8.12** | 6.9% |
| 3% | 37/237 | 867 | 41 | **-23.71** | 13.0% |
| 5% | 71/237 | 2,656 | 67 | **-74.29** | 17.1% |
| 7% | 104/237 | 3,830 | 88 | **-107.35** | 22.7% |
| 10% | 139/237 | 5,081 | 123 | **-142.25** | 32.0% |

(Full 10-point sweep: `figures/phase3_far_sweep.csv` /
`figures/phase3_far_sweep.png`.) Negative = the model policy costs less
than the rule — **it wins at every FAR tested, and the margin widens
monotonically as FAR increases; it never breaks even in the model's
favour reversing, let alone loses, across the swept range.**

**This result rides almost entirely on one assumption ratio, and that
needs to be said as plainly as the result itself.** The right panel of
`figures/phase3_far_sweep.png` shows why: benefit grows roughly 40x
faster than cost across the sweep. That's not really a discovery about
the model — it's built into the two cost parameters. `benefit_capture_rate
= 1.0` values every real of accelerated reserve as a full real of avoided
loss; `working_capital_cost_weekly_rate = 0.0035` charges a healthy
flagged merchant less than half a percent of their reserved capital, per
week. Any policy that produces *some* true accelerations at all will look
good under that ratio, almost regardless of how many false alarms come
with it. Per instruction these parameters were **not tuned to reach this
result** — picked once, up front, and documented in `config/costs.yaml`
before the sweep ran — but the result's robustness is still only as good
as that ratio's realism, which is asserted, not measured (Olist has no
financing-cost data). **A materially higher `working_capital_cost_weekly_rate`
or lower `benefit_capture_rate` could flip this — that sensitivity is
exactly what Phase 4's tornado plot is supposed to establish, not assumed
away here.**

**Two things worth carrying into Phase 4, checked here rather than
assumed:**
- **The false-alarm burden is sustained, not a blip.** At FAR=10%, a
  flagged healthy seller is flagged for a mean of 7.0 weeks (median 5.0)
  out of a mean 22.4 observed test-period weeks — roughly a third of
  their test-period existence. The per-week cost formula already prices
  this correctly (each flagged week is charged), but "32% seller-level
  false-alarm rate" understates how concentrated the burden is on the
  sellers it does hit.
- **Checked whether flagged healthy sellers skew toward small/new
  merchants (the brief's Phase 4 fairness concern) — they don't, on
  tenure at least.** Flagged rows have *higher* tenure than the overall
  censored population (mean 55.1 vs. 35.9 weeks, median 56 vs. 34) at
  FAR=10%. This is one dimension (tenure), not the full fairness
  question (size/GMV, category), and not a substitute for Phase 4's
  actual slice analysis — but it's evidence against, not for, the
  concern that this specific policy would concentrate its false-alarm
  cost on the most vulnerable merchants. Worth re-checking properly, not
  assumed to generalise.

**Bottom line, stated as instructed regardless of which way it went: the
model-based policy beats the naive N=8 rule at every false-alarm rate
tested, with the win growing as the rate loosens — but this conclusion
depends heavily on one under-measured cost-parameter ratio, and Phase 4's
sensitivity analysis needs to establish how much room that ratio has to
move before the answer changes.**

## Phase 4

### D17 — Sensitivity analysis: D16's caveat doesn't materialise, and updating on that plainly

`src/phase4_sensitivity.py`. Computed the breakeven value of each cost
parameter at every FAR in the sweep, and a tornado plot at FAR=5% — both
closed-form from the existing sweep (`figures/phase3_far_sweep.csv`),
since both cost terms are exactly linear in their own parameter and in
`reserve_pct` (no rescoring needed).

**Breakeven `benefit_capture_rate` across the sweep: 2.3%-5.7%** (config
default: 100%). **Breakeven `working_capital_cost_weekly_rate`: 322%-803%
annualised** (config default: ~18%). Neither is remotely plausible —
capture would have to fall to essentially nothing (recall reserve is
money the aggregator *already withheld* from the merchant's own
settlements, not a debt to be collected; near-total capture is
structurally the realistic end of this parameter, not the optimistic
one), and working-capital cost would have to exceed even predatory
microfinance rates several times over. Tornado plot
(`figures/phase4_tornado.png`) at FAR=5%: sweeping `benefit_capture_rate`
across [0.10, 1.00] and `working_capital_cost_weekly_rate` across
[~10%, ~60% annualised] — both deliberately wide, picked before seeing
where breakeven fell, not after — the net result never crosses zero. Only
`reserve_pct` produces a wider swing (R$ magnitude, not sign, D16), as
expected since it's a common linear multiplier on both terms.

**Updating plainly on D16's own caveat:** D16 flagged this as "the result
rides almost entirely on one assumption ratio" and left open that "a
materially higher working-capital rate or lower capture rate could flip
this." Quantified now: it doesn't, not within any range a reader would
call plausible. That caveat was the right thing to raise before running
the numbers — it just turns out not to bind. **This is the highest-
confidence finding in the project: the FAR-sweep result is robust to
single-parameter perturbation across generous plausible ranges.** It is
not immune to *joint* pessimism on both parameters at once (checked
analytically: at FAR=5%, breakeven requires `wc_rate / capture >= 0.139`
— e.g. capture=0.10 together with wc_rate >= 0.0139/week, ~72%
annualised, would flip it — a combination requiring both a very
pessimistic capture assumption *and* a very high financing rate
simultaneously, not just one or the other).

### D18 — The ablation: the brief's core hypothesis fails, cleanly, on every test built

`src/phase4_ablation.py`. Three nested feature tiers (levels only, 12
features; +trend, 28; +trend+accel, 37 — the full model), evaluated two
ways, plus the corrected active-only test D14 sec.3 called for.

**Corrected active-only test (the direct hypothesis test — raw
current-week order count, not the pooled level that contaminated D14
sec.3's first attempt; label = event within 8 weeks, anchored before
`last_active_week`; 19,633 train / 14,351 test rows):**

| tier | features | train AUC | test AUC |
|---|---:|---:|---:|
| levels only | 12 | 0.702 | **0.682** |
| levels + trend | 28 | 0.712 | **0.678** |
| levels + trend + accel | 37 | 0.714 | **0.678** |

Test AUC is flat to slightly *down* as trend and acceleration are added
(0.682 → 0.678 → 0.678), while train AUC rises slightly (0.702 → 0.714) —
the signature of extra features adding fitting capacity without adding
generalising signal, not the hypothesis's predicted direction.

**Point-in-time test (last-order-anchored curve, D14 sec.1's clean
anchor, all three tiers):** k=1/2/4/8 AUC ranges 0.53-0.59 for every
tier, curves visually overlapping (`figures/phase4_ablation.png`, right
panel). No tier separation at any horizon.

**Verdict, stated as instructed regardless of outcome: the brief's core
hypothesis — trend and acceleration predict distress better than levels —
is not supported by any test this project built.** Levels alone carry
real, moderate signal (0.68-0.70 AUC) about an actively-trading seller's
risk of failing within 8 weeks — a genuine, useful finding, and a more
optimistic one than D13/D14's point-in-time tests alone suggested, since
the horizon-pooled test has far more statistical power (1,524 positive
rows vs. 39-133 per point). But trend and acceleration, layered on top,
add nothing measurable. **The finding is not "no early signal exists" —
current-state features do carry a real signal even before a seller goes
fully quiet. The finding is specifically that the brief's hypothesized
mechanism — trend and acceleration beating levels — does not hold on this
feature set, this label, and every evaluation constructed to test it.**

This does not retroactively change D13/D14/D16 — Phase 2's diagnostics
and Phase 3's economics were built on the full 37-feature model, and nothing
here suggests a levels-only model would have scored differently on the
FAR-sweep economics (worth confirming in a future pass, not assumed).
Recorded here as the ablation result on its own terms, per instruction to
report it either way and make it prominent.

### D19 — Headline lead-time figure and calibration

`src/phase4_calibration.py`. Why calibration matters more than AUC here,
stated in the script and repeated for the README: the decision layer
thresholds the model's *absolute* predicted probability against a
false-alarm-rate-derived cutoff (Phase 3), and the brief's original
design wanted a reserve percentage sized directly off the hazard value.
AUC alone can't catch a model that ranks correctly but is systematically
over- or under-confident — that would silently distort every FAR
threshold and reserve figure downstream.

**Headline lead-time figure** (`figures/phase4_headline_lead_time.png`):
NOT the raw "days of warning before the event" the brief's Phase 4 spec
asked for — D14 sec.2 already established the honest framing is
acceleration over the N=8 rule. At FAR=5% (primary): median 2.0 weeks
(mean 3.4, right-skewed with a long tail to 17 weeks), but **153/237
events (65%) are never flagged before the rule fires at all** — the
distribution is conditional on beating the rule, and most events don't.
Companion panel: the last-order-anchored AUC-vs-k curve (D14 sec.1,
D18), the complementary "is there real advance warning while still
trading" view, restated here as the headline pairing rather than a
separate diagnostic.

**Calibration** (`figures/phase4_reliability_diagram.png`, quantile-
binned — equal-width bins are useless at a ~0.5-0.7% base rate, almost
everything would land in one bin): Brier=0.0068, ECE=0.0045 — good in
aggregate, but the aggregate number hides where it matters. The bottom 8
of 10 bins are indistinguishable from perfect (predicted and actual both
~0), unsurprising at this base rate. The top bin — the one closest to
Phase 3's FAR thresholds — is **over-confident**: mean predicted 0.080
vs. mean actual 0.039, roughly 2x too high. The second-highest bin is
mildly under-confident in the other direction (0.025 predicted vs. 0.028
actual). **The bin that actually drives the FAR-sweep decisions is the
most miscalibrated one, which the aggregate ECE number does not surface
on its own.** Not corrected here (a fix — e.g. Platt scaling on this
region specifically — is a natural next step, not done); flagged because
Phase 3's cost figures use the raw score, and a threshold derived from
this over-confident tail would flag slightly less often than the
model's own probabilities imply it should.

### D20 — Slice analysis and fairness: two real losing slices found

`src/phase4_slices.py`. Extends Phase 3's economic framework (D16) to
four slice dimensions — tenure at test start, size (mean weekly GMV,
quartiles), dominant category, and order-volume decile — all assigned
**per seller**, not per row (the question is whether the policy treats
different *kinds* of merchants differently, not different weeks of the
same merchant). "Loses to the rule" is economic (net Δcost per 1,000
merchant-weeks > 0 within the slice), since the rule has no AUC of its
own to lose on. FAR=5% throughout, matching Phase 3/4's primary operating
point. Full tables: `figures/phase4_slices_*.csv`;
`figures/phase4_slices.png` (all four dimensions),
`figures/phase4_slices_category_clean.png` (readable version, ≥20-seller
categories only — the full-label version is illegible with 70 categories).

**Size and volume-decile: the model wins in every slice.** No losing
slice in either dimension. Benefit scales with merchant size (Q4 largest:
-R$117.9/1000mw vs. Q1 smallest: -R$12.4/1000mw) — expected, since
benefit is R$-denominated and proportional to GMV — but the *sign* never
flips.

**Tenure: one real finding, though "loses" overstates it.** Three bands
(new <13wk test-start tenure: 1,361 sellers — the single largest cohort,
44% of all sellers; established 13-52wk: 1,190; veteran >52wk: 514).
Established and veteran sellers win big (-R$29.8 and -R$362.6/1000mw).
**New sellers technically lose, by R$0.01/1000mw — three orders of
magnitude smaller than every other slice's margin.** The honest
characterization isn't "the model hurts new sellers" — it's that **the
model is essentially inert for them**: few get flagged (little
false-alarm cost) and few of their failures get accelerated (little
benefit either). This is a genuinely two-sided fairness fact worth
stating plainly: new merchants — the segment the brief's fairness note
worried would be over-reserved — are not carrying disproportionate
false-alarm burden here, but they also see essentially none of the
model's value. The tool has close to nothing to say about the largest
group of merchants in the dataset.

**Category: real losing slices exist, not just small-sample noise.**
Filtering to categories with ≥20 sellers (below that, a single false
alarm with zero events flips the sign trivially — not a meaningful
finding on its own), 9 of 28 lose. The two most credible on sample size:

- **`auto`, 210 sellers, 10 events: +R$1.88/1000mw** (a real loss, small
  magnitude, but the second-largest category in the dataset by seller
  count).
- **`electronics`, 42 sellers, 3 events: +R$1.88/1000mw.**

Smaller-but-still-real cases: `consoles_games` (23 sellers, +R$7.02),
`watches_gifts` (52 sellers, +R$3.12), `musical_instruments` (38 sellers,
+R$3.07). No investigated mechanism for *why* these particular categories
lose (a natural next check — e.g. whether they have systematically
lower order frequency, which Phase 0's F1 already flagged as a general
sparsity problem — not done here, timeboxed). At the other extreme,
`cool_stuff` and `perfumery` show enormous wins (-R$802.9 and
-R$563.4/1000mw) — a wide spread across categories that a single
population-level number (D16) does not surface.

**Bottom line:** the model-based policy's aggregate win (D16) is not
uniform. It is genuinely negative in a handful of well-populated
categories (`auto` foremost), and essentially a no-op — not harmful, but
not useful either — for the largest single cohort of merchants in the
dataset (new sellers, <13 weeks tenure). Both reported as instructed,
without softening either.

### D21 — Calibrated re-run of the FAR sweep: your prediction did not hold, in either direction expected

`src/phase4_calibrated_sweep.py`. Isotonic regression fit on TRAIN
predictions/labels only (`sklearn.isotonic.IsotonicRegression`), applied
post-hoc to the raw scores `policy.py` already computes at every stage of
the sweep. No cost parameter touched.

**Your prediction was: net benefit shrinks but survives.** The actual
result: **it doesn't shrink — the calibrated sweep beats the uncalibrated
one at every single FAR tested (all 10 differences negative, i.e. more
favourable, not less), and there is no sign flip anywhere**
(`figures/phase4_calibrated_sweep.png`, `..._comparison.csv`). Stated
plainly because it's the opposite of what was predicted, not a
confirmation to wave through:

| FAR | uncalibrated net Δ/1000mw | calibrated net Δ/1000mw | difference |
|---:|---:|---:|---:|
| 1% | -8.12 | -16.50 | -8.38 |
| 5% | -74.29 | -98.03 | -23.74 |
| 10% | -142.25 | -155.33 | -13.08 |

**Why the prediction's mechanism doesn't apply, worked out after seeing
the result, not before:** the FAR sweep was never actually probability-
*weighted*. Cost and benefit are both computed from realized outcomes —
a censored row that crosses a quantile-defined threshold is an
unambiguous false alarm regardless of what probability the model
attached to it; an event's acceleration is measured against its actual
confirmation date. The score is used only to *rank* rows against a
quantile threshold. Isotonic regression is monotonic, so in the limit of
no ties it cannot change which rows clear a quantile threshold at
all — the over-confidence D19 found should have been close to a no-op on
this specific sweep design, not a shrink.

**It wasn't a no-op, because isotonic regression is a step function and
real, finite data produces ties at that step's plateaus** — visible
directly in the calibrated table: FAR=1% and 2% share the identical
threshold (0.200000) and identical accelerated-event count (26); so do
3%/4% (61), 6%/7% (107), and 8%/9%/10% (158). Where a quantile cutoff
lands inside one of these plateaus, the selection jumps in discrete
blocks rather than varying smoothly, and in this data those blocks
happened to pull in more benefit than cost. **This is an artefact of
isotonic regression's specific shape interacting with quantile-based
threshold selection, not a general property of "calibration helps."** A
smoother calibrator (Platt scaling, e.g.) would very likely behave more
predictably here — not tried, out of this timebox.

**Bottom line: the economic result survives calibration and is not
weakened by it, but not for the reason anyone would have guessed going
in, and the specific magnitude of "how much better" should be read with
real caution** given it hinges on where quantile cutoffs happen to land
relative to isotonic's tie plateaus — a more sensitive dependency on
implementation detail than the headline number suggests. The safe
takeaway for the README: **calibration does not overturn the FAR-sweep
result.** The specific "gets better, not worse" direction is a real
finding from this run, not a claim to build further conclusions on
without the smoother-calibrator follow-up.

### D22 — README finalised: three presentation figures, no new analysis

Per instruction, `src/phase4_presentation_figures.py` builds three
README figures from numbers already established (D12-D14, D18-D19,
D14 §2) — no model was refit differently and no new finding is in them:

- `readme_lead_time_waterfall.png` — the three-stage argument from D13/D14
  §1 (apparent AUC → confirmation-anchored collapse → last-order-anchored
  correction), now the README's first figure, above the economics
  (Section 3).
- `readme_ablation.png` — D18's tier comparison, with a caption noting
  the hypothesis predates this repository's commit history (`BRIEF.md`
  is gitignored by request, so this is stated as "no commit predates it,"
  not literally "in git log" — checked directly rather than assumed,
  `git log --all --full-history -- BRIEF.md` returns nothing, so the
  original phrasing suggested would have been imprecise).
- `readme_model_vs_rule.png` — D14 §2's 65%/5%/30% breakdown, redrawn so
  the 65%-no-benefit share is the dominant visual element rather than a
  caption detail, opening Section 4.

Two limitations added to the README that weren't there before: marketplace
sellers vs. payment-aggregator merchants as a distinct relationship-type
gap (not just the dataset/currency mismatch already covered), and an
explicit statement that every economic figure in Sections 4-5 is
simulated from assumed parameters against realised outcomes, not a
record of money that moved. Both were prompted by direct request, not
discovered independently this round.

### D23 — Precision and recall, stated directly, at the calibrated FAR-sweep thresholds

`src/phase4_precision_recall.py`. The evaluation track asks for measured
precision/recall on a held-out test set by name; this project had AUC,
calibration, lead time, and cost, but never stated these two directly.
Computed on the calibrated model (same isotonic calibrator as D21), at
the exact thresholds D21 already established for 1%/5%/10% FAR (reused
from `figures/phase4_calibrated_sweep.csv`, not recomputed), against the
full test-period row population and the original at-event-week label:

| FAR | threshold | flagged | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1% | 0.200000 | 874 | 31 | 843 | 206 | 3.5% | 13.1% |
| 5% | 0.054545 | 2,212 | 92 | 2,120 | 145 | 4.2% | 38.8% |
| 10% | 0.040389 | 4,505 | 166 | 4,339 | 71 | 3.7% | 70.0% |

Test window: 34,853 rows, 237 actual events (0.68% positive rate).
Precision is poor in absolute terms (3.5-4.2%) — expected given the base
rate, reported as such, not reframed. Recall rises with FAR (13%→39%→70%)
as expected. **The low precision does not contradict D16's economic
result — it's exactly why D16's cost model matters rather than being
decoration: the policy wins economically not because it's precise, but
because the cost-model ratio (D17) makes each rare true positive worth
far more than each common false positive costs.** Added to the README
(Section 5, alongside the calibrated-model discussion) rather than left
implicit across AUC/calibration/cost sections separately.

**Addendum — precision is non-monotonic across the three FAR points
(3.5%→4.2%→3.7%), checked rather than assumed to be either an error or
purely the D21 tie-plateau effect:** recomputed precision at the same
three FAR quantiles on the *raw, uncalibrated* scores as a control —
0.9%→4.1%→3.9%, also non-monotonic. So the underlying model's ranking is
not perfectly precision-ordered across this range regardless of
calibration; that part isn't a calibration artefact. What calibration
does add: isotonic regression collapses 31,442 distinct raw scores into
only 50 calibrated levels, so each of the three thresholds falls in one
of a small number of discrete blocks (15 unique levels between the 1%
and 5% thresholds, only 6 between 5% and 10%) rather than a smooth
continuum — those two blocks have batch precision 4.56% and 3.23%
respectively, confirmed directly, which is what coarsens a mild
underlying non-monotonicity into the more visible dip reported in the
table. Footnoted in the README rather than left to look like an error.

### D24 — Capacity check: a single gradient-boosted model, not a model upgrade

`src/phase4_gbm_capacity_check.py`. Framed and run as a capacity check,
not a candidate replacement: does a more flexible learner extract signal
the linear model missed on the *same* 37 features, *same* row-level
split, *same* two evaluations already used for the ablation (D18) and the
honest advance-warning horizon (D14 §1)? One `HistGradientBoostingClassifier`,
default hyperparameters except `random_state=0` — no tuning, no class
weighting (the logistic regression got neither either, so this stays an
apples-to-apples "same treatment" comparison, not a tuned model against
an untuned one). Not promoted to primary regardless of the result, per
instruction.

**Pooled active-only task (mirrors D18):** GBM test AUC 0.700 vs.
logistic 0.678 — reported with the number that actually explains it, not
asserted as a clean win: GBM train AUC is 0.953, a 25-point train/test
gap, against the logistic regression's 3.6-point gap (0.714→0.678). The
GBM converts its extra capacity mostly into overfit, not signal, and a
2.2-AUC-point edge measured against only 363 test-window positive rows is
within what sampling noise on a set that size would produce on its own.
**Not read as a meaningful edge.**

**Honest advance-warning horizon (mirrors D14 §1, last-order-anchored):**
the test that matters more, and the GBM does not beat the linear model
there — at or below it at three of four horizons:

| k (weeks before last order) | logistic | GBM |
|---:|---:|---:|
| 1 | 0.584 | 0.561 |
| 2 | 0.586 | 0.569 |
| 4 | 0.534 | 0.540 |
| 8 | 0.555 | 0.523 |

**Pattern worth naming directly:** the GBM is slightly better pooled and
slightly worse at the advance-warning horizons — consistent with it
fitting the *quiet-detection* signal (D13's "seller has already gone
quiet" mechanism) somewhat harder than the logistic regression does,
which is not early warning; D13/D14 already established that mechanism
is what drives most of the pooled number for either model class. A
learner that's marginally better at recognising silence and marginally
worse before it begins is not evidence of missed early-warning signal —
it's the same finding restated in a different model.

**Conclusion, restated at the strength the evidence actually supports
(amended below, D29):** ~~the ceiling is in the data and features, not
the model class~~ — a nonlinear, interaction-capturing learner given the
identical inputs does not clear the ~0.68-0.70 pooled ceiling or the
~0.52-0.59 advance-warning ceiling by a margin that survives scrutiny.
This strengthens D18's negative result rather than reopening it. What
this single run does *not* establish is a class-wide ceiling: one
untuned, default-hyperparameter GBM is evidence that these features
carry limited predictive information, not proof that no model class
could do better — that would need the tuned comparison D24's own
limitation paragraph, below, already flags as not done.

**Limitation, stated plainly rather than left implicit:** both models
were run on default hyperparameters, with no early-stopping tuning for
either. That's the right comparison for *this* question (an untuned GBM
against an untuned logistic regression), but it is not the strongest
possible test of "could a better-tuned nonlinear model do better" — a
properly cross-validated, early-stopped, hyperparameter-searched GBM is
what would be built next if this result needed to bear more weight than
a capacity check. Not done here; logistic regression remains the primary
model throughout this project regardless.

### D25 — Interactive demo: reads artefacts, computes nothing new

`app.py` (Streamlit, single file) + `src/prepare_demo_data.py` (one-time
prep, not in `run.sh`). The prep script does the only legitimate round of
computation, reusing the already-fitted primary model, the already-fit
D21 isotonic calibrator, and the already-established D16/D21 cost
economics exactly — no new modeling decision anywhere in it. It writes
three files `app.py` then only reads:

- `figures/demo_test_predictions.csv` (34,853 rows) — every test-period
  row's calibrated hazard plus each of the 37 features' *exact* linear
  contribution to the score (coefficient × standardised value — exact
  for a linear model, not an approximation). `app.py` computes "what
  changed since last week" by subtracting two rows of this table —
  arithmetic on precomputed numbers, not re-inference.
- `figures/demo_seller_gmv.csv` (3,065 rows) — `policy.per_seller_weekly_gmv`,
  reused verbatim.
- `figures/demo_event_acceleration.csv` (711 = 237 events × 3 FAR points)
  — reuses `policy.score_event_histories` /
  `acceleration_weeks_at_threshold` with the calibrator, the same
  mechanism `phase4_calibrated_sweep.py` already used for the aggregate
  D21 numbers, kept here at per-event granularity.

**Verified before treating it as done, not assumed:** ran the app
through `streamlit.testing.v1.AppTest` (executes the script in-process,
surfaces exceptions directly, no browser/websocket needed) across the
default view, an explicit event merchant, an explicit censored merchant,
a week change (exercising the "last week" delta path), and both other
FAR operating points (1%, 10%) — no exceptions in any case. The dynamic
honesty banner was checked to actually change with FAR, not just
render once: at 10% FAR it correctly reports 65/237 (27%) never flagged,
158/237 (67%) beat the rule by a median of 2.0 weeks, matching
`demo_event_acceleration.csv` exactly.

**One consequence worth naming:** the demo's acceleration banner is
built on the *calibrated* model (D21), which is measurably more
favourable than the uncalibrated D14 §2 numbers quoted in README Section
3/4 (at 5% FAR: 58% never-flagged / 36% beats-rule / 6% ties, vs. the
uncalibrated 65%/30%/5%). ~~This is not an inconsistency — ... deliberately~~

**Superseded by D26, below.** On reflection this framing was wrong: two
different numbers for the same quantity in two places a reviewer will
both look at is a credibility problem regardless of both being real or
both being sourced — "deliberate" doesn't fix that, it just explains it.
D26 corrects this by making the README's headline numbers the calibrated
ones throughout, matching the demo, with the uncalibrated numbers kept
only where explicitly labelled as the pre-calibration comparison.

Two required honesty elements from the instruction, both implemented as
non-collapsible `st.warning`/`st.info` banners rather than optional
detail: the minority-benefit acceleration result (dynamic per selected
FAR) and the top-decile calibration caveat (D19's numbers, static).
Kept deliberately plain per instruction ("cut it" if a panel looks more
impressive than the evidence supports) — no gauges, no 0-100 risk
scores, no colour-coded risk badges; hazard is shown as a plain
percentage via `st.metric`, and the reserve recommendation is described
explicitly as a binary threshold policy with a fixed reserve percentage,
not the continuous hazard-to-reserve surface the brief originally
specified and D15 explicitly did not build.

`requirements.txt` added (didn't exist before) covering both the core
pipeline and the demo, with the demo's one dependency (`streamlit`)
commented as demo-only. `run.sh` unchanged — neither `app.py` nor
`src/prepare_demo_data.py` are called from it, per instruction.

### D26 — README headline made calibrated throughout; consistency pass

**Closing D25's mismatch.** Per instruction: the calibrated model is
this project's established operating configuration (D21), so the
README's headline acceleration and economics numbers now match the demo
exactly, not just agree in direction.

**Changed, with the mechanical reason each needed to change:**
- **Section 3** (headline lead-time result): 30%/65%/5% → **36%/58%/6%**
  at 5% FAR (median acceleration unchanged at 2.0 weeks — only the
  *shares* moved). One sentence added stating which split is calibrated
  and where the uncalibrated one now lives (Section 5), so this doesn't
  need repeating as a caveat at every subsequent mention.
- **Section 4** (economic comparison): the headline table and its
  `figures/readme_model_vs_rule.png` figure are now calibrated —
  events-accelerated 26/85/158 (was 10/71/139), net Δcost -R$16.50/
  -R$98.03/-R$155.33 per 1,000 merchant-weeks (was -R$8.12/-R$74.29/
  -R$142.25), seller-level FAR 11.5%/19.4%/36.9% (was 6.9%/17.1%/32.0%).
  `src/phase4_presentation_figures.py`'s `fig3_model_vs_rule()` rewritten
  to score through the D21 calibrator (previously used raw scores,
  itself the source of D25's mismatch) and regenerated.
- **Section 5** (calibration): gained an explicit pre-calibration
  comparison table (the numbers Section 4 used to show), rather than
  only narrating that calibration helped without the reader being able
  to see both numbers side by side.

**Not changed, and why that's correct rather than an oversight:**
Section 6's ablation figures and numbers (AUC-based) needed no change —
AUC is invariant to any monotonic recalibration by construction (it
depends only on rank order, which isotonic calibration preserves), so
there was never an uncalibrated/calibrated distinction to reconcile
there. Checked, not assumed: this is a property of AUC, not something
that needed verifying against the actual numbers.

**Consistency pass — one further real inconsistency found, not fixed
this round, flagged in the README (Section 7) and here:** Section 7's
slice economics (`src/phase4_slices.py`, D20) score events and censored
rows with **raw, uncalibrated** predictions — no calibrator is applied
anywhere in that script, confirmed by inspection, not assumed. D20 was
written before D21 existed, so this wasn't a lapse at the time, but it
means Section 7 now sits on a different operating configuration than
Sections 3-5, the exact shape of problem D25 was. Not re-run this round
(re-running would change every margin in Section 7 — tenure, size,
category, volume-decile — not just relabel them, which is a bigger job
than this consistency pass). Labelled explicitly in the README instead
of left silently inconsistent. Expectation, not a checked claim: since
calibration made the aggregate economics more favourable (D21), the
qualitative findings (tenure inertia, `auto`/`electronics` losing) are
unlikely to reverse — but the exact margins have not been verified
against calibrated scores and the README says so.

**Everything else checked and found consistent:**
- `figures/phase4_precision_recall.csv` / README Section 5's
  precision/recall table: already calibrated (D23), thresholds match
  D21's exactly (0.2000/0.0545/0.0404) — no drift.
- Section 4's sensitivity/tornado analysis (D17): confirmed to be
  pre-calibration (reads `figures/phase3_far_sweep.csv`, not the
  calibrated sweep) — labelled explicitly in the README rather than
  silently left ambiguous, without re-deriving new breakeven numbers
  this round (a real follow-up, not done: re-run D17 on the calibrated
  sweep).
- DECISIONS.md's own D13/D14/D16 entries were not edited — they are a
  chronological log of what was true when written (before D21 existed),
  correctly stated for their own point in the project's history. Only
  D25's specific "not an inconsistency" claim was struck through and
  corrected, since that one was a live claim about the current state of
  the README, not a historical record.
- Spot-checked `figures/demo_event_acceleration.csv` (the demo's own
  data file) against the new README numbers directly — 58.2%/35.9%/5.9%
  at FAR=5% rounds to the 58%/36%/6% now in Section 3, exact match.

### D27 — Slice analysis re-run calibrated: `auto` and `musical_instruments` flip from losing to winning

`src/phase4_slices.py` closes the inconsistency D26 flagged but did not
fix: the script now scores events, histories, and censored rows through
the D21 isotonic calibrator before computing per-slice economics, same
as Sections 3-5. **D20's original uncalibrated numbers are not
overwritten** — they stay in D20, above, as the record of what was true
before calibration was applied here; this entry records what changed and
why, per instruction. Method: backed up the pre-rerun CSVs before
running, then did a programmatic merge on `model_wins` per slice per
dimension across all four CSVs rather than eyeballing the tables, so a
flip couldn't be missed or hallucinated.

**Size and volume-decile: no change.** The model still wins every slice
in both dimensions, no exceptions — magnitudes increased across the
board (e.g. size Q4: -R$117.9 → -R$163.5/1000mw), consistent with D21's
finding that calibration made the aggregate economics more favourable,
not less.

**Tenure: no flip, conclusion unchanged.** New sellers (<13wk,
1,361/3,065 — still the largest cohort) go from +R$0.005 to
+R$0.021/1000mw — nominally larger but still four to five orders of
magnitude below established (+R$29.8 → -R$52.9) and veteran (-R$362.6 →
-R$445.4) sellers, both of which strengthened. The model remains
essentially inert, not harmful, for the largest group of merchants in
the dataset — exactly the finding the user asked to check survived, and
it does.

**Category: 2 of 9 losing slices flip to winning; 7 remain.** Programmatic
comparison found flips only here, both losing → winning, none in the
other direction:

| category | sellers | events | net Δcost/1000mw, D20 (uncalibrated) | net Δcost/1000mw, calibrated | flip |
|---|---|---|---|---|---|
| `auto` | 210 | 10 | +R$1.88 | **-R$122.60** | loses → wins |
| `musical_instruments` | 38 | 5 | +R$3.07 | **-R$10.10** | loses → wins |
| `electronics` | 42 | 3 | +R$1.88 | +R$2.18 | stays losing |

`auto` is the significant one: it was D20's largest-by-sample-size
losing category (second-largest category in the dataset overall, 210
sellers) and is now a decisive win, by a wide margin relative to its
old magnitude. `musical_instruments` flips the same direction on a
smaller base. Neither flip is investigated mechanistically — same
timebox limitation as D20 — but the direction is consistent with D21:
calibration made the model's economics more favourable overall, and
these two categories were close to the win/lose boundary at 9 events or
fewer, exactly where a shift in score distribution would be expected to
move the sign.

`electronics` does not flip and is now the largest-by-sample-size
losing category that survives from D20's original two. The full ≥20-seller
losing set shrinks from 9 to 7: `electronics` (42), `watches_gifts` (52),
`construction_tools_construction` (50), `unknown` (63, not a real
category — a missing-data catch-all), `consoles_games` (23), `drinks`
(21), `kitchen_dining_laundry_garden_furniture` (21) — each still on 0-3
events, the same small-N caveat D20 raised.

**Answering the user's two specific questions:** the new-seller cohort
stays inert, not harmed (tenure — no flip, margin still negligible
relative to other bands). Of the two categories D20 called "most
credible": `electronics` stays losing; `auto` does not — it flips to a
clear win. That flip is reported in the README (Section 7) as
instructed.

### D28 — Demo bugfix: FAR selector crash, an empty-looking default, and a visual pass

**Bug: `ZeroDivisionError` on several FAR selector values.** The sidebar's
FAR options were pulled from `figures/phase4_calibrated_sweep.csv`, which
has all ten integer-percent points (1-10%). `figures/demo_event_acceleration.csv`
and `figures/phase4_precision_recall.csv` — both read by the same
page — only cover the three points D25 actually precomputed (1%/5%/10%;
`src/prepare_demo_data.py`'s `FAR_POINTS`). Selecting any of the other
seven produced `accel_at_far` with zero rows, and `n_never / n_events`
divided by that zero. Root cause was the selector reading from the wrong
artefact, not a missing guard on one value — fixed by sourcing
`far_options` from `acceleration["far"].unique()` (the three points
every other artefact on the page actually covers) instead of the sweep.
A defensive zero-events branch was added anyway (an explicit "nothing to
report at this operating point" message) in case the artefacts drift
apart again — belt and suspenders, not the primary fix.

**Empty-looking default.** The merchant selectbox previously defaulted
to position 0 of an `event_B`-then-`seller_id` sort, with no guarantee
that merchant was ever flagged. `default_merchant_and_week()` now picks,
at the default 5% FAR, a merchant the model actually beats the naive
rule on — at the *median* acceleration (2 weeks) among such merchants,
not the most dramatic outlier, so the first screen is representative of
the banner's own claim rather than cherry-picked to look better than the
evaluated result. The week defaults to that merchant's model-alarm week,
so the "Flagged at this FAR?" metric reads Yes on load. Any other
merchant remains selectable and defaults to its most recent test week,
same as before.

**Verified before pushing, not assumed:** wrote a throwaway
`streamlit.testing.v1.AppTest` script (not committed — same as D25's
verification, which also wasn't a committed pytest file) exercising all
three FAR options from a fresh app each time, both an explicit event and
non-event merchant at every FAR, and both endpoints of the week selector
for each. No exceptions in any of the 21 scenarios. Also checked
structurally that both required honesty banners (`st.warning` ×2) and
the dynamic outcomes banner (`st.info`) still render on the default
path, and that the default merchant/week lands on a flagged, confirmed
cessation (the "Known outcome" section appears).

**Visual pass**, within the constraints given (no gauges/dials/0-100
scores/red-amber-green badges/alert icons; colour only where a quantity
has genuine direction; native Streamlit components over injected CSS):

- Grouped sections with `st.container(border=True)` (merchant snapshot,
  recommended action, cost trade-off) and `st.columns(..., border=True)`
  for the metric rows — Streamlit's own bordered-container primitive,
  not custom CSS.
- Added a small hazard sparkline (last 12 available weeks,
  `st.altair_chart`) with a dashed grey reference line at the selected
  FAR's flag threshold — a factual line already used elsewhere on the
  page for the flag decision, not a danger-level indicator.
- Replaced the "what changed since last week" dataframe with a
  horizontal bar chart of the top 5 signed feature-contribution deltas,
  coloured by direction (raises/lowers hazard) — the one place colour
  was used, because a signed contribution genuinely has a direction, per
  instruction. Two-colour categorical scale, not a stoplight.
- Removed `delta_color="inverse"` from the hazard metric's week-over-week
  delta. On reflection this was already a soft version of the thing the
  instruction rules out: it painted a hazard *increase* red and a
  *decrease* green, i.e. invented a danger direction for a number the
  instruction says doesn't have one. Set to `delta_color="off"` (neutral
  grey) instead — a pre-existing choice from D25, changed here under the
  same reasoning newly stated, not left as an inconsistency once noticed.
- Added short `st.sidebar.caption()` helper text under each sidebar
  control, including a one-line explanation of what FAR means.
- Both required honesty banners (`st.warning`) kept at their original
  size and prominence — not shrunk, not moved into an expander — with a
  plain `st.subheader` placed above each for section hierarchy, not as a
  replacement for the banner's own weight.
- Centralised R$ and % formatting through two small helpers (`reais()`,
  already-existing `far_label()`) instead of ad hoc f-strings at each
  call site, so decimal-place choices are made once rather than per
  metric.

Ruff clean, full pytest suite unaffected (`app.py` is not imported by
anything under `src/` or `tests/`).

### D29 — FAR threshold methodology disclosed (not yet resolved); README reframed; app.py precision surfaced

**Open methodological question, answered but not yet acted on.** Asked
directly: are Section 4/5's FAR thresholds chosen on a held-out
validation split, or on the test set itself, to hit a target test-set
FAR? Traced the code (`src/policy.py::score_censored_rows`,
`run_sweep`; `src/phase4_calibrated_sweep.py`; same pattern in
`src/phase2_acceleration_vs_rule.py`): **on the test set itself.**
`neg_scores` — the population a FAR quantile is cut from — comes from
`features_df["week"] > TEST_CUTOFF`, i.e. the same test-period rows
every downstream number (acceleration, economics, precision/recall) is
then evaluated on. ~~`threshold = np.quantile(neg_scores, 1 - far)` is
constructed so the achieved row-level FAR equals the target *by
construction*, on this exact test set.~~ **Corrected in D30: this is not
quite right either — see D30's tie-plateau finding below.** TRAIN is
used to fit the model coefficients and the D21 isotonic calibrator; it
plays no role in picking the threshold.

This does not leak event-row information (only censored/negative rows
define the threshold) and doesn't affect the ablation's AUC-based
numbers (rank-based, threshold-independent). But it does mean "5% FAR"
is not an independently-validated operating point that happens to land
near 5% on unseen data — ~~it's exact by construction on the test set
itself~~ **it's close to the target by construction on the test set
itself, but not exact even there — D30**, and the README did not say so
anywhere before this entry (checked: no occurrence of "chosen on the
test set" or equivalent language in any FAR-related passage). **Not
fixed this round** — the
two options put to the user (state explicitly vs. move threshold
selection to a separate validation split) trade off honesty-by-labelling
against a materially bigger rebuild (every Section 4/5/7 number would
need re-deriving against a threshold picked on a third split), and which
one to do is the user's call, not made here. This entry exists so the
fact is on record regardless of which way that goes.

**README restructured**, per instruction, with numbering and section
order otherwise unchanged from SPEC.md — **deviation from SPEC's
README-requirements item 2** ("the limitations, second — before any
results"): Section 2 now opens with a compact version of the audit
finding (apparent 0.89–0.97 AUC → chance once corrected — previously
told in full only in Section 3) before its three limitation bullets,
rather than opening on disclaimers cold. Limitations reduced from four
paragraphs to three crisp ones by merging the two domain-mismatch
paragraphs (marketplace-vs-aggregator business relationship; Brazil-vs-
India market) into one, since both are facets of the same underlying
gap. Content preserved, not cut: the 86.2% benign-exit figure, the
cost-parameter disclosure, and the full domain-mismatch reasoning are
all still present, just tightened. Section 3's headline sentence gained
a footnote making the row-level/seller-level FAR distinction explicit at
its first and most prominent mention (5% row-level ≈ 19.4% seller-level
at that operating point) — a reader skimming only the bold sentence
would otherwise read "5% false-alarm rate" as "5% of merchants," which
is off by roughly 4x at this operating point. Section 4 and 5's
previously-bare "FAR" table headers renamed to "row-level FAR" for the
same reason, now that Section 4's table already carried a "seller-level
FAR" column alongside it. Section 6: the "not a no signal exists"
paragraph gained a boxed callout (blockquote — a first for this
document, used because the instruction asked for something visually
distinct) explaining why the pooled 0.68–0.70 AUC and Section 3's
0.53–0.59 point-in-time AUC are different questions on the same data,
not a contradiction. The ablation's closing conclusion — "the ceiling
here is in the data and features, not in the linearity of the model
class" — softened to state what one untuned, default-hyperparameter GBM
run actually supports: evidence pointing toward limited predictive
information in the features, not proof that linear capacity is the
bottleneck, since a single untuned run cannot establish a class-wide
ceiling. D24 above amended to match (struck through, not silently
rewritten) rather than leaving the two documents making different-
strength claims about the same result. "Interactive demo" section's
prose updated to describe what `app.py` now surfaces (below).

**`app.py`:**
- The week-over-week hazard delta was a difference of two percentages
  displayed with `%` formatting — numerically already the right
  magnitude (a 2-percentage-point move printed as "+2.00%"), but the
  unit label was wrong and readable as a 2% *relative* change. Changed
  to explicit "+X.XX pp vs. last week" — same number, correct unit.
- FAR selector now shows, directly beneath it: the row-level FAR
  (restating the selectbox value), the equivalent seller-level FAR from
  `phase4_calibrated_sweep.csv`, and that operating point's precision/
  recall/flagged-row counts from `phase4_precision_recall.csv` — all
  three previously only reachable via the "Population-level economics"
  expander, now visible at the point the FAR is actually chosen, not
  gated behind a click.
- "Recommended action" renamed to "Simulated policy action," with a new
  leading caption stating plainly that the model determines only the
  flag — the reserve percentage applied is a fixed `config/costs.yaml`
  assumption the model has no say over. The redundant older sentence
  making the same point lower in the section was removed rather than
  left duplicated.

**GitHub repository description — not changed by this session.** No
`gh` CLI and no `GH_TOKEN`/`GITHUB_TOKEN` in this environment, and a
repo-settings edit is an outward-facing change this session has no way
to make without one. Exact text handed to the user to apply themselves
(`gh repo edit --description "..."` or the GitHub web UI), corrected per
instruction to describe marketplace fulfilment telemetry and a fixed,
not dynamic, reserve.

Verified: `ruff check src/ tests/ app.py` clean; AppTest re-run across
all three FAR options and both an event and non-event merchant (mirrors
D28's method) — no exceptions. `pytest` unaffected (no `src/`/`tests/`
files touched this entry).

### D30 — Train-derived thresholds bound the test-set selection concern D29 raised: it's real, it moves the headline, and a second issue was found underneath it (headline decision superseded by D31)

**Instruction, precisely:** don't rebuild against a third validation
split, don't leave D29 at disclosure either. Derive thresholds from
TRAIN negatives at the nominal 1%/5%/10% quantiles, apply them unchanged
to test, report the achieved test-set FAR (row- and seller-level) both
origins produce, and promote whichever set of numbers turns out to be
the honest headline once checked — train-derived if the numbers moved
materially, test-derived (kept, not deleted) if they were close.

**Method (`src/phase4_train_derived_thresholds.py`, new script, not a
rewrite of any committed one).** `score_train_negative_rows()` mirrors
`policy.score_censored_rows()` exactly — same `_labels`/`event_B`
globally-censored-seller population, same feature/score pipeline — with
`week <= TEST_CUTOFF` instead of `> TEST_CUTOFF`, so the two threshold
origins differ only in which window supplies the quantile population,
nothing else. Thresholds calibrated the same way as everywhere else in
this project (D21's isotonic calibrator, fit on TRAIN only, applied
post-hoc). Applied to the *same* TEST-period scoring already used for
the existing D21 sweep — reused, not recomputed — via three small
functions (`economics_at_threshold`, `precision_recall_at_threshold`,
`status_breakdown_at_threshold`) that accept an external threshold
instead of deriving one internally, factored out of
`phase4_calibrated_sweep.run_calibrated_sweep` and
`phase4_precision_recall.py`'s logic rather than reimplemented.

**Base-rate drift, quantified as instructed, not explained away:**
row-level event rate train 0.5305% → test 0.6800%, a 1.28x ratio
(`fit["drift"]`, already computed by `model.py`, just not previously
surfaced next to this question). This is the mechanism: a threshold
calibrated to TRAIN's lower-hazard score distribution sits well inside
TEST's higher-hazard distribution rather than at its edge, so it flags
more of TEST than intended.

**Result: the numbers moved materially, not marginally.**

| nominal FAR | threshold origin | threshold | achieved row FAR | achieved seller FAR | events accelerated | net Δcost/1000mw | precision | recall |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1% | test-derived | 0.200000 | 2.5% | 11.5% | 26/237 | -R$16.50 | 3.5% | 13.1% |
| 1% | train-derived | 0.051335 | 7.3% | 23.9% | 107/237 | -R$110.88 | 4.1% | 47.3% |
| 5% | test-derived | 0.054545 | 5.9% | 19.4% | 85/237 | -R$98.03 | 4.2% | 38.8% |
| 5% | train-derived | 0.040000 | 12.0% | 37.0% | 158/237 | -R$155.33 | 3.7% | 70.0% |
| 10% | test-derived | 0.040389 | 12.0% | 36.9% | 158/237 | -R$155.33 | 3.7% | 70.0% |
| 10% | train-derived | 0.012987 | 15.6% | 47.2% | 207/237 | -R$189.60 | 3.8% | 94.9% |

Largest deviation: nominal 1% train-derived achieves 7.3% row-level
FAR — 7.3x the target. At nominal 5%, the gap is achieved 12.0% vs. a
5% target (2.4x), and the train-derived "5%" row lands almost exactly
on the test-derived "10%" row (thresholds 0.040000 vs. 0.040389, one
step apart on the calibrator's own discrete score levels — every other
number in that pair matches to within rounding). **No sign flip
anywhere: the model beats the naive rule at every nominal FAR under
both origins.** What moved is the *size* of the win, not its direction —
net Δcost at nominal 5% goes from -R$98.03 to -R$155.33/1000mw, a
1.6x change, not a reversal. One number is invariant to the choice: the
median acceleration among events the model does beat the rule on is 2.0
weeks either way — the drift is entirely in how many events clear that
bar, not in how early the ones that do get caught.

~~**Decision, per instruction: train-derived numbers become the
headline; test-derived stay as the labelled comparison, not deleted.**
README Sections 3 and 4 rewritten accordingly — Section 3's bold
headline sentence now reads 67%/27%/6% (was 36%/58%/6%), Section 4 leads
with the train-derived table and keeps the test-derived one immediately
below, explicitly labelled. `src/phase4_presentation_figures.py`'s
`fig3_model_vs_rule()` split into a shared `_fig3_render()` called
twice: `figures/readme_model_vs_rule.png` now renders the train-derived
breakdown (the figure embedded at the top of Section 4), and
`figures/readme_model_vs_rule_test_derived.png` is the new comparison
figure, generated by the same script, referenced but not embedded (two
large figures back to back was worse than one embed plus a text
pointer). Both regenerated and their printed never/ties/beats counts
spot-checked against `phase4_train_derived_thresholds.csv` — exact
match.~~

**Superseded by D31, below.** The "moved materially" read above compared
train-derived and test-derived at the *same nominal target* (5%), which
is not the same as comparing them at the same *achieved* FAR — and at
matched achieved FAR (~12%), D31's check found the two methods give
essentially identical economics. The apparent improvement here was a
substantially looser threshold, not a better threshold-selection method.
The headline was reverted to test-derived; the figure filenames were
swapped back (`readme_model_vs_rule.png` is test-derived again,
`readme_model_vs_rule_train_derived.png` holds the train-derived one).
The base-rate-drift finding and the tie-plateau correction immediately
below both survive this correction untouched — only the "which number
leads" decision was wrong.

**Second, independent finding, uncovered while building the check —
D29's own "exact by construction" claim about the test-derived
threshold was itself wrong, corrected above (struck through, not
silently rewritten).** Verified directly (not assumed) by computing
`(calibrated_scores >= threshold).mean()` against the same population
the threshold was quantiled from: the achieved row-level FAR for the
*test-derived* thresholds is 2.5%/5.9%/12.0% at nominal 1%/5%/10% — not
1.0%/5.0%/10.0%. Same mechanism D21/D23 already documented for
non-monotonic precision: isotonic calibration collapses the censored-row
population's scores into 46 discrete levels, `np.quantile`'s
interpolated cut lands at or near one of them, and "≥ that level" sweeps
in the whole tied block, which does not generally sum to exactly the
requested fraction. Test-derived is still much closer to nominal than
train-derived (worst case 1.2x vs. 7.3x), so the *comparative* finding
above is unaffected — but "exact by construction" was an unchecked
overclaim, present in D29 and in the README before this entry, now
corrected in both. Lesson applied directly: this is exactly why the
check was run empirically rather than reasoned about from the formula.

~~**Explicitly flagged, not fixed this round — same "flag rather than
silently drift" pattern D26 used for Section 7 before D27 caught it up:**

- **Section 7 (slice analysis, D20/D27)** still scores against the
  test-derived 5% threshold. Re-running it against the train-derived
  threshold would re-derive every per-slice margin, not just relabel
  them — a job the size of D27 itself. Caveat added to the README
  section stating the gap and the (unchecked) expected direction.
- **The interactive demo (`app.py`, D25/D28)** still reports
  `demo_event_acceleration.csv`'s test-derived numbers (36%/58%/6%),
  which Section 3 no longer treats as the headline. `src/prepare_demo_data.py`
  would need its threshold source changed and its artefacts regenerated —
  flagged in the README's "Interactive demo" section rather than left
  silently mismatched.
- **The D17 sensitivity/tornado analysis** is unaffected in substance —
  it tests cost-*parameter* breakeven ranges, orthogonal to where the FAR
  *threshold* comes from — but its existing pre-calibration caveat
  (D26) now needs to disclaim against two calibrated tables instead of
  one; wording updated in the README, analysis itself not re-run.~~

**Moot as of D31, not just resolved.** Once the headline reverted to
test-derived, all three of these were already consistent — Section 7,
the demo, and D17's wording had never been rebuilt against the
train-derived number in the first place, so nothing needed re-fixing,
only re-confirming (D31 did this explicitly rather than assuming it).

Verified: `ruff check src/ tests/ app.py` clean; `phase4_train_derived_thresholds.py`
and `phase4_presentation_figures.py` both run end-to-end and their
printed output cross-checked against each other and against the
committed CSVs/JSON. `pytest` unaffected (no test file exercises either
script).

### D31 — D30's headline promotion was wrong: matched-achieved-FAR, the two methods agree; test-derived restored as headline

**The correction, stated by the user, verified rather than taken on
faith:** D30 compared train-derived and test-derived thresholds at the
same *nominal* target (5%) and called the train-derived economics
better. But train-derived-at-nominal-5% achieves 12.0% *actual* FAR,
and test-derived-at-nominal-10% also achieves 12.0% — nearly the same
achieved operating point by two different routes. Comparing them at
matched nominal targets was comparing a tight threshold to a loose one
and crediting the looseness to the method.

**Checked directly: at matched achieved FAR, the two methods give
essentially the same economics.** All six already-computed thresholds
(three test-derived, three train-derived, from D30's own
`figures/phase4_train_derived_thresholds.csv` — no new computation
needed, this was a re-analysis of existing numbers) sorted by achieved
row-level FAR instead of nominal target:

| achieved row FAR | origin | nominal | events accelerated | net Δcost/1000mw | precision | recall |
|---:|---|---:|---:|---:|---:|---:|
| 2.5% | test | 1% | 26/237 | -R$16.50 | 3.5% | 13.1% |
| 5.9% | test | 5% | 85/237 | -R$98.03 | 4.2% | 38.8% |
| 7.3% | train | 1% | 107/237 | -R$110.88 | 4.1% | 47.3% |
| **12.0%** | **test** | **10%** | **158/237** | **-R$155.3304** | **3.7%** | **70.0%** |
| **12.0%** | **train** | **5%** | **158/237** | **-R$155.3255** | **3.7%** | **70.0%** |
| 15.6% | train | 10% | 207/237 | -R$189.60 | 3.8% | 94.9% |

At the matched pair: net Δcost differs by R$0.005/1000mw (rounding
noise, not signal), events accelerated identical (158/237), recall
identical to four decimals (70.0422%), precision within 0.01 points.
**Origin does not move the economics once achieved FAR is held fixed;
only FAR does.** D30's "the achieved FAR moved materially — this is the
headline table now" conclusion followed correctly from its own
comparison, but the comparison itself was the wrong one — nominal-vs-
nominal instead of achieved-vs-achieved. Caught by the user, not by this
project's own checking; recorded here so the record shows how, not just
that it was fixed.

**Limitation, stated rather than glossed:** only one of the six points
has a close cross-origin partner. Test's other two points (2.5%, 5.9%)
have no train-derived neighbour within these three thresholds, and
train's other two (7.3%, 15.6%) have no test-derived neighbour — three
thresholds per origin is not a dense grid. The matched-FAR agreement is
demonstrated at one point, not proven across the whole range. Extending
it would mean computing thresholds at intermediate quantiles for both
origins specifically to land near each other's achieved FARs — not done
here, a natural next step if this needs to bear more weight later.

**Corrected finding, replacing D30's: threshold transfer is a
deployment robustness caveat, not a better result.** A threshold set
from TRAIN to hit a nominal target degrades on TEST — 7.3x at nominal
1%, 2.4x at nominal 5%, 1.6x at nominal 10% — because the row-level
event rate drifts 0.53% (train) → 0.68% (test), 1.28x. This is real and
worth stating plainly: a threshold inherited from historical data
without periodic recalibration will run measurably looser than intended
in production. It is not evidence the train-derived method produces
better economics — matched-FAR, it doesn't produce *different*
economics at all.

**Reverted, precisely:**
- README Section 3's bold headline sentence: back to 36%/58%/6% (was
  67%/27%/6% under D30). Footnotes 1 and 2 kept and rewritten — footnote
  1 (row-level vs. seller-level, 19.4%) unchanged in substance; footnote
  2 now leads with the tie-plateau "not exact, 5.9%" correction (kept,
  per instruction) and folds the train-derived transfer-degradation
  number in as a caveat, not a competing claim. The "note on which
  numbers are which" paragraph restored to its pre-D30 two-way framing
  (calibrated vs. pre-calibration), with the train-derived transfer
  check named as a third, non-competing entry.
- README Section 4: restored the original test-derived table and
  economics paragraph as the section's lead. Added a new "Threshold-
  transfer robustness check" subsection below it — the train-derived
  table, the 2.4x-at-nominal-5% degradation finding, and the new
  matched-achieved-FAR table above, all framed as a robustness check on
  the headline, not an alternative headline.
- `figures/readme_model_vs_rule.png` regenerated as the TEST-derived
  breakdown again (58.2%/35.9%/5.9%, matching the restored 36%/58%/6%
  headline exactly). The train-derived breakdown moved to
  `figures/readme_model_vs_rule_train_derived.png` (renamed from D30's
  `_test_derived` suffix, which named the wrong one once the headline
  flipped back). `src/phase4_presentation_figures.py`'s `fig3_model_vs_rule()`
  docstring and print statements updated to match; `_fig3_render()`
  itself untouched, since only which threshold gets which filename
  changed, not the rendering logic.
- D17's tornado-sensitivity caveat paragraph: restored to its pre-D30
  wording (disclaims against one calibrated sweep, not two).
- Section 7 and the "Interactive demo" section's D30 gap notices:
  replaced with confirmation that they were never rebuilt against the
  train-derived number and so needed no change back — the gaps D30
  flagged were an artefact of the (wrong) headline promotion, not a real
  drift in those sections themselves.

**Not reverted, because it was correct independent of the headline
decision:** the tie-plateau finding (test-derived achieves 2.5%/5.9%/12.0%,
not exactly 1%/5%/10%) and its correction to D29's "exact by
construction" claim. Both survive untouched — they're true regardless
of which threshold origin leads the document.

Verified: `ruff check src/ tests/ app.py` clean; re-ran
`src/phase4_presentation_figures.py` end-to-end, confirmed
`readme_model_vs_rule.png`'s printed breakdown (58.2%/35.9%/5.9%)
matches the restored README sentence exactly. No new script needed —
D31's matched-FAR table is a re-sort of D30's own committed CSV, not a
new computation, so nothing to re-verify beyond the arithmetic (checked
by hand against the CSV, not just trusted).

### D32 — Demo visual design pass: a considered theme, real hierarchy, cards, no change to what's shown

**Instruction: the earlier plainness constraint was too restrictive —
the result read as unfinished, not deliberately plain. Loosen it.**
Redesign `app.py` to look like a designed research tool rather than a
default Streamlit page, within one hard rule carried over unchanged: no
gauges, no 0-100 risk scores, no red/amber/green threat levels, no alert
icons, nothing implying more confidence or precision than 0.68 AUC and a
minority-benefit result support. No content, number, or piece of
evaluated logic changed in this entry — every figure on the page is
identical to before; only how it's presented changed.

**`.streamlit/config.toml`, new file.** One theme, applied natively
through Streamlit's own theme config rather than fought with CSS
overrides: `primaryColor` (`#2F6F8F`, a muted slate-teal — the one
accent used throughout), a warm off-white `backgroundColor`
(`#F7F6F2`) against a white `secondaryBackgroundColor`, near-black
`textColor`, a muted `grayTextColor` for captions, `headingFontSizes`/
`headingFontWeights` tuned for a tool (h1 2rem, not the 2.75rem
marketing-page default) rather than left at Streamlit's defaults, and
`metricValueFontSize`/`metricValueFontWeight` bumped so `st.metric`
values read as the page's focal point without any custom CSS needed for
that specific ask. `showWidgetBorder`/`showSidebarBorder` enabled so
sidebar controls read as considered inputs, not borderless defaults.
Checked the installed Streamlit version (1.58) actually supports this
extended theme schema before writing it, by reading `streamlit/config.py`
directly rather than assuming from older documentation.

**One CSS block, injected once at the top of `main()` via
`st.markdown(..., unsafe_allow_html=True)`, per instruction ("in one
block ... rather than scattered").** Handles what theme config can't:
section-heading margins (generous whitespace instead of more divider
lines — one `st.divider()` removed, not added), metric-label
typography (small tracked uppercase caps, so the value carries the
visual weight), spacing between named cards, sidebar caption sizing,
and the honesty-banner restyle below. Colours referenced in the CSS are
the same Python constants (`ACCENT`, `ACCENT_WARM`, `INK`, `INK_MUTED`,
`CARD`, `BORDER`) used in the Altair chart specs, defined once, so the
page chrome and the charts can't drift out of the same palette.

**Honesty banners: restyled, not shrunk, not hidden — the harder part
was finding the right DOM node.** `st.warning`/`st.info` content and
placement are untouched; only appearance changed. First attempt
targeted `[data-testid="stAlert"]`'s background directly and did
nothing visible — checked why rather than assumed it worked: rendered
the app, opened the actual DOM (via a headless Chromium screenshot, see
Verification below) and found Streamlit paints the kind-specific colour
wash on two *inner* nodes, `stAlertContainer` (a semi-transparent tint)
and `stAlertContent{{Warning,Info,...}}` (the visible fill), neither of
which is the outer `stAlert` div a first guess would target. Fixed by
overriding both inner nodes' backgrounds to solid white and moving the
accent — one 4px left border in `ACCENT`, no colour-coding by kind — to
the outer box. `[data-testid="stAlertDynamicIcon"] { display: none }`
added for the hard rule against alert icons, though checked and this
Streamlit version doesn't render one by default for `st.warning`/
`st.info` without an explicit `icon=` argument — the rule is defensive,
not fixing an icon that was actually showing.

**Layout changes, per instruction:**
- Merchant snapshot: the hazard metric, a compact sparkline (axis-free,
  sized to sit beside a number rather than stand alone — `sparkline()`,
  new function), "Flagged?", and "Avg. weekly GMV" are one row inside a
  single bordered card, the sparkline given more column width than the
  two smaller metrics so the three metrics plus trend read as one focal
  unit, not four equal-weight blocks.
- "What changed since last week": the existing horizontal signed bar
  chart gained a `mark_rule` at zero (a diverging chart needs a visible
  baseline) and switched from the old ad hoc `#DD8452`/`#4C72B0` to the
  same `ACCENT_WARM`/`ACCENT` used everywhere else on the page — same
  chart, page-consistent colours.
- Every interactive section — snapshot, simulated policy action, what
  changed, known outcome, cost trade-off — is now a named bordered
  container (`st.container(border=True, key=...)`), so the page reads
  as five distinct cards rather than a scroll of same-weight blocks.
  Inner columns (the two cost-trade-off metrics, the snapshot's four
  slots) are NOT separately bordered — nesting boxes inside boxes was
  tried and reads as clutter, not hierarchy; one border per section is
  enough.
- Section headings promoted to `st.header` (h2) for the page's major
  divisions (the two honesty sections, "Outcomes at X FAR", "Merchant
  snapshot") with card titles at `st.subheader` (h3) one level below —
  a real three-level hierarchy (title / major section / card), not four
  same-sized headings competing for attention.

**Verification, two methods, because AppTest alone can't check CSS
rendered:**
1. `streamlit.testing.v1.AppTest`, same script and same coverage as
   D28's method — all three FAR options, an explicit event and
   non-event merchant, both week-selector endpoints. No exceptions.
2. **New for this entry: rendered the app for real** (`streamlit run
   app.py --server.headless true`) and captured full-page screenshots
   with a headless Chromium via Playwright (installed locally for this
   check only — not added to `requirements.txt`, the demo itself never
   imports it). This is how the alert-banner bug above was actually
   found: AppTest confirmed the page didn't crash, but only a rendered
   screenshot showed the banners still carrying their old yellow/blue
   background wash after the first CSS attempt. Re-screenshotted after
   the fix and confirmed solid white banners with the single accent
   border, no icons, correct card spacing, and the sparkline sitting
   beside the hazard metric as intended, before calling this done.

Ruff clean. No `src/` or `tests/` files touched; `pytest` unaffected.

### D33 — Restructure, not restyle: caveats moved to their own tab, sidebar cut to a stat block, merchant view is now the first thing shown

**Instruction: D32 restyled the page but didn't fix that it still reads
as mostly caveats.** "Read this first," "Outcomes at 5% FAR," and "Read
this too" occupied most of the visible area before any merchant content
appeared. Two changes, in order, then a light polish pass on what
remained — nothing removed, nothing softened, everything still one
click away.

**One short top banner replaces three full-length ones.** New text,
still `st.warning`, still the same D32 restyled callout:

> The model detects that a seller has already gone quiet, a little
> faster than a fixed rule — it does not predict distress weeks in
> advance (0.53–0.59 AUC on that specific claim; near chance). Full
> evaluation, the outcomes breakdown at the FAR selected below, and the
> calibration caveat are in **Method & limitations**, one tab over.

Every word from the original three banners still exists, verbatim,
unshortened — moved, not cut. `st.tabs(["Merchant view", "Method &
limitations"])`: the merchant view (snapshot, simulated policy action,
what changed, known outcome, cost trade-off, population-economics
expander) is `tab_merchant` and renders first, since Streamlit opens
the first tab by default -- exactly "primary content," not scrolled
past three disclosure sections to reach it. `tab_method` holds, under
three `st.subheader`s, the full original "What this model actually
does" warning, the full dynamic "Outcomes at X% FAR" info/warning
(unchanged logic, including the defensive zero-events branch), and the
full "Calibration caveat" warning plus the out-of-scope caption — all
identical text to before this entry, only relocated. Implementation
note: `main()`'s body was getting long with two full render paths
inline, so the merchant-view and method-tab content were factored into
`_render_merchant_view()` and `_render_method_and_limitations()`,
passed the same local variables `main()` already had rather than
recomputing anything.

**Sidebar cut by roughly two-thirds, prose replaced with a stat
block.** FAR's definition is now one line ("**FAR**: share of a healthy
seller's weekly rows flagged as a false alarm.") instead of a
three-sentence paragraph. The three prose captions that used to state
row-level FAR, seller-level FAR, and this operating point's precision/
recall/flagged-row counts as full sentences are now six `st.metric`
calls in a 2×3 sidebar grid (Row FAR / Seller FAR, Flagged rows / True
events, Precision / Recall) — labelled numbers, not sentences, per
instruction. The "roughly N alerts per true cessation row" derived
ratio from the old prose was dropped rather than kept as a seventh
stat — it's computable from the two numbers already shown (flagged
rows, true events) and wasn't one of the six figures asked for; not a
caveat, so nothing lost by cutting it. Merchant section captions
similarly cut: "Any seller in the held-out test window. Sellers with a
confirmed cessation in the test set are marked and listed first.
Defaults to a merchant the model actually flags, so the page below
isn't empty on load." (three sentences) → "Test-set sellers; confirmed
cessations marked and listed first." (one clause) — the "why it
defaults this way" justification was implementation detail for a
developer reading the code, not something a user needs from the
sidebar; it's still in this docstring and D28.

**Light polish, per instruction, on what remained:** named cards
(`.st-key-*`) gained explicit padding and a subtle `box-shadow` (kept
deliberately faint — 5% alpha — so it separates the card from the page
without reading as elevation/emphasis it hasn't earned) on top of D32's
native border; card bottom margin increased slightly (1.85rem →
2rem) for more consistent vertical rhythm between sections now that
there are fewer of them competing for attention.

**Hard rule carried over unchanged, re-confirmed by inspection:** no
gauges, no 0-100 scores, no red/amber/green threat levels, no alert
icons anywhere in the restructure — the top banner and both tabs use
the same D32 callout styling, no new visual vocabulary introduced.

Verified: `ruff check app.py` clean. `streamlit.testing.v1.AppTest`
re-run with the same script and coverage as D28/D32 — all three FAR
options, both an explicit event and non-event merchant, both week-
selector endpoints — no exceptions; the default run's metric list now
also includes the six new sidebar stat values (`5%`, `19.4%`, `2,212`,
`92`, `4.2%`, `38.8%`), confirming the stat block renders with real
data, not placeholders. Also rendered for real (`streamlit run` +
headless Chromium screenshot, same method as D32) and visually
confirmed: the merchant view is what a first-time visitor sees with no
scrolling past caveats, the Method & limitations tab reproduces every
original sentence unabridged, and the card shadow/padding change is
visible without reading as new emphasis.

### D34 — Demo's sidebar contradicted the README's own FAR methodology; fixed, plus a Section 4 findability check

**The bug: the sidebar's "Row FAR" stat showed the nominal target as if
it were the achieved figure.** Selecting 5% FAR showed "Row FAR: 5%,"
but this project's own methodology (`DECISIONS.md` D29/D30) established
that the achieved row-level FAR is a different, larger number —
isotonic calibration's tie-plateaus mean a threshold quantiled to hit 5%
actually flags 5.9% of test rows (2.5% at the 1% target, 12.0% at the
10% target). README Section 4's table has carried both figures side by
side since D30; the demo's sidebar never did, and quietly asserted the
number the README explicitly corrected. Not a new finding — the numbers
were already known and already in a committed artefact — the bug was
that the demo's own UI wasn't reading them.

**Fix: three FAR figures now shown, not one, read from the artefact
that produces them rather than recomputed or hardcoded.**
`load_data()` gained a fourth read, `figures/phase4_train_derived_thresholds.csv`
filtered to `threshold_origin == "test_derived"` (the demo's own
operating configuration — D31 restored test-derived as the headline
after D30's brief detour) and indexed by `nominal_far` — the exact same
artefact README Section 4's "achieved row-level FAR" column reads, so
the two cannot drift apart the way the sidebar and the README just did.
Sidebar now shows, as a single full-width `st.metric` (first attempt
used a 3-column split — "5%," "5....," "19..." all truncated in the
narrow sidebar, caught by screenshot before committing, not assumed to
render fine): **"Row FAR: target → achieved" — "5% → 5.9%."** Seller
FAR keeps its own full-width row below it (a fourth quantity, distinct
from both row-level numbers), then flagged rows/true events and
precision/recall stay as 2-column pairs, unchanged from D33.

**Same fix applied to the Method & limitations tab's "Outcomes at X
FAR" heading and banner, per instruction** — this made the identical
mistake, one level of abstraction further from the sidebar than the
first inspection caught. Heading changed from `f"Outcomes at
{far_label(far)} FAR"` to `f"Outcomes at a {far_label(far)} FAR
target{achieved_clause}"`, and the banner's own opening sentence
("**At a 5% false-alarm rate, on the 237 confirmed cessations...**")
gained the same `{achieved_clause}` — "(achieved 5.9% on this test
set)" — inline, immediately after "target," not left for a reader to
infer. `achieved` is computed once in `main()`'s sidebar block and
passed into `_render_method_and_limitations()` rather than
recomputed, so the sidebar stat and the Method tab's heading always
agree by construction.

**Checked, not assumed, that this was the full extent of it:** audited
every `far_label(far)` call site in `app.py` (`grep -n`). Three were
left unchanged after inspection, deliberately, because they don't make
achieved-behaviour claims: "No additional reserve recommended at the 5%
operating point" (says "operating point," already correctly framed as a
setting label, not an achieved rate), "(threshold 0.0545 at 5% FAR)" in
the policy-action card (names which threshold value was applied, with
the exact threshold given alongside — not a rate claim), and "At 5%
FAR, the model flagged this merchant 2 weeks before..." in the known-
outcome card (a single merchant's flag timing, not a population-rate
statistic to which achieved-vs-nominal applies). The distinction that
matters: does the sentence claim something about what happened across
the test set at this rate, or does it just name which sidebar setting
produced this outcome? Only the first kind needed the fix.

**README grep sweep, defensive, not expecting to find anything new**
given how much scrutiny Sections 3-4 already got in D29-D31: checked
every remaining "false-alarm rate"/"FAR" mention against this same
test. All either already carry the achieved figure alongside (Section
4's table, Section 3's footnotes), are clearly labelled "nominal" in a
table header with a cross-reference to where achieved lives (Section
5's precision/recall table, D29), or are prose narrating a table's own
row labels immediately adjacent to that table (Section 4's opening
paragraph, Section 5's recall sentence) — none found making a bare,
unlabelled achieved-behaviour claim. Nothing changed in the README as a
result of this sweep; the gap was specific to `app.py`.

**Second task: a findability check, not new analysis.** The threshold-
transfer robustness check (D30's finding, corrected framing in D31) has
been fully written up in Section 4 since D31 — the question was whether
a reader would actually find it. They wouldn't have reliably: it sits
after the sensitivity/tornado subsection, which is a different topic
(cost-*parameter* ranges, not FAR *threshold* selection) that a reader
skimming Section 4's headline table has no reason to read through first.
Added one pointer immediately after the headline table's own footnote,
before the unrelated tornado paragraph begins: states the question
plainly ("would these thresholds still be close to their targets on a
different slice of time"), gives the one-line answer (2.4x degradation
at the 5% target), and names the subsection to skip to by its exact
heading text. Section 3's footnote 2 already pointed to "Section 4"
generally (D31); this makes the pointer land at the specific subsection
once inside Section 4, not just at the top of it.

Verified: `ruff check app.py` clean. `streamlit.testing.v1.AppTest`
re-run across all three FAR options and both an explicit event and
non-event merchant — no exceptions; the default run's metric list now
reads `'5% → 5.9%'` where it previously read `'5%'`, confirming the
combined stat renders with real artefact data at every FAR, not a
placeholder. Rendered for real and screenshotted twice (headless
Chromium) — once to catch the 3-column truncation, once after the
full-width fix to confirm "5% → 5.9%" renders without wrapping.
`pytest` unaffected (5 passed, no `src/`/`tests/` files touched).

### D35 — Sidebar regrouped into two labelled blocks; policy wording, an architecture one-liner, and the README title corrected

Four instructed changes, unrelated to each other, done in one entry.

**Sidebar regrouped: "Operating point" then "Test-set performance,"
not six flat metrics.** D33/D34 built the right numbers but left them
as an undifferentiated grid — "what was chosen" (target/achieved/
seller FAR) and "how it did" (precision/recall/alerts) are different
questions, and reading them as one block blurred that. Now:
`st.sidebar.header("Operating point")` → target→achieved row FAR,
seller FAR → `st.sidebar.divider()` → `st.sidebar.header("Test-set
performance")` → precision, recall (2-column), alerts (full width) →
one caption for true-events count. True-events count moved out of the
flat-metric grid per instruction ("move true-events count to a caption
or the Method tab") — kept as a caption immediately below the stats
rather than moved all the way to the Method tab, since it's one clause
directly explaining the "Alerts" number just above it, not a caveat
that needed full relocation.

**Second column-width lesson, same mechanism as D34's first one, this
time in the new block:** first attempt put precision/recall/alerts in
one 3-column row, matching the FAR row's earlier three-item shape.
Screenshotted before committing (same discipline as D34) and found it
truncated ("4....", "38...", "2,...") even though these are shorter
strings than the FAR row's "5% → 5.9%" that prompted the original
full-width fix — the actual constraint is D32's bumped
`metricValueFontSize` (2.1rem, tuned for the merchant view's focal-point
metrics), which doesn't fit three columns in a ~280px sidebar
regardless of string length. Fixed to precision/recall as a 2-column
pair (this width does fit, per D34's own working example) and alerts as
its own full-width metric. Lesson generalised in a code comment at the
call site so the next stat added here doesn't repeat the same
3-column mistake.

**Policy section wording:** the unflagged case read "No additional
reserve recommended," inconsistent with the section's own D33 rename to
"Simulated policy action" — "recommended" implies an opinion being
offered, when the panel's whole point (stated in its own caption) is
that this is a mechanical threshold policy, not a recommendation
engine. Changed to "No additional reserve under this simulated policy."

**Architecture one-liner added near the top of the README,** per
instruction, directly after the existing "Reproduce every number..."
paragraph and before Section 1: Olist orders → weekly merchant panel →
leakage-safe features → discrete-time hazard model → isotonic
calibration → FAR threshold → merchant flag → simulated reserve policy
→ cost evaluation. One line, no new numbered section, matching the
existing un-numbered preamble block rather than disrupting SPEC.md's
eight-section README ordering.

**README title changed:** "Merchant distress early-warning → dynamic
reserve sizing" → "Merchant Cessation Early-Warning & Reserve Policy
Simulation" — the old title claimed dynamic (continuous, hazard-sized)
reserve sizing, which D15 explicitly scoped out in favour of a binary
threshold policy with a fixed reserve percentage; the title had been
overclaiming since that decision, just never revisited. `SPEC.md`'s own
title ("Specification: merchant distress early-warning → dynamic
reserve sizing") deliberately left unchanged, checked rather than
assumed to also need fixing: `SPEC.md` is the *target* document — what
the brief specified before D15 narrowed scope — and its own stated
philosophy is that `DECISIONS.md` records deviations from it rather
than the target being retroactively edited to match what was actually
built. Grepped both files plus `DECISIONS.md` for the old phrase to
confirm no other stale copy of the title exists.

Verified: `ruff check app.py` clean. `streamlit.testing.v1.AppTest`
re-run across all three FAR options and both an event and non-event
merchant — no exceptions; the default run's metric list now reads
`'4.2%', '38.8%', '2,212'` as three separate entries (precision, recall,
alerts) in the new block, confirming the 2-column-plus-full-width
layout renders with real data. Rendered and screenshotted three times
in total across this entry (one 3-column truncation caught, one
full-width confirmation, one final full-sidebar check of both blocks
together). `pytest` unaffected — no `src/`/`tests/` files touched.

### D36 — Layout overhaul: no sidebar, a real hazard trajectory chart, status pills, background-contrast sections

A full restructure of `app.py`'s layout, with three explicit exclusions
held to throughout. No number, threshold, or piece of evaluated logic
changed — same artefacts, same computations as D35, only how the page
is built and laid out.

**Chrome, sidebar, width.** Streamlit's own chrome (deploy button, main
menu, toolbar actions, status widget, footer) hidden via CSS targeting
their stable `data-testid`s; the header bar shrunk rather than
`display:none`'d, so the page doesn't jump on load. Every `st.sidebar.*`
call removed. `[data-testid="stAppViewBlockContainer"]`'s `max-width`
set to 100% so the now-sidebar-less page actually uses the full window
width `layout="wide"` already asked for, rather than sitting in a
centred column with no sidebar to justify the gutter.

**Toolbar replaces the sidebar.** FAR, merchant, and week selectors
moved into one `st.container(key="toolbar")` row (`st.columns([1, 2,
1])`), styled as a slim card. The explanatory captions the sidebar used
to carry (D33/D35) moved to each selectbox's own `help=` tooltip (the
"?" icon) instead of being dropped — compact by default, still one
hover away, not lost. Selectbox creation order (FAR, merchant, week)
kept identical to the old sidebar's order specifically so the existing
AppTest verification script's `at.selectbox[0/1/2]` indexing kept
working without modification.

**Operating-point metrics preserved exactly, per instruction, just
relocated.** Target row FAR, achieved row FAR (D34), seller FAR,
precision, recall: five `st.metric`s in one row below the toolbar,
identical values and sources to D35's sidebar blocks (same
`achieved_far_lookup` artefact read, same `precision_recall`/`sweep`
lookups). Alerts count and true-events-caught, previously a sidebar
metric plus caption (D35), condensed into one caption line under the
stat row — content preserved, just no longer a separate metric widget,
since the toolbar's job is to stay compact.

**Status pills — the one place a firm line was drawn.** Three pills,
one row, identical neutral style regardless of value: "Historical
replay" (a fact about the demo, not a value that varies), "FAR {X%}"
(restates the toolbar's own selection, small enough to be useful at a
glance without opening the toolbar), and "Flagged" / "Not flagged" —
deliberately the only two words that appear on this pill, ever. No
"HIGH RISK," no severity tiers, no colour change between the two
states — checked directly (screenshotted both states, below) that
"Flagged" and "Not flagged" render pixel-identical apart from the text,
which is the actual mechanism that keeps this from becoming a
categorical risk grade in disguise.

**Hazard trajectory chart, ~60% width, real visual weight.** Replaces
D32's compact axis-free sparkline. Design choice made here, not
instructed but load-bearing for the rest of this entry: shows the
merchant's **full** test-window history, not a trailing sample — this
is what makes "N=8 rule-confirmation date on the chart if it falls
within range" actually meaningful rather than a coin-flip against an
arbitrary window. Four things drawn: a dashed horizontal rule at the
FAR's threshold (unchanged from the old sparkline), a large distinctly-
styled point at whichever week is selected in the toolbar (ties the
Week selector's effect visibly to a specific point on the line, not
just a number elsewhere on the page), a solid vertical rule at the
model's first alarm — computed directly from `merchant_rows` and the
current `threshold` (`first week hazard >= threshold`), not only from
the event-only acceleration artefact, so it works identically for a
merchant that gets flagged without ever becoming a confirmed cessation
— and, for confirmed-cessation merchants, a dotted vertical rule at the
N=8 rule's confirmation date, drawn only if it falls inside the
displayed range.

**Checked, not assumed: does the "otherwise show it below" fallback
ever actually fire?** Verified directly against `demo_test_predictions.csv`:
for all 237 event sellers, `event_week` equals the last available row
in that seller's test-window history exactly — 0 mismatches. Given the
chart now shows the *full* history, the confirmation date is therefore
always inside the displayed range by construction, and the fallback
branch is currently unreachable. Kept anyway, deliberately, as
defensive logic matching this file's own established pattern (the
`n_events == 0` branch, the `achieved is None` branch) — correct given
data that could exist even though today's data never exercises it, and
implements the instructed behaviour rather than assuming the "always
true" case would hold forever.

**"Historical outcome timeline"** (renamed from "Known outcome in the
test set," `is_event`-only, unchanged) states both dates explicitly as
a short list — model alarm, N=8 rule confirmation — rather than only
inside a sentence, and carries the fallback caption for the
(currently-unreachable, per above) case where the confirmation date
isn't on the chart.

**Sections: background contrast + shadow, not nested borders, per
instruction.** Every `st.container(border=True, key=...)` from D32/D33
changed to `st.container(key=...)` (no `border=True`); the visual
separation is now entirely `.st-key-*` CSS — a white background against
the page's off-white, `border-radius`, and a soft `box-shadow` (kept at
the same low alpha D33 used for cards, no heavier). The merchant
snapshot's old 4-column metric row is gone; its two survivors (the hero
hazard number and average weekly GMV) moved into `info_col`, a plain
(no-border) panel with a light background wash, beside the chart.

**Type scale.** `--fs-display` (2.75rem) introduced for exactly one
element: the hero hazard number, now the single most visually dominant
figure on the page with the sidebar's competing stats gone.
`--fs-small`/`--fs-micro` named as CSS variables rather than repeating
bare rem values, for the pills, hero label, and hero delta. Regular
`st.metric` values (operating-point strip, GMV, cost trade-off) stay at
D32's `metricValueFontSize` (2.1rem, set via `.streamlit/config.toml`),
one deliberate step below the hero number — a real scale (display >
metric > body > small > micro), not a single size reused everywhere.

**Excluded, checked against three times each (code, screenshots, this
writeup) before calling this done:**
1. No "HIGH RISK" label or any categorical risk grading anywhere —
   confirmed by inspection: the only state-dependent text on the page
   is "Flagged"/"Not flagged," in one pill style, and the hazard number
   itself carries no colour, icon, or descriptor beyond the percentage.
2. App name unchanged: `st.title("Reserve decision engine — demo")` —
   restored the "— demo" suffix a prior revision had dropped from the
   on-page title (the browser-tab `page_title` still said "(demo)"
   throughout; only the on-page `st.title` had drifted). Caught by
   re-reading the instruction against the actual current string, not
   assumed already correct.
3. Both required honesty elements kept in the primary view: the short
   top banner (content unchanged from D33, now also states "historical
   replay" explicitly in its own first sentence, matching the new
   pill's wording) and the full "Method & limitations" tab (D33's
   three disclosures, byte-for-byte unchanged text).

Verified: `ruff check app.py` clean. `streamlit.testing.v1.AppTest`
re-run across all three FAR options and both an explicit event and
non-event merchant — no exceptions. Rendered for real and screenshotted
(headless Chromium): full page top-to-bottom, a zoomed crop confirming
the dotted rule-confirmation marker actually draws (easy to miss at
full-page scale, checked at pixel level rather than assumed from the
legend text alone), the Method & limitations tab, and both pill states
("Flagged" reached via the default event merchant, "Not flagged"
reached by switching to a non-event merchant and an early week) —
confirmed pixel-identical pill styling between the two states.
`pytest` unaffected (no `src/`/`tests/` files touched).

### D37 — Second layout pass to a specific reference, with three explicit exclusions and a data-availability check

A reference screenshot (a dark-nav-rail research-console mockup) was
given as the structural/density target, with named deviations. This
entry implements the structure closely while holding every prior hard
rule and the three new exclusions given with this instruction. No
number, threshold, or piece of evaluated logic changed anywhere in this
entry — same artefacts as D34-D36, only presentation.

**The three exclusions, resolved before writing any code:**
1. **No app branding.** The reference's logo mark and "Merchant Risk /
   Research Console" label are not implemented. Page header stays
   "Reserve decision engine — demo" with "Historical research replay
   (not a live predictor)" directly beneath — and this entry actually
   *restores* something D36 had silently dropped: the on-page
   `st.title` had lost its "— demo" suffix in an earlier revision
   (caught in D36, fixed there; re-verified here it's still correct).
2. **Left navigation restricted to exactly three items** — Merchant
   review, Method & limitations, About this project. The reference's
   Portfolio overview / Evaluation results / Economic analysis / Data &
   features destinations are not built; those views don't exist in this
   project and weren't asked for. "About this project" is new (below).
3. **Flag status stays strictly "Flagged"/"Not flagged," one accent
   colour, never a severity gradient.** The reference uses an orange
   flag icon/text for the active state and red/green-tinted cost cards.
   Implemented: the flag pill/card uses `ACCENT_WARM` for "Flagged" and
   plain ink for "Not flagged" — one colour, on or off, the same
   distinction already established for the feature-contribution chart's
   signed direction (D32), not a new kind of exception. The cost
   trade-off cards were **not** given red/green tinting to match the
   reference — that specific instruction sentence ("any flag colour is
   a status accent only") scopes the colour allowance to the flag
   status specifically, and red/green on a cost-vs-benefit pair is
   exactly the kind of thing the hard rule carried since D32 rules out.
   Checked by screenshotting both flag states side by side and
   confirming the "Flagged"/"Not flagged" pill styling differs only in
   text and that one accent colour, never severity.

**Left nav replaces the tab structure, not the toolbar.** D36's
`st.tabs(["Merchant view", "Method & limitations"])` became a narrow
left-rail navigation (`st.button` per destination, tracked via
`st.session_state["nav"]`) — this is page navigation only. The FAR/
merchant/week selectors stay exactly where D36 put them: a compact top
toolbar, not the nav rail and not a sidebar of controls. A small "About
this demo" card sits under the nav buttons (matching the reference's
own layout), stating the historical-replay claim in two sentences and
linking to Method & limitations — additive, not a substitute for the
full-length top banner, which stayed on the primary view unchanged.

**Bug found and fixed: nav highlighting lagged one click behind the
content it was supposed to match.** First implementation checked
`if st.button(item, type=(...)): st.session_state["nav"] = item` --
each button's own `type=` argument is evaluated (to decide primary vs.
secondary styling) *before* that same click is detected and state is
updated, so on the render where a click just landed, every button's
highlight still reflects the *previous* nav state, even though the
content below (which reads `st.session_state["nav"]` later in the
script) already switched. Caught by screenshot, not by reasoning about
the code alone: clicking "Method & limitations" visibly rendered the
Method content while leaving "Merchant review" highlighted. Fixed by
moving state updates into `on_click` callbacks (`_set_nav`), which
Streamlit runs *before* the script body re-executes -- re-screenshotted
all three destinations after the fix and confirmed each highlights
correctly and immediately.

**Five primary metric cards, replacing D36's operating-point row in
this position:** calibrated hazard (this week), flag status, current
flag threshold, average weekly GMV, seller FAR — exactly the five
named. Target FAR, achieved FAR, precision, and recall moved to the
"Operating point summary" strip further down (still all present,
nothing dropped — see below); this row is deliberately merchant-
specific, not population-level, matching the reference's own split
between the top row and the summary strip.

**Hazard trajectory: a trailing window ending at the selected week, not
the full history D36 always showed.** This is the mechanism that makes
"if the confirmation date falls inside the window, mark it; if not,
don't stretch the axis, state it below" a real, sometimes-false
condition rather than the always-true one D36's full-history chart
made it (checked there, in D36's own writeup, and now superseded). Adds
a `st.segmented_control("6W"/"12W"/"24W"/"All")` and computes the
window as `merchant_rows[week <= selected_week].tail(n)` — trailing
*from the selected week*, never a future week relative to it, which
also means the "current point" marker is always the window's rightmost
point by construction, and a merchant's future confirmation date (which
for every event merchant equals their last observed row, D36) is
structurally excluded from any window ending before that row — this is
correct, not a bug: showing a not-yet-known future date on a point-in-
time chart would itself be a look-ahead artefact, and the reference
image's own chart exhibits the identical behaviour (its visible x-axis
also ends at the selected week, with the confirmation date stated only
in the panels below, not drawn).

**Degrades gracefully by construction, checked with a real short-
history merchant, not assumed from reading `.tail()`'s docs.** Found
the shortest available test-window history (1 week) and ran the
20W/24W/All range options against it via `AppTest` — no exception, no
padding, `.tail(24)` on a 1-row frame simply returns the 1 row that
exists. This is pandas' own behaviour, not code written for this
entry, but it was verified rather than trusted.

**"About this merchant" panel — checked what's actually available
before writing labels, not before.** Inspected
`figures/demo_test_predictions.csv`'s real columns directly: `category`
and `tenure_weeks` are present as raw per-row values; no order-level
date or order count exists anywhere in the committed demo artefacts
(confirmed by grepping every `figures/*.csv` header, not assumed from
memory). The reference's exact six-field list ("first order," "last
order," "total orders," ...) therefore cannot be shown honestly as
written — two fields are relabelled to what the data actually supports
("first/last week observed [test window]" rather than "first/last
order," since a panel-week is not an order date) and "total orders" is
dropped rather than fabricated, replaced with "tenure at first
observation" (a genuinely stored value, `tenure_weeks` on the merchant's
earliest test-window row) and an explicit caption stating why order-
level fields aren't shown. This is the same "state the gap, don't
fabricate the number" discipline this project has applied to every
other artefact throughout (D20's small-sample categories, D29's tie-
plateau correction, D34's target-vs-achieved FAR fix) — applied here to
a UI-copy decision instead of an analytical one, but the same rule.

**Operating-point summary strip: seven metrics, all previously
established, none recomputed.** Target row FAR, achieved row FAR
(D34), seller FAR, flagged rows, true events, precision, recall — same
sources as D35's sidebar and D36's stat row, now a horizontal strip
matching the reference's density. Target and achieved FAR kept as two
separate metrics with an explanatory caption, per instruction, not
collapsed into one number.

Verified: `ruff check app.py` clean. Two `AppTest` scripts run: the
existing D28/D32/D33/D36 smoke-test coverage (all three FAR options,
event and non-event merchants — no exceptions), and a new script
covering exactly what this instruction asked for and nothing assumed
already covered by the first: every FAR option, an explicitly flagged
merchant, an explicitly non-flagged merchant, a 1-week-history merchant
against the 24W and All range options, and an event merchant at its
first available week with the 6W range specifically to force the
confirmation date outside the displayed window (checked the fallback
text actually appears, not just that no exception was raised). Rendered
and screenshotted for real (headless Chromium) at every stage of this
entry — full page, the outside-window fallback text, all three nav
destinations before and after the highlighting-lag fix, and both flag
states — before calling any of it done. `pytest` unaffected (5 passed,
no `src/`/`tests/` files touched).

