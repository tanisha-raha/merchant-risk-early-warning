# Phase 0 — data viability finding

Reproduce with:
```
PYTHONPATH=src python3 src/panel.py
PYTHONPATH=src python3 src/distress_events.py
PYTHONPATH=src python3 src/phase0_report.py
```

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
tweak, so I'm stopping here rather than picking it for you. Three decisions
outstanding before Phase 1:

1. **Event definition:** B (recommended), A as specified (accepting <150
   events and the circularity caveat), a loosened variant of A (e.g. lower
   the late-rate threshold, or use relative/trend-based "elevated" instead
   of an absolute cutoff), or something else.
2. **N** (silence weeks): 8 is my suggested default; 4 is more sensitive but
   closer to normal seller cadence gaps; 12 is stricter and loses ~115
   events versus N=8.
3. **Eligibility floor** (D3: ≥4 orders, ≥3 active weeks) — reasonable
   defaults, not derived from anything, open to a different cutoff.
