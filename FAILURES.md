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

### F3 — Trimming to STUDY_END fixed the volume-truncation artefact but not a subtler edge artefact

**Assumption going in:** trimming the panel to `STUDY_END = 2018-08-26`
(D1) — chosen because that's where weekly order volume collapses — would
be enough to stop the dataset's truncation from being mistaken for
merchant cessation.

**What actually happened:** it fixed the obvious problem (a seller active
right up to the true data cutoff no longer looks like it "vanished") but
not a subtler one. Under pure cessation, an event is only confirmed once
`STUDY_END - last_active_week >= N` weeks — sellers whose last order lands
close to `STUDY_END - N` get confirmed with almost no margin, right at the
edge of what the window can support. Checked directly
(`src/phase0_calendar_hazard.py`): 22–35% of all confirmed events
(depending on N) are confirmed in just the final N weeks before
`STUDY_END`, a span that's only 5–14% of the 86-week window. The weekly
hazard-rate plot (`figures/phase0_calendar_hazard.png`) shows a visible
spike in the last few weeks for every N tested, on top of a slower,
separate upward drift across the whole window that looks more like a
duration-dependence/composition effect (more of the risk set has aged into
higher-hazard tenure later in the study, since the seller population grew
over time) than a real change in platform-wide distress.

I looked for an external explanation (the well-known May 2018 Brazilian
truckers' strike, which disrupted deliveries nationally) before assuming
this was purely an artefact — checked monthly late-delivery rate directly.
It does **not** hold up: May 2018's late rate (8.6%) is unremarkable; the
actual peak is March 2018 (23.4%), which doesn't line up with the
cessation-onset over-indexing (which peaks Apr–Jun 2018). No supported
real-world story here — treating this as a boundary-confirmation artefact
until shown otherwise.

**Resolution:** not resolved — flagged in `DECISIONS.md` D6 as an open
question, since fixing it changes either the label (shrinking the usable
event count further) or the evaluation design (Phase 2's test window is
exactly where this concentrates), and that's a modelling decision, not an
implementation one.

### F4 — Sibling-module imports break depending on invocation directory

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
