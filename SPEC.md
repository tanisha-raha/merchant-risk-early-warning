# Specification: merchant distress early-warning → dynamic reserve sizing

This is the design document the project was built against — the
engineering content of the original brief, with the project-management
framing and process instructions removed. `DECISIONS.md` records where
and why the actual build deviated from it; this file is the target, not
the retrospective.

## Problem

A payment aggregator carries credit exposure to its own merchants. When a
merchant collects money and then fails to deliver — goes dark, collapses,
or floods refunds — the refunds and chargebacks still have to be
honoured. If the merchant's balance is gone, the aggregator absorbs the
shortfall.

The standard defence is a rolling reserve: hold back a percentage of
settlements for a fixed window. In practice that percentage is set by
crude static rules (category, tenure, manual review).

**Goal:** predict merchant distress from payment telemetry alone, early
enough to act, and convert the prediction into a reserve percentage under
an explicit cost model.

## Core hypothesis

The trend and acceleration of merchant health metrics predict distress
better than their levels. A steady 8% refund rate is fine; 2% → 4% → 7%
over three weeks is not. This is a hypothesis to be tested, not assumed —
if the ablation contradicts it, that is a finding to report, not to bury.

## Design principles

Prefer boring, well-understood methods. The project is judged on
evaluation rigour, not model sophistication. Reach for a more complex
method only when the simple version has been shown insufficient, and be
able to state why.

## Phase 0 — Data viability gate

Dataset: the Olist Brazilian e-commerce public dataset (~100k orders,
~3k sellers, order-level timestamps, delivery status, cancellations,
review scores, roughly two years). Used almost exclusively elsewhere for
buyer-side analysis; the novel angle here is building a **seller-week
panel** from it.

Tasks:

1. Build a merchant × week panel from the order tables. One row per
   seller per active week.
2. Propose two or three candidate definitions of a distress event.
   Starting suggestion, to be critiqued rather than assumed: sustained
   cessation of orders (no orders for N consecutive weeks, never
   resuming) *preceded* by elevated cancellation and late-delivery rates
   in the trailing window. The "preceded by" clause matters — it is
   meant to separate distress from benign exit.
3. For each candidate definition, report: number of sellers, number of
   events, event rate, censoring rate, and the distribution of
   observation lengths.
4. Plot the panel's calendar coverage. Flag any structural artefacts —
   dataset start/end truncation especially, since sellers near the end of
   the window will look like cessations when they are just censored.

**Kill criterion:** if the best definition yields fewer than ~150
distress events, the project does not proceed on this dataset, and does
not compensate with a fancier model. That is a decision point, not
something to route around.

Deliverable: a short written viability finding.

## Phase 1 — Features

Build a feature pipeline over the seller-week panel. Every feature must
be computable using only data available **as of** the week in question.
Look-ahead leakage is the failure mode most likely to invalidate the
whole project, and must be asserted against in tests, not left to
inspection.

Feature families, each in level, trend (slope over trailing 4 weeks), and
acceleration (change in slope) form where it makes sense:

- Refund and cancellation rate
- Fulfilment latency (order → ship, ship → delivery), and late-delivery
  share
- Order volume, and average order value
- Volume-up-while-AOV-down interaction (the discount-driven cash grab
  pattern)
- Share of first-time buyers
- Review score, and review score trend
- Concentration: revenue share of top SKU and top buyer
- Merchant tenure in weeks, and category

Keep the feature set small enough to reason about: under 40 columns.
Document each one in `FEATURES.md` with its rationale and its as-of
guarantee.

## Phase 2 — Model

This is survival analysis, not binary classification. Most sellers have
not failed yet; they are right-censored, and labelling them negative is
wrong.

- **Primary:** discrete-time hazard model (logistic regression on the
  seller-week panel with a time-in-study term). Simple, interpretable,
  handles censoring natively, gives calibrated per-week hazards.
- **Comparison:** Cox proportional hazards, with the proportional-hazards
  assumption checked, not assumed.
- **Optional third:** gradient-boosted survival, and only once the
  simpler models are fit and evaluated first.

Split by time, never randomly. Train on the earlier window, evaluate on
the later one. Report base-rate drift between the two windows. Group by
seller so no seller appears in both train and test.

Calibrate the output. Downstream consumption is of absolute
probabilities, so calibration matters more than ranking.

## Phase 3 — The decision layer

Convert hazard into a reserve percentage under an explicit, parameterised
cost model. Every assumed parameter lives in one `config/costs.yaml` —
none hardcoded elsewhere.

Two-sided cost:

- **Under-reserving:** expected refund shortfall if the merchant fails —
  unreserved liability at the time of failure.
- **Over-reserving:** working-capital cost to a healthy merchant, plus
  attrition risk. Attrition is modelled as a function of reserve burden,
  with the elasticity exposed as a config parameter since it is an
  assumption.

Derive the reserve percentage that minimises expected cost per
merchant-week. Present the resulting policy as a surface over (hazard,
merchant size).

## Phase 4 — Evaluation

The evaluation is the actual deliverable and warrants more time than
Phases 1–3 combined.

**Headline metric: lead time.** Report the distribution of days of
warning before the event, at a fixed false-alarm rate. Target sentence:
"median N days of warning at an X% false-alarm rate." Plot the full
distribution, not just the median.

**Discrimination, time-aware:** concordance index, and time-dependent AUC
at 7/14/30-day horizons. A single aggregate AUC is not an acceptable
headline.

**Calibration:** reliability diagram, Brier score, expected calibration
error. The README must explain why calibration is the binding constraint
here.

**Economic evaluation:** total cost per 1,000 merchant-weeks under the
policy versus four baselines:

1. Flat reserve for every merchant
2. Category-based reserve
3. Tenure-based reserve
4. A binary classifier with a single threshold and no survival treatment

Baseline 4 is the important one. If survival treatment does not beat it,
that must be stated prominently, not minimised.

**Sensitivity analysis:** tornado plot of the economic result across
plausible ranges for every assumed parameter in `costs.yaml`. State
which assumptions the conclusion survives and which it does not.

**Ablation:** levels-only versus levels+trend versus
levels+trend+acceleration — the direct test of the core hypothesis.
Report the result honestly either way.

**Slice analysis:** performance by merchant size, tenure, category, and
volume decile. Identify at least two slices where the model underperforms
a baseline and write them up.

**Fairness note:** an early-warning model will systematically
over-reserve small, new, and seasonal merchants — exactly the segment
least able to absorb a working-capital squeeze. Measure the disparity in
reserve burden across size and tenure bands. Propose a reserve ceiling
for small merchants and show its cost.

## Hard constraints

- **Strictly defensive.** Nothing in this repo may help anyone evade
  detection. No adversarial example generation, no evasion testing, no
  synthetic-fraud generators, not even framed as robustness work.
- **No LLM in the scoring path.** This is a tabular problem; an LLM would
  be worse and slower. If used anywhere at all — e.g. summarising a
  flagged merchant's signals into a reviewer-facing note — it must live
  in a clearly separated module, with the README explaining why it was
  appropriate there and inappropriate in scoring.
- **No look-ahead.** Enforced by tests, not by care.
- **No random splits.** Time-based only.
- **Every reported number reproducible** from a single command against a
  fixed seed.

## Stack

Python. pandas, scikit-learn, lifelines (or scikit-survival), matplotlib.
Ruff for lint, pytest for tests. No deep learning. No notebooks as
deliverables — notebooks are acceptable for exploration, but every result
in the README must come from a script under `src/`.

## Repo layout

```
README.md              ← the artifact reviewers actually read
DECISIONS.md
FAILURES.md
FEATURES.md
config/costs.yaml
data/                  ← gitignored, CSVs supplied locally
src/
  panel.py             ← seller-week panel construction
  features.py
  model.py
  policy.py            ← cost model + reserve sizing
  evaluate.py
tests/
  test_no_lookahead.py
  test_panel.py
figures/
run.sh                 ← reproduces every number in the README
```

## README requirements

Written last, but it is the deliverable. Required contents, in this
order:

1. The problem, in three sentences, with the money quantified.
2. **The limitations, second — before any results.** The distress event
   is a proxy for merchant default, not default itself. The cost
   parameters are assumptions, not measurements. The dataset is Brazilian
   e-commerce, not Indian payments. State all of this plainly and early.
3. The headline lead-time result.
4. Economic comparison against the four baselines.
5. Calibration evidence.
6. The ablation result, including if it contradicts the hypothesis.
7. The failure slices and the fairness disparity.
8. What to do next with real data.

No marketing prose. No rounding numbers in the project's favour. No
omitting a baseline that beats the model.
