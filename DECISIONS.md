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
