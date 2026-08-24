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

**Resolution:** resolved 2026-08-23 — `DECISIONS.md` D6. Events confirmed
within the final N weeks before `STUDY_END` are now treated as censored,
not events (equivalent to requiring `silence_weeks_observed >= 2*N`).
Event counts dropped from 858/665/550 to 665/477/357 for N=4/8/12; all
still clear the kill floor. A calendar-time model covariate was considered
as an alternative and rejected — see D6 for why. A follow-up check
(`DECISIONS.md` D7) confirmed a 26-week Phase 2 test window is needed for
the strictest variant (N=12) to retain a usable number of test-set events
(151) after this fix.

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

**Partial fix, Phase 1:** added `tests/conftest.py` (puts `src/` on
`sys.path` once, for the whole test session) so `pytest` now works from the
repo root with no `PYTHONPATH` needed. Running a script directly (e.g.
`python3 src/features.py`) still needs `PYTHONPATH=src` — that's what
`run.sh` will use. The `python -m src.<script>` packaging cleanup is still
not done; still a nice-to-have, not a blocker.

## Phase 1

### F5 — Test's own cutoff timestamp clipped same-day orders (test bug, not a features.py bug)

**What happened:** `tests/test_no_lookahead.py`'s first draft set
`CUTOFF = pd.Timestamp("2018-03-04")`, which defaults to midnight. The
"hide the future" test compares feature values for weeks ≤ cutoff between
a full run and a run with raw data truncated at cutoff — but 236 orders
purchased later on 2018-03-04 itself (after 00:00:00) got wrongly excluded
from the truncated run's raw data, even though they belong to the same
`W-SUN` week as orders purchased earlier that day. This showed up as 8
feature columns (`order_volume_*`, `aov_*`, both concentration levels)
"changing when the future was hidden" for that boundary week — which
looked exactly like a leakage bug at first.

**Resolution:** confirmed it was the test, not the code, by checking the
raw data directly (236 same-day orders after midnight) before touching
features.py. Fixed by setting `CUTOFF` to the end of that week
(`23:59:59.999999`), not its start. Recorded here because "the test itself
had a bug" is exactly the kind of thing that's tempting to fix silently and
move on — worth showing that the first failure wasn't real leakage before
the second one (F6) turned out to be.

### F6 — Review data-quality bug the leakage test caught for real

See `DECISIONS.md` D9. After fixing F5, one genuine mismatch remained:
`review_score_level` for one seller-week differed between the full and
future-hidden runs. Traced to a raw data artefact — 74 of 99,224 review
rows are dated before their own order's purchase timestamp (a review
literally predating the purchase it's reviewing), almost certainly a
reused `order_id` in the reviews table. One such row attached a January
2018 review date to an order actually purchased in April 2018; hiding
April's data correctly made the review disappear from the truncated run,
while the full run — unaware anything was wrong — kept counting it against
January. Fixed by dropping any review row where
`review_creation_date < order_purchase_timestamp` in
`build_review_weekly`. This is the test doing exactly its job: catching a
real, if narrow (0.075% of rows), source of leakage-shaped distortion
before it reached a model.
