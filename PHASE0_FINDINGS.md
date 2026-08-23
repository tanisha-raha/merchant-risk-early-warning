# Phase 0 — data viability finding

Reproduce with:
```
PYTHONPATH=src python3 src/panel.py
PYTHONPATH=src python3 src/distress_events.py
PYTHONPATH=src python3 src/phase0_report.py
PYTHONPATH=src python3 src/phase0_calendar_hazard.py
PYTHONPATH=src python3 src/phase0_benign_exit.py
```

**Status (2026-08-23): resolved.** Event definition is pure cessation
(Candidate B), N=8 primary with N=4/N=12 carried through to Phase 4 as a
robustness check (D5). Eligibility floor kept as-is, GMV impact quantified
(D3). The right-edge check found a real boundary-confirmation artefact;
events in the affected zone are now excluded from the label (D6), and a
provisional Phase 2 test-window width was checked against the post-
exclusion event counts (D7). All numbers below are **post-exclusion, final
for Phase 0.**

## Panel

3,065 sellers, 133,734 seller-weeks, study window 2017-01-01 to 2018-08-26
(86 weeks). 1,919 sellers (62.6%) clear the eligibility floor (≥4 orders,
≥3 distinct active weeks) needed for a cessation-style event to mean
anything — see `DECISIONS.md` D3.

Calendar coverage, with the excluded soft-launch and truncation periods
shaded: `figures/phase0_calendar_coverage.png`. Both artefacts are real and
material — trimming to the study window is not optional (D1).

## Candidate distress definitions, all eligible sellers (n=1,919)

Post edge-exclusion (D6) for A and B; C is unaffected (it doesn't require
confirming a future absence of orders, so it has no right-edge margin
problem).

| Definition | Events | Event rate | Censoring rate | Obs. length (weeks) p25 / median / p75 |
|---|---:|---:|---:|---|
| **A** — cessation(N=4) + elevated quality | 78 | 4.1% | 95.9% | 18 / 36 / 57 |
| **A** — cessation(N=8) + elevated quality | 66 | 3.4% | 96.6% | 20 / 38 / 59 |
| **A** — cessation(N=12) + elevated quality | 50 | 2.6% | 97.4% | 22 / 40 / 60 |
| **B** — cessation(N=4), no quality filter | 665 | 34.7% | 65.4% | 18 / 36 / 57 |
| **B** — cessation(N=8), no quality filter | 477 | 24.9% | 75.1% | 20 / 38 / 59 |
| **B** — cessation(N=12), no quality filter | 357 | 18.6% | 81.4% | 22 / 40 / 60 |
| **C** — quality collapse(M=2), no cessation required | 559 | 29.1% | 70.9% | 15 / 34 / 58 |
| **C** — quality collapse(M=3), no cessation required | 439 | 22.9% | 77.1% | 17 / 38 / 62.5 |

(N = weeks of silence required to call cessation terminal; M = consecutive
weeks of elevated trailing cancel/late rate required for Candidate C.
Definitions and thresholds in `src/distress_events.py`, rationale in
`DECISIONS.md` D3–D4, D6.)

Bar chart and observation-length histogram: `figures/phase0_definition_comparison.png`.

## Kill-criteria check

**Candidate A, exactly as you specified it in the brief, fails the ~150-event
floor at every N tested (50–78 events, post-exclusion).** Candidates B and
C both clear it comfortably (357–665 events). This is not a "the dataset is
unusable" verdict — B and C both give more than enough events for the
discrete-time hazard model in Phase 2 — but it does mean the literal
starting suggestion needs a decision from you before Phase 1 starts.

## Why A comes up short, and a problem beyond event count

Two things happened, both reported in full in `FAILURES.md`:

1. **Cancellation rate is nearly always zero at seller-week grain** (F1).
   97.6% of active-seller-weeks have a trailing 4-week cancellation rate of
   exactly 0 — the 95th percentile is still 0. Late-delivery rate carries
   almost all of the "elevated quality" signal in Candidate A; cancellation
   contributes little beyond noise at the threshold needed to mean anything.
2. **Most cessations in this data look like ordinary attrition, not visible
   quality collapse beforehand.** Roughly 86% of sellers who qualify as
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

## Decision: Candidate B, pure cessation, N=8 primary (approved 2026-08-23)

Adopted **Candidate B — pure cessation, no quality precondition in the
label** as the Phase 1 distress event, N=8 primary with N=4/N=12 carried
through Phase 1–4 as a robustness check (DECISIONS.md D5). Cancellation
rate, late-delivery rate, and their trends/accelerations become predictive
features instead of label ingredients — which is also what lets Phase 1–2
actually test the brief's core hypothesis (trend/acceleration beats levels)
without the label already containing the answer.

Eligibility floor kept at ≥4 orders / ≥3 active weeks (D3) — excludes
1,146 of 3,065 sellers (37.4%) but only 3.2% of in-window GMV, so the floor
removes mostly long-tail noise, not real exposure.

Final, post-edge-exclusion numbers for the primary definition (N=8): **477
events** against 1,919 eligible sellers, 75.1% censoring, median
observation length 38 weeks.

## Right-edge check: does the truncation artefact really stop at STUDY_END?

Short answer: **no, not fully — found, and fixed by excluding the affected
events from the label.** `src/phase0_calendar_hazard.py`, `FAILURES.md`
F3, `DECISIONS.md` D6.

Before the fix: for each N, share of confirmed events whose confirmation
date fell in the **final N weeks before STUDY_END** (a window that's only
5–14% of the full 86-week study):

| N | Total events (pre-fix) | Events in final N weeks | Share |
|---|---:|---:|---:|
| 4 | 858 | 193 | 22.5% |
| 8 | 665 | 188 | 28.3% |
| 12 | 550 | 193 | 35.1% |

All three were hugely over-represented relative to how much calendar time
that window actually covers, and the weekly hazard rate visibly spiked in
the last few weeks before `STUDY_END` for every N. I checked for a real
external cause before calling it an artefact — the well-known May 2018
Brazilian truckers' strike didn't hold up (May 2018's late-delivery rate,
8.6%, is unremarkable; the actual peak is March 2018 at 23.4%, which
doesn't line up with the affected window). Treated as a boundary-
confirmation artefact: events near the edge were confirmed with the
thinnest possible margin, and that margin is not evenly distributed across
the window.

**Fix (D6):** any event whose confirmation date falls in the final N weeks
before `STUDY_END` is now treated as censored at `STUDY_END` instead of an
event — equivalent to requiring `silence_weeks_observed >= 2*N`. Event
counts dropped accordingly (858→665, 665→477, 550→357 for N=4/8/12); all
three remain comfortably above the 150-event floor.
`figures/phase0_calendar_hazard.png` now shows the hazard rate dropping
cleanly to zero at the new boundary rather than spiking — confirmed
directly, 0% of events now fall in the excluded zone.

A calendar-time covariate (control for the effect in the model instead of
removing it from the label) was considered and **rejected**: the test
window is exactly where this artefact concentrates, so a model that can see
calendar time could learn "close to the data cutoff" as a predictive
signal and inflate apparent test-set performance without learning anything
about real distress — an artefact of *this specific dataset's collection
cutoff*, not something a production model would ever see. Full reasoning
in `DECISIONS.md` D6; **this belongs in the README methodology section**,
not just here.

## Provisional Phase 2 test-window width

Checked post-exclusion event counts against four candidate test-window
widths (`src/phase0_calendar_hazard.py`, `figures/phase0_test_window_check.csv`),
because a test window with too few events would make Phase 2's evaluation
too noisy to trust regardless of how good the model is:

| Test width | Test start | N=4 events | N=8 events | N=12 events |
|---|---|---:|---:|---:|
| 13 weeks (~3 mo) | 2018-05-27 | 207 | 88 | **13** |
| 17 weeks (~4 mo) | 2018-04-29 | 276 | 133 | 63 |
| 20 weeks (~4.6 mo) | 2018-04-08 | 308 | 173 | 104 |
| 26 weeks (~6 mo) | 2018-02-25 | 390 | 237 | **151** |

The binding constraint is N=12 (the strictest robustness variant): a
13-week test window leaves it with only 13 events — useless for concluding
anything, and the whole point of carrying N=12 forward is to check whether
the headline result depends on N, which 13 events can't support. **A
26-week (~6 month) test window is the earliest candidate where all three N
variants clear a usable floor** (151/237/390 events for N=12/8/4). Note
151 is not generous headroom for N=12 — comparable in order of magnitude to
the original ~150-event viability floor — so Phase 4 should treat N=12's
test-window results as the least statistically stable of the three when
comparing across N.

**This is a provisional check, not a committed split** — it only looks at
raw event counts by confirmation date against a naive calendar cutpoint.
Phase 2 still owns: how seller-weeks straddling the boundary get assigned,
reporting base-rate drift between train/test (required by the brief), and
confirming 26 weeks still holds once Phase 1 features exist.

## Limitation: pure cessation labels benign exits as distress

Quantified in `src/phase0_benign_exit.py`, for Candidate B N=8, final
477 events:

1. **Only 13.8% of cessation events (66/477) show elevated cancel/late rate
   before exiting** (Candidate A's proxy). 86.2% show no such signal — this
   was already known from F2, restated here as the headline limitation
   number for the README.
2. **Trailing review score before exit is lower than baseline, and the gap
   widened after the edge-exclusion fix:** mean 3.76 vs. a baseline mean of
   4.08 across all active seller-weeks (median 4.00 vs. 4.33). A real,
   independent (not label-derived) signal that departing sellers skew
   toward worse recent customer satisfaction — a 0.32-point gap on a 1–5
   scale, more than the pre-fix estimate (0.24), suggesting the events
   removed by the edge exclusion were disproportionately the more
   "benign-looking" ones (higher review scores).
3. **Seasonality is genuine, not purely a right-edge echo, though not
   fully explained.** Post-fix, cessation onsets over-index most in
   2018-04 (2.1×), 2018-02 (1.8×), and 2017-05 (1.6×) relative to their
   share of order volume — spread across the window, not just clustered
   near the old boundary. December 2017 (the holiday peak) now shows real
   elevation too (1.4×), which is different from the pre-fix read and
   mildly consistent with a seasonal-exit pattern, though not conclusive on
   this data alone.
4. **Ceasing sellers are smaller than surviving ones:** median 9 total
   orders / 7 active weeks vs. 19 orders / 13 active weeks for censored
   (still-active) sellers. Consistent with either "smaller sellers churn
   more benignly" or "smaller sellers are more fragile" — this data can't
   distinguish the two, but it does mean the distress label leans toward
   the same small/low-volume population the brief's Phase 4 fairness note
   is worried about over-reserving.

**Net:** pure cessation is a defensible, non-circular, kill-criteria-clearing
label, but it is a proxy that includes a real population of benign exits —
plausibly on the order of 85% by the (admittedly weak) quality-proxy
measure, tempered by a real, modest review-score gap and a spread-out (not
purely edge-driven) seasonality pattern suggesting the population isn't
purely random churn either. This goes in the README limitations section
verbatim: *the distress event is a proxy for merchant default, not default
itself, and a large majority of labelled events likely include sellers who
left for reasons unrelated to financial distress.*
