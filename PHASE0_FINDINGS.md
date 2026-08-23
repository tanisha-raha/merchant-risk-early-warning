# Phase 0 — data viability finding

Reproduce with:
```
PYTHONPATH=src python3 src/panel.py
PYTHONPATH=src python3 src/distress_events.py
PYTHONPATH=src python3 src/phase0_report.py
PYTHONPATH=src python3 src/phase0_calendar_hazard.py
PYTHONPATH=src python3 src/phase0_benign_exit.py
```

**Status (2026-08-23): approved, with a change and two follow-ups.**
Event definition is pure cessation (Candidate B), N=8 as primary with N=4
and N=12 carried through to Phase 4 as a robustness check (DECISIONS.md
D5). Eligibility floor kept as-is, now with its GMV impact quantified
(D3). Two follow-up analyses below: a right-edge/censoring-boundary check,
and a benign-exit quantification for the README limitations section.

## Panel

3,065 sellers, 133,734 seller-weeks, study window 2017-01-01 to 2018-08-26
(86 weeks). 1,919 sellers (62.6%) clear the eligibility floor (≥4 orders,
≥3 distinct active weeks) needed for a cessation-style event to mean
anything — see `DECISIONS.md` D3.

Calendar coverage, with the excluded soft-launch and truncation periods
shaded: `figures/phase0_calendar_coverage.png`. Both artefacts are real and
material — trimming to the study window is not optional (D1).

## Candidate distress definitions, all eligible sellers (n=1,919)

| Definition | Events | Event rate | Censoring rate | Obs. length (weeks) p25 / median / p75 |
|---|---:|---:|---:|---|
| **A** — cessation(N=4) + elevated quality | 91 | 4.7% | 95.3% | 18 / 36 / 57 |
| **A** — cessation(N=8) + elevated quality | 78 | 4.1% | 95.9% | 20 / 38 / 58 |
| **A** — cessation(N=12) + elevated quality | 71 | 3.7% | 96.3% | 21.5 / 39 / 59 |
| **B** — cessation(N=4), no quality filter | 858 | 44.7% | 55.3% | 18 / 36 / 57 |
| **B** — cessation(N=8), no quality filter | 665 | 34.7% | 65.4% | 20 / 38 / 58 |
| **B** — cessation(N=12), no quality filter | 550 | 28.7% | 71.3% | 21.5 / 39 / 59 |
| **C** — quality collapse(M=2), no cessation required | 559 | 29.1% | 70.9% | 15 / 34 / 58 |
| **C** — quality collapse(M=3), no cessation required | 439 | 22.9% | 77.1% | 17 / 38 / 62.5 |

(N = weeks of silence required to call cessation terminal; M = consecutive
weeks of elevated trailing cancel/late rate required for Candidate C.
Definitions and thresholds in `src/distress_events.py`, rationale in
`DECISIONS.md` D3–D4.)

Bar chart and observation-length histogram: `figures/phase0_definition_comparison.png`.

## Kill-criteria check

**Candidate A, exactly as you specified it in the brief, fails the ~150-event
floor at every N tested (71–91 events).** Candidates B and C both clear it
comfortably (439–858 events). This is not a "the dataset is unusable"
verdict — B and C both give more than enough events for the discrete-time
hazard model in Phase 2 — but it does mean the literal starting suggestion
needs a decision from you before Phase 1 starts.

## Why A comes up short, and a problem beyond event count

Two things happened, both reported in full in `FAILURES.md`:

1. **Cancellation rate is nearly always zero at seller-week grain** (F1).
   97.6% of active-seller-weeks have a trailing 4-week cancellation rate of
   exactly 0 — the 95th percentile is still 0. Late-delivery rate carries
   almost all of the "elevated quality" signal in Candidate A; cancellation
   contributes little beyond noise at the threshold needed to mean anything.
2. **Most cessations in this data look like ordinary attrition, not visible
   quality collapse beforehand.** Roughly 85–90% of sellers who qualify as
   "cessation" under B do *not* show elevated late/cancel rates before they
   stop (F2). Either that's a real feature of this marketplace, or the
   quality precondition is calibrated too strictly for the order volume
   most sellers carry — Phase 0 can't distinguish those two explanations
   with this data.

There's also a methodological problem with A (and more acutely with C) that
isn't about event count: **using trailing cancellation/late-rate as part of
the event *label* and then also as a *predictive feature* in Phase 1/2 is
circular.** A model would partly be predicting a quantity that's already
baked into its own target, inflating apparent skill in a way that won't
generalize. Candidate C is the worst offender here — its label *is* the
elevated-quality condition directly, with no cessation requirement at all.
Candidate B has no such issue: cessation is an independent, objectively
observed outcome, and cancellation/late-rate (levels, trend, acceleration)
remain honest predictors of it.

## Recommendation (yours to confirm, not mine to impose)

Adopt **Candidate B — pure cessation, no quality precondition in the
label** — as the Phase 1 distress event, with N=8 weeks (roughly the 95th
percentile of natural gaps between a still-active seller's order weeks, so
an 8-week silence is genuinely unusual rather than an ordinary lull; see
gap-distribution numbers in `DECISIONS.md` if you want them added there).
That gives 665 events against 1,919 eligible sellers, 65.4% censoring,
median observation length 38 weeks. Cancellation rate, late-delivery rate,
and their trends/accelerations become predictive features — which is also
what lets you actually test the brief's core hypothesis (trend/acceleration
beats levels) without the label already containing the answer.

This is a real change from your starting suggestion, not a minor parameter
tweak. **Approved 2026-08-23:** Candidate B, pure cessation, N=8 primary
with N=4/N=12 carried through as a robustness check on the headline result
(DECISIONS.md D5). Eligibility floor kept at ≥4 orders / ≥3 active weeks
(D3) — excludes 1,146 of 3,065 sellers (37.4%) but only 3.2% of in-window
GMV, so the floor removes mostly long-tail noise, not real exposure.

## Right-edge check: does the truncation artefact really stop at STUDY_END?

Short answer: **no, not fully.** `src/phase0_calendar_hazard.py`,
`FAILURES.md` F3, `DECISIONS.md` D6.

For each N, share of confirmed events whose confirmation date falls in the
**final N weeks before STUDY_END** (a window that's only 5–14% of the full
86-week study):

| N | Total events | Events in final N weeks | Share |
|---|---:|---:|---:|
| 4 | 858 | 193 | 22.5% |
| 8 | 665 | 188 | 28.3% |
| 12 | 550 | 193 | 35.1% |

All three are hugely over-represented relative to how much calendar time
that window actually covers. `figures/phase0_calendar_hazard.png` shows why:
the weekly hazard rate visibly spikes in the last few weeks before
`STUDY_END` for every N, on top of a slower upward drift across the whole
window that looks like duration dependence (the risk set skews toward
longer-tenured sellers later in the study, since the seller population grew
over 2017–2018) rather than a real change in platform-wide distress.

I checked for a real external cause before calling this an artefact — the
May 2018 Brazilian truckers' strike is a well-known disruption to this
dataset's delivery times. It doesn't hold up: May 2018's late-delivery rate
(8.6%) is unremarkable; the actual peak is March 2018 (23.4%), which
doesn't line up with the Apr–Jun 2018 window where cessation onsets
over-index. No supported story — this reads as a boundary-confirmation
artefact: events near the edge are confirmed with the thinnest possible
margin (silence_weeks_observed exactly at or just past N), and that margin
is not evenly distributed across the window.

**Why this matters for Phase 2:** the brief requires a time-based
train/later-window-test split. The later window is exactly where this
artefact concentrates, so without a mitigation, the test set's event labels
are disproportionately drawn from the least trustworthy confirmations —
this could bias lead-time and calibration results right where they're
reported as the headline.

**Open question, not resolved unilaterally** (see below).

## Limitation: pure cessation labels benign exits as distress

Quantified in `src/phase0_benign_exit.py`, for Candidate B N=8 (665 events):

1. **Only 11.7% of cessation events (78/665) show elevated cancel/late rate
   before exiting** (Candidate A's proxy). 88.3% show no such signal — this
   was already known from F2, restated here as the headline limitation
   number for the README.
2. **Trailing review score before exit is lower than baseline, but not
   dramatically:** mean 3.84 vs. a baseline mean of 4.08 across all active
   seller-weeks (median 4.25 vs. 4.33). A real, independent (not
   label-derived) signal that departing sellers skew toward worse recent
   customer satisfaction — but a 0.24-point gap on a 1–5 scale is modest,
   not a clean split between "distressed" and "benign" sellers.
3. **Seasonality is confounded with the right-edge artefact, not clean
   evidence on its own.** Cessation onsets over-index most in Apr–Jun 2018
   (up to 2.6× their share of order volume) — but that's exactly the window
   close enough to `STUDY_END` to be N=8-confirmable at all, so this number
   can't be cleanly separated from the right-edge finding above. December
   2017 (the actual holiday peak) shows no elevation (ratio ≈ 1.0), which
   weighs against a simple "one-shot seasonal seller" story.
4. **Ceasing sellers are smaller than surviving ones:** median 10 total
   orders / 8 active weeks vs. 20 orders / 13 active weeks for censored
   (still-active) sellers. Consistent with either "smaller sellers churn
   more benignly" or "smaller sellers are more fragile" — this data can't
   distinguish the two, but it does mean the distress label leans toward
   the same small/low-volume population the brief's Phase 4 fairness note
   is worried about over-reserving.

**Net:** pure cessation is a defensible, non-circular, kill-criteria-clearing
label, but it is a proxy that includes a real population of benign exits —
plausibly on the order of 80–90% by the (admittedly weak) quality-proxy
measure, tempered by a real but modest review-score gap suggesting the
population isn't purely random churn either. This goes in the README
limitations section verbatim: *the distress event is a proxy for merchant
default, not default itself, and a majority of labelled events likely
include sellers who left for reasons unrelated to financial distress.*
