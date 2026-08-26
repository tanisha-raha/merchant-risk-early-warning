# Merchant distress early-warning → dynamic reserve sizing

**One-line summary of where this landed:** the hypothesised mechanism
failed, a simpler one works modestly, and the economic case survives
implausibly wide sensitivity bounds.

Reproduce every number in this document with `./run.sh` (lint, tests,
then every phase's scripts, in order). Individual scripts are documented
in `DECISIONS.md`, referenced by entry number (`D1`, `D17`, …) throughout
this README — that file has the full reasoning behind every choice
mentioned here; `FAILURES.md` has the dead ends, including the ones that
turned out to matter (D14 §3, D21).

## 1. The problem

This project's loss category is merchant default — the same family as
fraud, chargebacks, and returns, approached from the other side of the
ledger: it is what happens when a merchant collects payment and then
fails to deliver. The refund and chargeback liability that follows does
not stay with the merchant; it lands on the aggregator holding the
reserve, which is the exposure this project is trying to price and catch
earlier.

A payment aggregator settles money to merchants before delivery is
confirmed, carrying that credit exposure if the merchant then fails to
deliver, floods refunds, or simply disappears; the standard defence — a
rolling reserve held back from settlement — is currently sized by crude
static rules (flat percentage, category, tenure) with no live signal.
Across the ~20-month sample used here, R$13.5 million of total merchant
GMV passed through the platform; 1,919 of the 3,065 sellers placed enough
orders to be evaluable at all, and of those, 477 went on to a confirmed,
silence-based exit. This
project asks one narrow, falsifiable question: can payment telemetry
alone flag a failing merchant earlier and cheaper than the naive rule
that just watches for eight weeks of silence — and the honest answer,
worked out in full below, is "modestly, and only if you're honest about
what 'modestly' means."

## 2. Limitations — read this before any result below

**The distress label is cessation, not default.** It is defined as eight
consecutive silent weeks with no orders, confirmed and never reversed
within the study window (`DECISIONS.md` D3–D6). It is not a chargeback
event, not a bankruptcy, not a merchant-reported closure — it is "this
seller stopped placing orders and never came back." Checked directly
(Phase 0 D-series, `src/phase0_benign_exit.py`): **86.2% of confirmed
cessations (411 of 477) show no elevated cancellation or late-delivery
signal in the weeks before they stop** — no visible quality collapse, no
customer complaints spiking, nothing that looks like failure in progress.
That is consistent with a large share of "distress events" in this
dataset being ordinary attrition — a seller moving to another
marketplace, retiring a side business, running out of seasonal stock —
not merchant default in any sense a payments team would recognise. Every
number in this document is a number about *predicting cessation*, not
about predicting default; the gap between those two things is real and
unmeasured here.

**The cost-model parameters are assumptions, not measurements — every
economic figure in Sections 4 and 5 is a simulation, not an observed
loss.** `config/costs.yaml` holds three numbers — the reserve percentage,
the weekly working-capital cost of holding it, and the fraction of
accelerated reserve that actually offsets a loss — and none of them come
from data. Olist has no financing-cost, reserve-program, or write-off
data to measure them against. No real reserve was ever held, no real
merchant ever paid a real working-capital cost, and no real shortfall was
ever avoided anywhere in this document — every R$ figure below is what
*would* happen under an assumed cost structure applied to *realised*
cessation outcomes, not a record of money that actually moved. They were
picked once, documented, and never tuned to reach a particular answer
(`DECISIONS.md` D16), and Section 4 shows the economic conclusion is
robust to wide, deliberately generous ranges around them — but "robust to
a wide range of guesses" is not the same claim as "measured."

**Marketplace sellers are not payment-aggregator merchants.** Olist
sellers list goods on a marketplace and are evaluated on delivery and
customer satisfaction; a payment aggregator's merchants have a fundamentally
different relationship with the platform — money movement and settlement,
not fulfilment — and correspondingly different failure modes (fraud,
insolvency, chargeback floods) and different available data (transaction-
and settlement-level signals, not order and delivery telemetry). This
project's entire premise — that payment telemetry predicts merchant
failure — is tested here on a proxy business relationship, not the
target one. That gap sits underneath every other limitation in this
section, not just the dataset's currency and label.

**This is Brazilian e-commerce data (Olist, 2017–2018), in Brazilian
Real, evaluated for a hypothesis about Indian payments.** Every R$ figure
in this document is the dataset's real currency, kept that way
deliberately rather than converted to Rupees — an FX conversion would
imply a transfer of relevance to a market this data was never collected
in, which the data cannot support (`DECISIONS.md` D15, D16). Order
patterns, seasonality, refund norms, and financing costs for Indian
payments merchants may differ from Brazilian e-commerce sellers in ways
this project cannot check.

## 3. The headline lead-time result

![Lead-time waterfall: three stages, apparent result to honest result](figures/readme_lead_time_waterfall.png)

The figure above is the whole argument of this section in one image.
**Stage 1** is what a naive read of Section 6's model produces — AUC
0.89–0.97, which looks like strong prediction. **Stage 2** audits that
number by lead time and it collapses to exactly chance (0.499) by 8 weeks
before confirmation — because that k=8 point lands precisely on the
seller's last active week, where soon-to-fail sellers actually scored
*below* still-healthy ones (mean predicted risk 0.0001 vs. 0.0099).
**Stage 3** corrects a flaw in stage 2's own measurement — its k was
counted from confirmation, not from the seller's actual last order, so
every point except k=8 was already inside the silence period, not before
it. Re-anchored to genuinely precede the last order, the result holds at
0.53–0.59 across every horizon tested: still near chance. Full detail
below.

**There is no evidence of genuine multi-week advance warning.** Checked
directly and reported as a negative result, not softened
(`DECISIONS.md` D13, D14 §1): scoring each confirmed cessation at 1, 2, 4, and 8 weeks
*before the seller's actual last order* — i.e. while still genuinely
trading, the fair test of "did we see it coming" — the model's
discrimination sits at 0.53–0.59 AUC at every horizon. Chance is 0.50.
That is not a small early-warning signal fading with distance; it is
close to no signal at any distance tested.

What the model can do is **detect that a seller has already gone quiet**,
and detect it faster than a payments team manually waiting out a fixed
eight-week silence rule would. The honest headline sentence, replacing
"predicts distress N weeks in advance": **at a 5% false-alarm rate, the
model beats the naive eight-week silence rule for 36% of cessations, by a
median of 2.0 weeks — and provides no benefit at all over the naive rule
for the other 58%** (the remaining 6% are flagged the same week the rule
fires — neither an early win nor a miss; `DECISIONS.md` D21, D26). The
lead-time distribution is right-skewed with a long tail out to 17 weeks
for a minority of cases,
but the median case is a two-week head start, not the multi-week advance
warning the project set out to find. The 58% figure is not a footnote —
it is most of what happens, and it is shown that way at the top of the
next section, not buried in a caption.

*A note on which numbers are which, stated once here and not repeated as
a caveat everywhere below: this 36%/58%/6% split is on the calibrated
model — D21 established calibration as this project's operating
configuration, and this is what the interactive demo (`app.py`) also
reports, so the two agree. The pre-calibration split was 30%/65%/5%
(`DECISIONS.md` D14 §2) — a real, previously-reported number, not wrong,
just measured before calibration; it appears clearly labelled as the
"pre-calibration comparison" in Section 5, where D21's calibration check
is discussed, and nowhere else in this document.*

## 4. Economic comparison

![Model vs. the operational baseline: what happens to all 237 test-period cessations](figures/readme_model_vs_rule.png)

The brief's original plan for this section was a comparison against four
baselines (flat reserve, category-based, tenure-based, a binary
classifier with no survival treatment). **That comparison was not built
this round** — scoped out explicitly in favour of finishing the
diagnostics above properly rather than rushing it (Section 8 has the
follow-up plan). What *was* built, and is the one comparison this
document can actually stand behind: the model-triggered early-reserve
policy against the naive N=8-week silence rule itself, which is the
rule any of those four baselines would have to beat too, and the one
already running today in this problem's static-reserve framing.

Swept the row-level false-alarm rate from 1% to 10% and priced both
sides in R$ per 1,000 merchant-weeks, **on the calibrated model**
(`DECISIONS.md` D21, D26 — this project's operating configuration; the
pre-calibration numbers are in Section 5, clearly labelled, not here):
the model-based policy beats the rule **at every false-alarm rate
tested**, and the margin widens as the rate loosens — from
-R$16.50/1,000 merchant-weeks at 1% FAR to -R$155.33/1,000 merchant-weeks
at 10% FAR (negative = the model saves money).

| FAR | events accelerated | net Δcost / 1,000 merchant-weeks | seller-level FAR |
|---:|---:|---:|---:|
| 1% | 26/237 | -R$16.50 | 11.5% |
| 5% | 85/237 | -R$98.03 | 19.4% |
| 10% | 158/237 | -R$155.33 | 36.9% |

**That result is far more robust than it has any right to look, given
Section 3's near-null discrimination — checked, not assumed**
(`DECISIONS.md` D17, `figures/phase4_tornado.png`). The breakeven value
of `benefit_capture_rate` (how much of the extra reserve actually offsets
a loss) is 2.3%–5.7% across the sweep, against a config default of 100%.
The breakeven `working_capital_cost_weekly_rate` is 322%–803%
*annualised*, against a config default of ~18%. Neither is remotely
plausible — reserve is money the aggregator already withheld from the
merchant's own settlement, not a debt that needs collecting, so near-full
capture is structurally the realistic end of that parameter, not the
optimistic one. A tornado plot across generous, honestly-wide ranges
picked before seeing where breakeven fell never crosses zero.

*This sensitivity analysis (D17) was run on the pre-calibration sweep
(D16) and has not been re-run on the calibrated numbers above — flagged
here rather than left implicit (`DECISIONS.md` D26). Since calibration
made the raw economics more favourable, not less (Section 5), there is
no reason to expect the breakeven values to move in the direction that
would matter (i.e. become more plausible) — but that is a reasonable
expectation, not a checked number, and shouldn't be read as one.*

![Sensitivity tornado](figures/phase4_tornado.png)

## 5. Calibration evidence

**Calibration matters more than AUC here because the decision layer
consumes absolute probabilities, not ranks.** Section 4's false-alarm-rate
thresholds are cut directly from the model's own predicted probabilities;
a model that ranks correctly but is systematically over- or
under-confident would silently distort every threshold and every R$
figure above, in a way AUC cannot detect.

In aggregate the model is well calibrated: Brier score 0.0068, Expected
Calibration Error 0.0045 (`DECISIONS.md` D19,
`figures/phase4_reliability_diagram.png`). That aggregate number hides
where it matters. The highest-risk decile of test predictions — the one
closest to where Section 4's false-alarm thresholds actually sit — is
**over-confident by roughly 2x**: mean predicted risk 0.080 against a mean
actual event rate of 0.039.

![Reliability diagram](figures/phase4_reliability_diagram.png)

**What that miscalibration did to the economics, checked rather than
assumed:** refit an isotonic calibrator on train predictions only and
re-ran the full FAR sweep on the calibrated scores, no other parameter
touched (`DECISIONS.md` D21, `figures/phase4_calibrated_sweep.png`). The
prediction going in was that the economic margin would shrink but
survive, given how much headroom Section 4's sensitivity analysis showed.
**That prediction did not hold — the calibrated sweep beat the
uncalibrated one at every single false-alarm rate tested, with no sign
flip anywhere.**

**Pre-calibration comparison, labelled as such** — the numbers Section 4
would have shown before D21, and the only place in this document they
appear:

| FAR | net Δcost / 1,000 mw, pre-calibration | net Δcost / 1,000 mw, calibrated (Section 4) |
|---:|---:|---:|
| 1% | -R$8.12 | -R$16.50 |
| 5% | -R$74.29 | -R$98.03 |
| 10% | -R$142.25 | -R$155.33 |

The mechanism, worked out after seeing the result: the FAR sweep was
never actually probability-weighted (cost and benefit are both computed
from realised outcomes, using the score only to rank rows
against a threshold), so a monotonic recalibration should have been close
to a no-op — it wasn't exactly, because isotonic regression is a step
function and real data produces ties at its plateaus, which shifted which
rows cleared each quantile threshold in discrete jumps rather than
smoothly. **The safe conclusion is that calibration does not overturn the
economic result. The specific size of "how much better" should be read
with caution** — it depends on where quantile cutoffs happen to land
relative to those tie plateaus, a more sensitive dependency on
implementation detail than the headline number suggests. A smoother
calibrator (Platt scaling) is the natural follow-up, not attempted here.

**Precision and recall, calibrated model, held-out test window** — stated
directly, not only implied through AUC, calibration, lead time, and cost
(`src/phase4_precision_recall.py`, thresholds reused exactly from D21):

| FAR | threshold | flagged | true events caught | false positives | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|
| 1% | 0.2000 | 874 | 31 | 843 | 3.5% | 13.1% |
| 5% | 0.0545 | 2,212 | 92 | 2,120 | 4.2%¹ | 38.8% |
| 10% | 0.0404 | 4,505 | 166 | 4,339 | 3.7% | 70.0% |

¹ *Precision is non-monotonic (3.5%→4.2%→3.7%), not an error. Checked
directly: it's non-monotonic on the raw, uncalibrated scores too
(0.9%→4.1%→3.9%), so it isn't purely a calibration artefact — the
model's ranking itself isn't perfectly precision-ordered across this
range. Isotonic calibration makes it more visible: it collapses 31,442
distinct raw scores into just 50 calibrated levels (the same tie-plateau
mechanism as D21), so each threshold draws from one of a handful of
discrete blocks of rows whose composition can differ by chance rather
than shifting smoothly.*

**Precision is poor in absolute terms — 3.5–4.2%, meaning roughly one in
25 flags is a real cessation — and that is reported plainly, not dressed
up.** It reflects the test window's own base rate (237 of 34,853 rows,
0.68%): even a 4x–6x lift over flagging at random still looks low as a
raw percentage when the event itself is this rare. **This low precision
is priced explicitly in the cost model, which is why the policy still
beats the naive rule despite it (Section 4):** every flagged healthy row
is charged its real working-capital cost regardless of how rare true
positives are, and the FAR sweep still comes out ahead because each of
the few true positives is worth far more — an accelerated reserve against
an actual failure — than each false positive costs. The economics do not
depend on precision being good; they depend on the ratio in
`config/costs.yaml`, audited separately in Section 4's sensitivity
analysis. Recall climbs with FAR as expected (13%→39%→70%) — at a loose
10% false-alarm rate the model does eventually flag most true cessations
somewhere in their test-period history, which is a different and weaker
claim than flagging them *early* (Section 3's finding stands: most of
that flagging happens once the seller has already gone quiet, not before).

## 6. The ablation — the brief's core hypothesis, tested directly

The hypothesis this project set out to test: *the trend and acceleration
of merchant health metrics predict distress better than their levels.*
**Every test built in this project says no.**

Three nested feature tiers were evaluated (levels only, 12 features;
levels + trend, 28; levels + trend + acceleration, the full 37-feature
model) against the cleanest available version of the core question:
restricted to rows where the seller was *still genuinely placing orders
that exact week* (raw current-week order count, not a smoothed trailing
average — the first attempt at this check used the trailing average and
was contaminated by a multi-week "echo" of recent activity, caught and
corrected, `DECISIONS.md` D14 §3, D18), predicting whether the seller
would cease within the next 8 weeks.

| tier | features | train AUC | test AUC |
|---|---:|---:|---:|
| levels only | 12 | 0.702 | **0.682** |
| levels + trend | 28 | 0.712 | **0.678** |
| levels + trend + acceleration | 37 | 0.714 | **0.678** |

Test AUC is flat to slightly *down* as trend and acceleration are added,
while train AUC rises — added fitting capacity without added
generalising signal, the opposite of what the hypothesis predicted.

![Ablation result: levels vs. trend vs. acceleration](figures/readme_ablation.png)

This hypothesis was stated in `BRIEF.md` before any code in this
repository was written — no commit in this repository's history predates
it. (`BRIEF.md` itself is gitignored at the user's request, so it is not
part of the tracked deliverable and cannot literally appear in `git log`
— what git history does confirm is that every commit in this repository,
starting from the first, postdates the point the hypothesis was already
fixed, not the reverse.) It was tested directly, on the cleanest cut of
the data available, and rejected. A full-detail version of this figure,
including the train/test bars for the confirmation-anchored and
last-order-anchored point tests across all three tiers, is in
`figures/phase4_ablation.png`.

**This is not a "no signal exists" result.** Levels alone carry real,
moderate signal — 0.68–0.70 AUC — about whether an actively-trading
seller will cease within the next two months, which is itself a more
useful and more surprising finding than the near-null point-in-time tests
in Section 3 alone would have suggested (aggregating over an 8-week
window recovers signal that a single point-in-time snapshot doesn't show,
because week-to-week order counts here are individually noisy —
`DECISIONS.md` D18, and Phase 0's F1 on how sparse per-week order volume
is for most sellers). The finding is specifically that trend and
acceleration, layered on top of that levels signal, add nothing this
project could measure.

**Capacity check, not a model upgrade: does a nonlinear learner find what
the linear model missed on the same inputs?** One gradient-boosted model
(`HistGradientBoostingClassifier`, default hyperparameters, `random_state=0`
only — no tuning, no class weighting, matching the logistic regression's
own lack of either), same 37 features, same split, same two evaluations
(`DECISIONS.md` D24, `src/phase4_gbm_capacity_check.py`). Not promoted to
primary regardless of the result.

| evaluation | logistic | GBM |
|---|---:|---:|
| pooled active-only test AUC | 0.678 | 0.700 |
| pooled active-only train AUC (train/test gap) | 0.714 (3.6 pts) | 0.953 (**25 pts**) |
| advance-warning horizon, k=1/2/4/8 | 0.584 / 0.586 / 0.534 / 0.555 | 0.561 / 0.569 / 0.540 / 0.523 |

The pooled number looks like a 2.2-point win for the GBM — **it isn't
read as one.** A 25-point train/test gap against the logistic
regression's 3.6 means the GBM converted most of its extra capacity into
overfitting the training rows, not into generalising signal, and a
2.2-AUC-point edge measured on only 363 test-window positive rows is well
within what sampling noise on a set that size produces on its own. At the
horizons that actually matter — advance warning, still trading — the GBM
is at or below the linear model at three of four. **The GBM is slightly
better pooled and slightly worse at the advance-warning horizons, which
is the same finding restated, not a new one: it fits the quiet-detection
signal (Section 3) somewhat harder than the linear model does, and that
signal was never early warning to begin with.** Conclusion: the ceiling
here is in the data and features, not in the linearity of the model class.

Limitation stated plainly: both models ran on default hyperparameters
with no early-stopping tuning either way — the right comparison for this
specific question, but not the strongest possible test of what a
properly tuned nonlinear model could do (Section 8).

## 7. Failure slices and the fairness disparity

*This section's economics are pre-calibration (D20 predates D21) and
have not been re-run on the calibrated model used in Sections 4-5 —
found during a consistency pass, flagged rather than silently left
inconsistent (`DECISIONS.md` D26). The qualitative findings below
(tenure inertia, the two losing categories) are not expected to reverse
— D21 showed calibration makes the aggregate economics more favourable,
not less — but the exact margins in this section have not been checked
against the calibrated scores and should not be assumed to match Section
4's numbers precisely.*

Extended Section 4's economics to four slice dimensions — tenure at test
start, merchant size (weekly GMV quartile), dominant product category,
and order-volume decile, all assigned per seller — at the 5%
false-alarm rate used throughout (`DECISIONS.md` D20,
`figures/phase4_slices.png`).

Size and volume-decile: the model beats the rule in every slice, no
exceptions. Two dimensions did not clear that bar:

**Tenure — the model is inert for the largest single group of merchants
in the dataset, not harmful to them, but not useful either.** New sellers
(under 13 weeks of tenure at the start of the test window) are 1,361 of
3,065 sellers — 44% of everyone in the panel, the largest tenure band by
a wide margin. They technically lose to the rule, by R$0.01 per 1,000
merchant-weeks — three orders of magnitude smaller than every other
slice's margin, established sellers (-R$29.8) and veterans (-R$362.6)
included. Few new sellers get flagged and few of their eventual failures
get accelerated, so the honest read is that the tool has close to nothing
to say about the largest cohort of merchants on the platform, not that it
actively burdens them.

**Category — two real losing slices, not sample-size artefacts.**
Filtering to categories with at least 20 sellers (below that, a single
false alarm against zero events flips the sign trivially, which is not a
finding), 9 of 28 categories lose to the rule. The two most credible on
sample size: **`auto`** (210 sellers, the second-largest category in the
dataset, +R$1.88/1,000 merchant-weeks) and **`electronics`** (42 sellers,
+R$1.88/1,000 merchant-weeks). No mechanism investigated for *why* these
categories specifically lose — a natural next check, not done here.

![Slice economics by category](figures/phase4_slices_category_clean.png)

## 8. What I would do next with real data

In priority order, given more time and access to real payments data
rather than Olist's e-commerce proxy:

- **Replace the cessation label with an actual default/write-off event.**
  Section 2's biggest open question — 86% of "distress events" here show
  no quality-collapse signature, and are plausibly benign exits, not
  merchant default. A real payments dataset would have chargebacks,
  refund floods, and write-offs directly.
- **Run the N=4/8/12 robustness sweep across every Phase 3/4 result.**
  Deliberately skipped this round (explicit scope decision, not an
  oversight) — every headline number here uses the primary N=8 cessation
  definition only. Phase 0/1 already carried N=4/12 as parallel label
  definitions for exactly this purpose; the machinery exists, the sweep
  across Phase 3's economics and Phase 4's diagnostics was not run.
- **Build the four-baseline comparison** (flat reserve, category-based,
  tenure-based reserve, and a binary classifier with no survival
  treatment) that Section 4 explicitly did not build. The N=8-rule
  comparison used throughout this document is a real and relevant
  baseline, but not the full set the brief specified, and baseline 4 in
  particular (does survival treatment beat plain classification at all)
  is still an open question here.
- **Try a smoother probability calibrator** (Platt scaling) as a
  follow-up to Section 5's isotonic check, whose step-function shape
  makes the exact magnitude of the calibrated economic result more
  sensitive to implementation detail than is comfortable.
- **Run a properly tuned gradient-boosted comparison** — Section 6's GBM
  capacity check deliberately used default hyperparameters with no
  cross-validation or early-stopping tuning on either model, the right
  comparison for "does an untuned nonlinear learner find missed signal,"
  but not the strongest possible test of what a well-tuned nonlinear
  model could do on these features. Logistic regression stays primary
  either way, per this project's scope.
- **Investigate why `auto` and `electronics` lose economically** (Section
  7) — category-specific order cadence, AOV structure, or delivery
  patterns are the natural first hypotheses, untested here.
- **Get real financing-cost and reserve-program data** to replace
  `config/costs.yaml`'s three assumed parameters with measured ones —
  Section 4's sensitivity analysis says the conclusion has a lot of room
  to be wrong on these and still hold, but "a lot of room" is not the
  same as "measured."
- **A reserve ceiling for small/new merchants**, sized against the
  tenure-band finding in Section 7 — the brief's original fairness ask,
  not built this round since it wasn't in this phase's scope, and now
  informed by evidence (the model has near-zero net effect on this group
  either way) rather than the assumption that motivated asking for it.

## Interactive demo

`app.py` is a Streamlit demonstration of the decision this project
evaluated — select a test-set merchant, see its calibrated hazard, what
changed since last week and which features moved it, the recommended
reserve action at a chosen false-alarm rate, and the estimated cost
trade-off. It is a presentation of the results already reported above,
not a new analysis and not a production system: the two required
honesty checks (this section's own opening two paragraphs) are the same
ones from Sections 3 and 5 — the minority-benefit acceleration result and
the top-decile calibration caveat — surfaced as banners that don't
collapse or hide.

**Run it:**

```bash
pip install -r requirements.txt
python src/prepare_demo_data.py   # one-time: materialises figures/demo_*.csv
                                   # from the already-fitted model + calibrator (D21) --
                                   # reuses existing functions, no new modeling
streamlit run app.py
```

`app.py` itself reads only pre-computed files (`figures/demo_*.csv`,
`figures/phase3_far_sweep.csv`, `figures/phase4_calibrated_sweep.csv`,
`figures/phase4_precision_recall.csv`, `config/costs.yaml`) — it does not
fit, score, or sweep anything at runtime. `src/prepare_demo_data.py` is
deliberately **not** part of `run.sh`: `run.sh` is the reproducibility
path for every number in this document, and stays that way; the demo is
a separate, optional artefact with its own one-time setup step.
