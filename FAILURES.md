# Failures

Dead ends, wrong assumptions, and things that broke, kept as-is — not
cleaned up for the write-up.

## Phase 0

### F1 — Cancellation rate is nearly always zero at seller-week grain; not usable alone as an "elevated" signal

**Assumption going in:** cancellation rate would be a reasonably common,
useful signal for the "preceded by elevated cancellation" half of the
brief's suggested distress definition, alongside late-delivery rate.

**What actually happened:** order-level cancellation rate over the whole
study window is 0.45%. Looking at the trailing 4-week pooled cancellation
rate across every active-seller-week (66,276 seller-weeks with at least one
order in the trailing window): the median is 0, the 75th percentile is 0,
the 90th percentile is 0, and the 95th percentile is *still* 0. Only the
99th percentile (0.5) and above show any signal at all — 97.6% of
active-seller-weeks have a trailing cancellation rate of exactly zero.

Late-delivery rate is far more usable by comparison: 22.6% of
active-seller-weeks have a nonzero trailing late rate, with a 90th
percentile of 0.25 and a 95th percentile of 0.50.

**Resolution:** kept cancellation in the "elevated" OR-condition for
completeness (a seller with real cancellation activity should still count),
but set its threshold high (0.10, near the 99th percentile) since anything
looser is indistinguishable from noise, and treated late-delivery rate as
the load-bearing half of the quality signal. This is a data characteristic
of Olist specifically — Brazilian marketplace cancellations are rare and
may be recorded differently than refunds/chargebacks would be in a payments
context — and is exactly the kind of dataset-vs-target mismatch the README
limitations section needs to state plainly.

### F2 — The brief's literal suggested definition (Candidate A) undershoots the kill criterion on its own

**Assumption going in:** "sustained cessation preceded by elevated
cancellation/late-delivery" (the brief's starting suggestion, Candidate A)
would be the primary definition, with B and C mainly there for comparison.

**What actually happened:** at every N tested (4, 8, 12 weeks of silence),
Candidate A produces 71–91 events among 1,919 eligible sellers — below the
brief's ~150-event kill floor. The unfiltered cessation definition
(Candidate B, same N, no quality precondition) produces 550–858 events at
the same settings. The gap is the "preceded by elevated quality" clause
doing exactly what it was designed to do — filtering distress-flavoured
exits from benign ones — but filtering far more aggressively than expected:
roughly 85–90% of qualifying cessations get cut.

**Why:** most cessations in this dataset look like ordinary attrition — a
seller stops listing with no visible delivery/cancellation problem
beforehand — rather than a visible quality collapse before going dark. That
may be a real feature of this marketplace (sellers who fail badly enough to
flood cancellations/refunds may behave differently from sellers who simply
stop), or it may mean the quality precondition as specified is too strict
for the amount of order volume most sellers carry (see F1 — cancellation
in particular contributes almost nothing).

**Resolution:** not resolved unilaterally — this is exactly the kind of
result the brief says should be reported honestly and escalated, not
patched around. See `PHASE0_FINDINGS.md` for the full comparison and the
decision this leaves for you.

### F3 — Sibling-module imports break depending on invocation directory

**What happened:** `src/panel.py`, `src/distress_events.py`, and
`src/phase0_report.py` import each other as plain sibling modules
(`from panel import ...`). Running `python3 src/distress_events.py` from
the repo root fails with `ModuleNotFoundError: No module named 'panel'`
because `src/` isn't on `sys.path` in that invocation form.

**Resolution:** run with `PYTHONPATH=src python3 src/<script>.py` from the
repo root — that's the form used in this report and will be the form baked
into `run.sh` once it exists. Flagging rather than quietly fixing with a
sys.path hack, since the cleaner long-term fix (turn `src` into a proper
package, use `python -m src.<script>`) is a Phase 1 packaging decision, not
a Phase 0 one.
