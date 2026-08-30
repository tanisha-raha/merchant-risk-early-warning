"""Reserve decision engine -- interactive demo.

Reads only pre-computed artefacts (figures/demo_*.csv, figures/phase3_*.csv,
figures/phase4_*.csv, config/costs.yaml). Fits, scores, and sweeps nothing
at runtime -- run `python src/prepare_demo_data.py` once beforehand (see
README.md "Interactive demo") to (re)generate those artefacts from the
already-established primary model, isotonic calibrator, and cost model.

This is a demonstration of an evaluated research result on a historical
test set, not a production system, and the result it demonstrates is
measured and modest, not a product pitch -- see DECISIONS.md D13/D14/D16/
D19/D21 for the full evidence behind every number surfaced here.

Visual design (DECISIONS.md D32): one considered palette (`.streamlit/
config.toml` + the CSS block in `main()`), applied consistently. The one
sanctioned exception to "one accent" is the feature-contribution chart,
where a second colour encodes a genuinely signed quantity. No gauges, no
0-100 risk scores, no red/amber/green threat levels, no alert icons --
a hazard estimate does not have a "danger level," and nothing here should
imply more confidence or precision than 0.68 AUC and a minority-benefit
result support.
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yaml

FIG_DIR = Path("figures")

# The only false-alarm rates the demo's pre-computed artefacts cover --
# figures/demo_event_acceleration.csv and phase4_precision_recall.csv are
# only built at these three established operating points (see
# src/prepare_demo_data.py FAR_POINTS). phase4_calibrated_sweep.csv has ten
# (1-10%), which is where a prior version of this app pulled the FAR
# selector's options from -- picking any of the other seven crashed with a
# ZeroDivisionError, since there were zero rows to compute a percentage
# over. Restricting the selector to what the acceleration data actually
# covers fixes that at the source rather than papering over it per FAR.
DEFAULT_FAR = 0.05

# One considered palette, matching .streamlit/config.toml, defined once
# and reused for both the CSS block and the Altair charts so the two
# can't drift apart. ACCENT is the one colour used throughout the page;
# ACCENT_WARM is the single sanctioned exception -- signed feature
# contributions genuinely have a direction, so that chart alone earns a
# second colour (DECISIONS.md D32).
ACCENT = "#2F6F8F"
ACCENT_WARM = "#B5602E"
INK = "#1C1F24"
INK_MUTED = "#646B78"
CARD = "#FFFFFF"
BORDER = "#E1DFD8"

FAMILY_LABELS = {
    "cancel_rate": "Cancellation rate",
    "ship_latency": "Ship latency (purchase→carrier)",
    "deliver_latency": "Delivery latency (carrier→customer)",
    "late_share": "Late-delivery share",
    "order_volume": "Order volume",
    "aov": "Average order value",
    "first_time_buyer_share": "First-time-buyer share",
    "review_score": "Review score",
    "top_sku_revenue_share": "Top-SKU revenue concentration",
    "top_buyer_revenue_share": "Top-buyer revenue concentration",
}
SUFFIX_LABELS = {"level": "level", "trend": "trend", "accel": "acceleration"}

CUSTOM_CSS = f"""
<style>
/* ---- one clean block, one palette, applied throughout ---- */

/* Section headings get real breathing room -- generous whitespace does
   the work of separating sections, not extra divider lines. */
[data-testid="stHeading"] h2 {{ margin-top: 2.5rem; }}
[data-testid="stHeading"] h3 {{ margin-top: 0.25rem; margin-bottom: 0.5rem; }}

/* Metric labels: small, tracked, muted caps -- so the VALUE is the
   focal point and the label reads as context, not competing text. */
[data-testid="stMetricLabel"] p {{
    text-transform: uppercase;
    letter-spacing: 0.045em;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    color: {INK_MUTED} !important;
}}
[data-testid="stMetricValue"] {{ color: {INK}; }}

/* Named cards (st.container(key=...)): generous padding, a subtle
   shadow so they visibly lift off the page background, and consistent
   gap below each one -- the vertical rhythm between sections. */
.st-key-snapshot-card, .st-key-policy-card, .st-key-changed-card,
.st-key-outcome-card, .st-key-costs-card {{
    margin-bottom: 2rem;
    padding: 0.5rem 0.25rem;
    box-shadow: 0 1px 4px rgba(28, 31, 36, 0.05);
}}
.st-key-econ-expander {{ margin-bottom: 2rem; }}

/* Honesty banners restyled as intentional callouts, not default
   error/warning chrome -- one accent bar, no icon (hard rule: no alert
   icons), kept full padding and weight, never shrunk. Streamlit paints
   the kind-specific colour wash on TWO nested divs -- stAlertContainer
   (a semi-transparent tint) and stAlertContent{{Kind}} inside it -- so
   both need neutralising or the tint bleeds through at the edges. */
div[data-testid="stAlert"] {{
    border: 1px solid {BORDER} !important;
    border-left: 4px solid {ACCENT} !important;
    border-radius: 0.5rem !important;
    box-shadow: 0 1px 3px rgba(28, 31, 36, 0.06);
    overflow: hidden;
}}
div[data-testid="stAlertContainer"] {{ background: {CARD} !important; }}
div[data-testid^="stAlertContent"] {{
    background: {CARD} !important;
    padding: 1.15rem 1.4rem !important;
}}
div[data-testid^="stAlertContent"] p {{ color: {INK} !important; }}
div[data-testid^="stAlertContent"] strong {{ color: {INK}; }}
[data-testid="stAlertDynamicIcon"] {{ display: none !important; }}

/* Sidebar: quieter, tighter typography -- controls, not a second
   column of competing prose. */
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
    font-size: 0.8rem;
    line-height: 1.4;
    color: {INK_MUTED};
}}
[data-testid="stSidebar"] [data-testid="stHeading"] h2 {{
    margin-top: 1.75rem;
    font-size: 1.05rem !important;
}}
</style>
"""


def humanize(col: str) -> str:
    col = col.removeprefix("contrib__")
    if col == "tenure_weeks":
        return "Merchant tenure"
    if col == "category_freq":
        return "Category commonness"
    if col == "volume_aov_interaction":
        return "Volume-up / AOV-down interaction"
    if col.endswith("_history_missing"):
        fam = col.removesuffix("_history_missing").replace("_", " ")
        return f"{fam}: insufficient recent history"
    for suffix, label in SUFFIX_LABELS.items():
        if col.endswith(f"_{suffix}"):
            fam = col[: -(len(suffix) + 1)]
            fam_label = FAMILY_LABELS.get(fam, fam.replace("_", " ").title())
            return f"{fam_label} ({label})"
    return col.replace("_", " ").title()


def far_label(far: float) -> str:
    return f"{far:.0%}"


def reais(x: float, decimals: int = 2) -> str:
    return f"R${x:,.{decimals}f}"


@st.cache_data
def load_data():
    missing = [
        f
        for f in ["demo_test_predictions.csv", "demo_seller_gmv.csv", "demo_event_acceleration.csv"]
        if not (FIG_DIR / f).exists()
    ]
    if missing:
        st.error(
            "Missing demo artefacts: "
            + ", ".join(missing)
            + ".\n\nRun `python src/prepare_demo_data.py` from the repo root first "
            "(see README.md, \"Interactive demo\") -- this app reads pre-computed "
            "files only and does not fit or score anything itself."
        )
        st.stop()

    predictions = pd.read_csv(FIG_DIR / "demo_test_predictions.csv", parse_dates=["week", "event_week"])
    gmv = pd.read_csv(FIG_DIR / "demo_seller_gmv.csv")
    acceleration = pd.read_csv(
        FIG_DIR / "demo_event_acceleration.csv", parse_dates=["event_week", "model_alarm_week"]
    )
    sweep = pd.read_csv(FIG_DIR / "phase4_calibrated_sweep.csv")
    precision_recall = pd.read_csv(FIG_DIR / "phase4_precision_recall.csv")
    # Same artefact README Section 4's "achieved row-level FAR" column
    # reads (DECISIONS.md D29/D30/D34) -- the nominal FAR a threshold
    # targets and the row-level FAR it actually achieves on test differ
    # (isotonic tie-plateaus), and this is the one place that gap is
    # measured, so it's read here rather than duplicated/hardcoded.
    achieved_far = pd.read_csv(FIG_DIR / "phase4_train_derived_thresholds.csv")
    achieved_far = achieved_far[achieved_far["threshold_origin"] == "test_derived"].set_index("nominal_far")[
        "achieved_row_level_far"
    ]
    with open("config/costs.yaml") as f:
        costs = yaml.safe_load(f)
    return predictions, gmv, acceleration, sweep, precision_recall, achieved_far, costs


def default_merchant_and_week(acceleration: pd.DataFrame) -> tuple[str, pd.Timestamp]:
    """Pick a merchant the model actually flags, so the first screen shows
    the engine doing something instead of an unflagged, unchanged case.

    Representative rather than flattering: among confirmed cessations the
    model beats the naive rule on at the default 5% FAR, pick one at the
    *median* acceleration (2 weeks -- the number the banner itself states),
    not the single most dramatic outlier. Ties broken by seller_id so the
    choice is deterministic across runs.
    """
    pool = acceleration[(acceleration["far"] == DEFAULT_FAR) & (acceleration["status"] == "beats_rule")]
    median_weeks = pool["acceleration_weeks"].median()
    at_median = pool[pool["acceleration_weeks"] == median_weeks].sort_values("seller_id")
    chosen = at_median.iloc[0]
    return chosen["seller_id"], chosen["model_alarm_week"]


def sparkline(trail: pd.DataFrame, threshold: float) -> alt.LayerChart:
    """Compact trend line beside the hazard metric -- no axis chrome, a
    thin threshold rule, sized to sit next to a number rather than as a
    standalone chart."""
    spark_df = trail[["week", "calibrated_hazard"]].rename(columns={"calibrated_hazard": "hazard"})
    line = (
        alt.Chart(spark_df)
        .mark_line(point=alt.OverlayMarkDef(size=25, filled=True), color=ACCENT, strokeWidth=2.25)
        .encode(
            x=alt.X("week:T", title=None, axis=None),
            y=alt.Y("hazard:Q", title=None, axis=None),
            tooltip=[alt.Tooltip("week:T", title="Week"), alt.Tooltip("hazard:Q", title="Hazard", format=".2%")],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"threshold": [threshold]}))
        .mark_rule(strokeDash=[3, 3], color=INK_MUTED, strokeWidth=1)
        .encode(y="threshold:Q")
    )
    return (line + rule).properties(height=64)


def main() -> None:
    st.set_page_config(page_title="Reserve decision engine (demo)", layout="wide")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    predictions, gmv, acceleration, sweep, precision_recall, achieved_far_lookup, costs = load_data()
    contrib_cols = [c for c in predictions.columns if c.startswith("contrib__")]

    st.title("Reserve decision engine")
    st.caption(
        "A demonstration of an evaluated research result on the Olist Brazilian marketplace "
        "test set (2018), not a production system. Every number on this page is read from a "
        "file written by an already-run, already-reported script — nothing here is fit or "
        "scored live. Full evaluation and limitations: `README.md`, `DECISIONS.md`."
    )

    # ---- required honesty banner, always visible, not collapsible ----
    # Full evaluation used to be spread across three banners occupying
    # most of the page (D32). Restructured, not softened (DECISIONS.md
    # D33): one short banner states the single most important sentence
    # and points to "Method & limitations," which carries every word of
    # the original text, unchanged, one click away.
    st.warning(
        "**The model detects that a seller has already gone quiet, a little faster than a "
        "fixed rule — it does not predict distress weeks in advance** (0.53–0.59 AUC on that "
        "specific claim; near chance). Full evaluation, the outcomes breakdown at the FAR "
        "selected below, and the calibration caveat are in **Method & limitations**, one tab "
        "over."
    )

    # ---- sidebar: operating point ----
    st.sidebar.header("Operating point")
    st.sidebar.caption("**FAR**: share of a healthy seller's weekly rows flagged as a false alarm.")
    far_options = sorted(acceleration["far"].unique())
    far = st.sidebar.selectbox(
        "False-alarm rate (FAR)",
        far_options,
        index=far_options.index(DEFAULT_FAR),
        format_func=far_label,
    )
    far_row = sweep.loc[sweep["false_alarm_rate"] == far].iloc[0]
    threshold = float(far_row["threshold"])

    # Compact stat block, not prose (DECISIONS.md D33), regrouped into
    # two labelled blocks rather than six flat metrics (DECISIONS.md
    # D35): "Operating point" (what was chosen and what it costs in false
    # alarms) and "Test-set performance" (how it actually did there) are
    # different questions, and reading them as one undifferentiated grid
    # blurred that. Target and achieved row-level FAR are different
    # numbers (isotonic tie-plateaus, D29/D30 -- 5% nominal achieves
    # 5.9%, 1% achieves 2.5%, 10% achieves 12.0%), and showing only "5%"
    # here once contradicted the README's own methodology (D34). Achieved
    # figure is read from the same artefact README Section 4's table
    # reads, not hardcoded, so the two can't drift apart.
    pr_row_far = precision_recall[precision_recall["far"] == far]
    pr = pr_row_far.iloc[0] if len(pr_row_far) else None
    achieved = achieved_far_lookup.get(far)

    # Full-width, not a column split -- "target -> achieved" needs more
    # room than a narrow sidebar column gives it without truncating.
    st.sidebar.metric(
        "Row FAR: target → achieved",
        f"{far_label(far)} → {achieved:.1%}" if achieved is not None else far_label(far),
    )
    st.sidebar.metric("Seller FAR", f"{far_row['seller_level_false_alarm_rate']:.1%}")

    st.sidebar.divider()
    st.sidebar.header("Test-set performance")
    # Two columns, not three -- D32's bumped-up metric-value font size
    # (a main-content focal-point choice) truncates in anything narrower
    # than half the sidebar; caught by screenshot, not assumed to fit.
    perf_a, perf_b = st.sidebar.columns(2)
    perf_a.metric("Precision", f"{pr['precision']:.1%}" if pr is not None else "—")
    perf_b.metric("Recall", f"{pr['recall']:.1%}" if pr is not None else "—")
    st.sidebar.metric("Alerts", f"{int(pr['n_flagged']):,}" if pr is not None else "—")
    st.sidebar.caption(
        f"{int(pr['true_events_caught'])} of these alerts are true cessations "
        "(full breakdown: Method & limitations)."
        if pr is not None
        else "No precision/recall recorded at this operating point."
    )

    accel_at_far = acceleration[acceleration["far"] == far]
    n_events = len(accel_at_far)

    # Rendered inside the "Method & limitations" tab, below -- computed
    # here because accel_at_far/n_events are also needed by the "known
    # outcome" card in the merchant view.

    # ---- sidebar: merchant + week ----
    default_seller_id, default_alarm_week = default_merchant_and_week(acceleration)

    st.sidebar.divider()
    st.sidebar.header("Merchant")
    st.sidebar.caption("Test-set sellers; confirmed cessations marked and listed first.")
    sellers = predictions[["seller_id", "category", "event_B"]].drop_duplicates("seller_id")
    sellers = sellers.sort_values(["event_B", "seller_id"], ascending=[False, True]).reset_index(drop=True)
    sellers["label"] = sellers.apply(
        lambda r: f"{r['seller_id'][:10]}…  ·  {r['category']}"
        + ("  · [known cessation in test set]" if r["event_B"] else ""),
        axis=1,
    )
    default_seller_pos = sellers.index[sellers["seller_id"] == default_seller_id]
    default_seller_idx = int(default_seller_pos[0]) if len(default_seller_pos) else 0
    choice = st.sidebar.selectbox("Select a merchant", sellers["label"], index=default_seller_idx)
    seller_id = sellers.loc[sellers["label"] == choice, "seller_id"].iloc[0]

    merchant_rows = predictions[predictions["seller_id"] == seller_id].sort_values("week").reset_index(drop=True)
    weeks_available = merchant_rows["week"].dt.date.tolist()
    if seller_id == default_seller_id and default_alarm_week.date() in weeks_available:
        default_week_idx = weeks_available.index(default_alarm_week.date())
    else:
        default_week_idx = len(weeks_available) - 1
    st.sidebar.caption("Any week in this merchant's test-window history.")
    week_choice = st.sidebar.selectbox("Week", weeks_available, index=default_week_idx)
    row = merchant_rows[merchant_rows["week"].dt.date == week_choice].iloc[0]
    row_idx = merchant_rows.index[merchant_rows["week"].dt.date == week_choice][0]
    prev_row = merchant_rows.iloc[row_idx - 1] if row_idx > 0 else None

    is_event = bool(row["event_B"])
    weekly_gmv = float(gmv.loc[gmv["seller_id"] == seller_id, "weekly_gmv"].iloc[0])
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    # ---- the merchant view is the primary content (DECISIONS.md D33);
    # method and limitations are one tab over, not stacked above it ----
    tab_merchant, tab_method = st.tabs(["Merchant view", "Method & limitations"])

    with tab_merchant:
        _render_merchant_view(
            row, prev_row, merchant_rows, threshold, far, is_event, accel_at_far,
            weekly_gmv, reserve_pct, wc_rate, benefit_capture, far_row, pr_row_far,
            contrib_cols,
        )

    with tab_method:
        _render_method_and_limitations(far, achieved, n_events, accel_at_far)


def _render_merchant_view(
    row, prev_row, merchant_rows, threshold, far, is_event, accel_at_far,
    weekly_gmv, reserve_pct, wc_rate, benefit_capture, far_row, pr_row_far,
    contrib_cols,
) -> None:
    # ---- merchant snapshot: the focal point of the page ----
    st.header("Merchant snapshot")
    with st.container(border=True, key="snapshot-card"):
        hazard_col, spark_col, flag_col, gmv_col = st.columns([1.15, 1.5, 0.85, 1.05])

        hazard_this_week = float(row["calibrated_hazard"])
        hazard_last_week = float(prev_row["calibrated_hazard"]) if prev_row is not None else None
        # The delta is a difference of two percentages, i.e. percentage
        # points, not itself a percentage -- ".2%" formatting on the raw
        # difference understated it by ~100x. "pp" makes the unit explicit.
        with hazard_col:
            st.metric(
                "Calibrated hazard, this week",
                f"{hazard_this_week:.2%}",
                delta=(
                    f"{(hazard_this_week - hazard_last_week) * 100:+.2f} pp vs. last week"
                    if hazard_last_week is not None
                    else None
                ),
                delta_color="off",  # a hazard estimate has no "danger direction" -- see banners
            )

        trail = merchant_rows[merchant_rows["week"] <= row["week"]].tail(12)
        with spark_col:
            st.altair_chart(sparkline(trail, threshold), width="stretch")
            st.caption(f"Last {len(trail)} week(s) · dashed line = flag threshold")

        flagged = hazard_this_week >= threshold
        with flag_col:
            st.metric("Flagged?", "Yes" if flagged else "No")
        with gmv_col:
            st.metric("Avg. weekly GMV", reais(weekly_gmv, 0))

    # ---- simulated policy action ----
    with st.container(border=True, key="policy-card"):
        st.subheader("Simulated policy action")
        st.caption(
            "The model determines only the flag (hazard ≥ threshold, above). The reserve "
            "percentage applied when flagged is a fixed `config/costs.yaml` assumption, not "
            "something the model sizes or has any say over — see Section 2, limitation 2."
        )
        if flagged:
            st.write(
                f"**Hold an additional {reserve_pct:.0%} reserve** on this merchant's settlements "
                f"while the flag holds (threshold {threshold:.4f} at {far_label(far)} FAR)."
            )
        else:
            st.write(f"**No additional reserve under this simulated policy** at the {far_label(far)} operating point.")
        st.caption(
            "This is a binary threshold policy — flag or don't — with a fixed reserve percentage "
            "when flagged, not a continuous hazard-to-reserve formula (that fuller design was "
            "scoped out; DECISIONS.md D15)."
        )

    # ---- what changed since last week ----
    with st.container(border=True, key="changed-card"):
        st.subheader("What changed since last week")
        if prev_row is None:
            st.write("No prior week in the test window for this merchant.")
        else:
            deltas = pd.DataFrame(
                {
                    "feature": [humanize(c) for c in contrib_cols],
                    "delta": [row[c] - prev_row[c] for c in contrib_cols],
                }
            )
            deltas["abs"] = deltas["delta"].abs()
            top_movers = (
                deltas.sort_values("abs", ascending=False).head(5).drop(columns="abs").reset_index(drop=True)
            )
            top_movers["direction"] = top_movers["delta"].apply(
                lambda v: "raises hazard" if v > 0 else "lowers hazard"
            )
            zero_rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=BORDER, strokeWidth=1).encode(x="x:Q")
            bars = (
                alt.Chart(top_movers)
                .mark_bar(size=22)
                .encode(
                    x=alt.X("delta:Q", title="Δ contribution to log-odds score", axis=alt.Axis(grid=False)),
                    y=alt.Y("feature:N", sort=top_movers["feature"].tolist(), title=None),
                    color=alt.Color(
                        "direction:N",
                        scale=alt.Scale(domain=["raises hazard", "lowers hazard"], range=[ACCENT_WARM, ACCENT]),
                        legend=alt.Legend(title=None, orient="bottom"),
                    ),
                    tooltip=[
                        alt.Tooltip("feature:N", title="Feature"),
                        alt.Tooltip("delta:Q", title="Δ contribution", format="+.4f"),
                    ],
                )
                .properties(height=36 * len(top_movers))
            )
            st.altair_chart(zero_rule + bars, width="stretch")
            st.caption(
                "Exact decomposition for this linear model: each feature's contribution is its "
                "coefficient × standardised value; the deltas above sum to the change in the "
                "underlying log-odds score, not an approximation. Sorted by magnitude; colour is "
                "the one signed quantity on this page, so it's the one place colour is used for "
                "meaning rather than decoration."
            )

    # ---- known outcome ----
    if is_event:
        with st.container(border=True, key="outcome-card"):
            st.subheader("Known outcome in the test set (not a live prediction)")
            outcome_row = accel_at_far[accel_at_far["seller_id"] == row["seller_id"]]
            if len(outcome_row):
                o = outcome_row.iloc[0]
                status_text = {
                    "beats_rule": f"the model flagged this merchant **{o['acceleration_weeks']:.0f} weeks before** "
                    f"the N=8 rule would have confirmed it (rule confirmation: {o['event_week'].date()}, "
                    f"model alarm: {o['model_alarm_week'].date()}).",
                    "ties_rule": f"the model flagged this merchant the **same week** the N=8 rule confirmed it "
                    f"({o['event_week'].date()}).",
                    "never_flagged": f"the model **never flagged** this merchant before the N=8 rule confirmed "
                    f"it on {o['event_week'].date()} — the same outcome the naive rule alone would give.",
                }[o["status"]]
                st.write(f"This merchant went on to a confirmed cessation. At {far_label(far)} FAR, {status_text}")

    # ---- cost trade-off ----
    with st.container(border=True, key="costs-card"):
        st.subheader("Estimated cost trade-off at this reserve level")
        weekly_wc_cost = weekly_gmv * reserve_pct * wc_rate
        two_week_benefit = 2 * weekly_gmv * reserve_pct * benefit_capture
        col_x, col_y = st.columns(2)
        with col_x:
            st.metric("If false alarm (stays healthy)", f"{reais(weekly_wc_cost)} / week held")
            st.caption("Working-capital cost charged to a healthy merchant while flagged (config/costs.yaml).")
        with col_y:
            st.metric("If caught ~2 weeks early", reais(two_week_benefit))
            st.caption(
                "Illustrative, not a prediction for this merchant specifically — 2 weeks is the "
                "population median acceleration when the model does beat the rule (a minority of "
                "cases; see the banner above)."
            )

    with st.expander("Population-level economics at this FAR (from the evaluated test set)"):
        # far_row already computed above (sidebar); pr_row_far reused here too.
        pr_row = pr_row_far
        st.write(
            f"- Net Δcost vs. the naive rule: **{reais(far_row['net_delta_cost_per_1000_merchant_weeks_reais'])} "
            "per 1,000 merchant-weeks** (negative = the model-based policy saves money; DECISIONS.md D16/D21)"
        )
        st.write(
            f"- Seller-level false-alarm rate: **{far_row['seller_level_false_alarm_rate']:.1%}** "
            "of healthy sellers flagged at least once"
        )
        if len(pr_row):
            st.write(
                f"- Precision **{pr_row['precision'].iloc[0]:.1%}**, recall **{pr_row['recall'].iloc[0]:.1%}** "
                "on the held-out test window (DECISIONS.md D23) — most flags are false alarms; "
                "the economics work anyway because the cost-model ratio makes each rare true "
                "positive worth far more than each false positive costs, not because precision is high."
            )


def _render_method_and_limitations(
    far: float, achieved: float | None, n_events: int, accel_at_far: pd.DataFrame
) -> None:
    """Every word that used to occupy most of the page's visible area
    (DECISIONS.md D33) -- relocated, not cut and not softened. Reachable
    in one click from the short top banner."""
    st.subheader("What this model actually does")
    st.warning(
        "**What this model actually does:** it does not predict distress weeks in advance "
        "(checked directly — DECISIONS.md D13/D14 — discrimination is 0.53–0.59 AUC, near "
        "chance, at every horizon tested before a seller's last order). What it does is "
        "sometimes recognise a seller going quiet a little faster than a fixed rule that "
        "simply waits eight silent weeks. The banner below updates for whichever false-alarm "
        "rate is selected in the sidebar."
    )

    # "Target" throughout, not "at X% FAR" bare -- the achieved row-level
    # FAR differs from the nominal target (isotonic tie-plateaus, D29/
    # D30), and stating only the nominal number here would make the same
    # nominal-as-achieved claim the sidebar used to (DECISIONS.md D34).
    achieved_clause = f" (achieved {achieved:.1%} on this test set)" if achieved is not None else ""
    st.subheader(f"Outcomes at a {far_label(far)} FAR target{achieved_clause}")
    if n_events == 0:
        # Defensive: with the sidebar selector restricted to the FARs the
        # acceleration artefact actually covers this shouldn't be
        # reachable, but the artefact and the selector are two separate
        # files -- if they ever drift apart again, show this instead of
        # dividing by zero.
        st.info(
            f"No confirmed cessations are recorded at a {far_label(far)} false-alarm rate target in "
            "this demo's pre-computed artefacts — nothing to report at this operating point."
        )
    else:
        n_never = int((accel_at_far["status"] == "never_flagged").sum())
        n_beats = int((accel_at_far["status"] == "beats_rule").sum())
        n_ties = int((accel_at_far["status"] == "ties_rule").sum())
        if n_beats > 0:
            median_accel = accel_at_far.loc[accel_at_far["status"] == "beats_rule", "acceleration_weeks"].median()
            beats_clause = (
                f"{n_beats} ({n_beats / n_events:.0%}) are flagged earlier, by a median of "
                f"{median_accel:.1f} weeks. "
            )
        else:
            beats_clause = f"{n_beats} ({n_beats / n_events:.0%}) are flagged earlier. "
        st.info(
            f"**At a {far_label(far)} false-alarm rate target{achieved_clause}, on the {n_events} confirmed "
            f"cessations in the test set:** {n_never} ({n_never / n_events:.0%}) are never flagged before "
            f"the naive N=8-week rule would confirm them anyway — the model gives them nothing. "
            f"{beats_clause}"
            f"{n_ties} ({n_ties / n_events:.0%}) are flagged the same week "
            "the rule would fire. This is a minority-benefit result, not broad early warning — "
            "see DECISIONS.md D14 §2 / D21."
        )

    st.subheader("Calibration caveat")
    st.warning(
        "**Calibration caveat:** the highest-risk decile of predictions in back-testing is "
        "over-confident by roughly 2x (mean predicted 8.0% vs. mean actual 3.9%; DECISIONS.md "
        "D19). A hazard estimate near the top of the range shown on this page should be read "
        "as directionally high, not as a precise probability."
    )
    st.caption(
        "This demo does not implement the brief's original continuous reserve-sizing surface "
        "(hazard × merchant size), the N=4/12 robustness sweep, or the four-baseline comparison "
        "— all explicitly out of scope for this build (README.md Section 8)."
    )


if __name__ == "__main__":
    main()
