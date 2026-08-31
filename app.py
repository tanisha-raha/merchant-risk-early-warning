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

Visual design (DECISIONS.md D32, D36, D37): one considered palette
(`.streamlit/config.toml` + the CSS block in `main()`), applied
consistently. The one sanctioned exception to "one accent" is the
feature-contribution chart, where a second colour encodes a genuinely
signed quantity, plus one status accent for the flag state (D37) --
never a red/amber/green severity gradient. No gauges, no 0-100 risk
scores, no red/amber/green threat levels, no alert icons, no categorical
risk labels ("HIGH RISK" etc.) -- a hazard estimate does not have a
"danger level," and nothing here should imply more confidence or
precision than 0.68 AUC and a minority-benefit result support.
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

RANGE_OPTIONS = {"6W": 6, "12W": 12, "24W": 24, "All": None}
DEFAULT_RANGE = "12W"

NAV_ITEMS = ["Merchant review", "Method & limitations", "About this project"]

# One considered palette, matching .streamlit/config.toml, defined once
# and reused for both the CSS block and the Altair charts so the two
# can't drift apart. ACCENT is the one colour used throughout the page.
# ACCENT_WARM has two sanctioned uses, both signed/stateful rather than a
# severity gradient (DECISIONS.md D32, D37): the feature-contribution
# chart's "raises hazard" direction, and the flag-status accent -- one
# colour, on or off, never varying by "how risky."
ACCENT = "#2F6F8F"
ACCENT_WARM = "#B5602E"
INK = "#1C1F24"
INK_MUTED = "#646B78"
PAPER = "#F7F6F2"
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
/* ---- one clean block, one palette, applied throughout (D32, D36, D37) ---- */

:root {{
    --fs-display: 2.5rem;
    --fs-small: 0.85rem;
    --fs-micro: 0.72rem;
}}

[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stToolbarActions"], [data-testid="stStatusWidget"] {{
    display: none !important;
}}
header[data-testid="stHeader"] {{ height: 1rem; background: transparent; }}
footer {{ visibility: hidden; height: 0; }}

[data-testid="stAppViewBlockContainer"] {{ max-width: 100%; padding: 1rem 2rem 2.5rem; }}

[data-testid="stHeading"] h2 {{ margin-top: 1.25rem; margin-bottom: 0.5rem; }}
[data-testid="stHeading"] h3 {{ margin-top: 0.25rem; margin-bottom: 0.4rem; }}

[data-testid="stMetricLabel"] p {{
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: var(--fs-micro) !important;
    font-weight: 600 !important;
    color: {INK_MUTED} !important;
}}
[data-testid="stMetricValue"] {{ color: {INK}; }}

/* Metric/summary cards: restrained shadow + subtle border, denser
   padding than D36's sections -- matching the reference's information
   density rather than D36's more spacious single-column cards. The
   five top metric cards share a "metric-card-*" key prefix (each needs
   a distinct key -- Streamlit forbids reusing one across a loop of
   containers -- so this targets the prefix via an attribute selector
   rather than listing five exact class names). */
[class*="st-key-metric-card-"], .st-key-cost-card, .st-key-outcome-card,
.st-key-opstrip-card, .st-key-about-card, .st-key-chart-card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 0.6rem;
    padding: 1rem 1.25rem;
    box-shadow: 0 1px 2px rgba(28, 31, 36, 0.04);
}}
.st-key-policy-card, .st-key-changed-card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 0.6rem;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 1px 2px rgba(28, 31, 36, 0.04);
}}
.st-key-econ-expander {{ margin-bottom: 1.25rem; }}
.st-key-toolbar {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 0.6rem;
    padding: 0.85rem 1.25rem 0.25rem;
    margin-bottom: 0.9rem;
    box-shadow: 0 1px 2px rgba(28, 31, 36, 0.04);
}}

/* Left navigation rail -- page destinations only (Merchant review /
   Method & limitations / About this project), not the FAR/merchant/week
   controls, which stay in the top toolbar (DECISIONS.md D37). No logo,
   no product branding -- explicit instruction. */
.st-key-nav-rail {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 0.6rem;
    padding: 0.5rem;
}}
.st-key-nav-rail [data-testid="stButton"] button {{
    justify-content: flex-start;
    font-weight: 500;
}}
.st-key-about-demo-card {{
    background: {PAPER};
    border: 1px solid {BORDER};
    border-radius: 0.6rem;
    padding: 1rem 1.1rem;
    margin-top: 1rem;
    font-size: var(--fs-small);
    color: {INK_MUTED};
}}
.st-key-about-demo-card p {{ font-size: var(--fs-small); color: {INK_MUTED}; }}

/* Flag-status accent: ONE colour, on/off, never a severity gradient
   (hard rule, DECISIONS.md D37). Checked by construction: this class is
   applied identically regardless of *which* merchant/week is flagged --
   only whether the boolean is true. */
.flag-on {{ color: {ACCENT_WARM}; }}
.flag-off {{ color: {INK}; }}

.hero-label {{
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: var(--fs-micro);
    font-weight: 600;
    color: {INK_MUTED};
    margin-bottom: 0.2rem;
}}
.hero-value {{ font-size: var(--fs-display); font-weight: 700; line-height: 1.05; }}
.hero-sub {{ font-size: var(--fs-small); color: {INK_MUTED}; margin-top: 0.35rem; }}

.timeline-row {{ font-size: var(--fs-small); color: {INK}; margin: 0.15rem 0; }}
.timeline-row b {{ color: {INK}; }}

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
    padding: 1.1rem 1.35rem !important;
}}
div[data-testid^="stAlertContent"] p {{ color: {INK} !important; }}
div[data-testid^="stAlertContent"] strong {{ color: {INK}; }}
[data-testid="stAlertDynamicIcon"] {{ display: none !important; }}
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
    return f"R${x:,.2f}" if decimals else f"R${x:,.0f}"


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


def hazard_trajectory_chart(
    trail: pd.DataFrame,
    threshold: float,
    current_week: pd.Timestamp,
    model_alarm_week: pd.Timestamp | None,
    rule_confirm_week: pd.Timestamp | None,
) -> tuple[alt.LayerChart, bool]:
    """The currently-selected range window (DECISIONS.md D37's 6W/12W/
    24W/All control), trailing from the selected week -- never a future
    week relative to what's selected, consistent with this app's
    point-in-time framing everywhere else. Marks the threshold, the
    selected week (always the rightmost point, by construction of the
    trailing window), the model's first alarm, and the N=8 rule's
    confirmation date -- the last two only drawn if they fall inside
    THIS window, not stretched for. Returns whether each was drawn, so
    the caller can state undrawn dates as text instead."""
    df = trail[["week", "calibrated_hazard"]].rename(columns={"calibrated_hazard": "hazard"})
    domain_min, domain_max = df["week"].min(), df["week"].max()

    line = (
        alt.Chart(df)
        .mark_line(color=ACCENT, strokeWidth=2.25)
        .encode(
            x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %d", grid=False)),
            y=alt.Y("hazard:Q", title="Calibrated hazard", axis=alt.Axis(format="%", gridColor=BORDER)),
            tooltip=[alt.Tooltip("week:T", title="Week"), alt.Tooltip("hazard:Q", title="Hazard", format=".2%")],
        )
    )
    points = alt.Chart(df).mark_point(filled=True, size=32, color=ACCENT, opacity=0.85).encode(
        x="week:T", y="hazard:Q"
    )
    threshold_rule = (
        alt.Chart(pd.DataFrame({"y": [threshold]}))
        .mark_rule(strokeDash=[4, 4], color=INK_MUTED, strokeWidth=1.25)
        .encode(y="y:Q")
    )
    layers = [line, points, threshold_rule]

    current_df = df[df["week"] == current_week]
    if len(current_df):
        current_point = (
            alt.Chart(current_df)
            .mark_point(filled=True, size=160, color=INK, stroke=ACCENT, strokeWidth=2)
            .encode(x="week:T", y="hazard:Q", tooltip=[alt.Tooltip("hazard:Q", title="Selected week", format=".2%")])
        )
        layers.append(current_point)

    alarm_drawn = False
    if model_alarm_week is not None and domain_min <= model_alarm_week <= domain_max:
        alarm_rule = (
            alt.Chart(pd.DataFrame({"x": [model_alarm_week]}))
            .mark_rule(color=ACCENT_WARM, strokeWidth=1.5)
            .encode(x="x:T")
        )
        layers.append(alarm_rule)
        alarm_drawn = True

    confirm_drawn = False
    if rule_confirm_week is not None and domain_min <= rule_confirm_week <= domain_max:
        confirm_rule = (
            alt.Chart(pd.DataFrame({"x": [rule_confirm_week]}))
            .mark_rule(color=INK, strokeDash=[2, 2], strokeWidth=1.5)
            .encode(x="x:T")
        )
        layers.append(confirm_rule)
        confirm_drawn = True

    chart = alt.layer(*layers).properties(height=300)
    return chart, alarm_drawn, confirm_drawn


def _set_nav(item: str) -> None:
    st.session_state["nav"] = item


def main() -> None:
    st.set_page_config(page_title="Reserve decision engine (demo)", layout="wide")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    if "nav" not in st.session_state:
        st.session_state["nav"] = "Merchant review"

    predictions, gmv, acceleration, sweep, precision_recall, achieved_far_lookup, costs = load_data()
    contrib_cols = [c for c in predictions.columns if c.startswith("contrib__")]

    nav_col, main_col = st.columns([1, 5])

    with nav_col:
        with st.container(key="nav-rail"):
            for item in NAV_ITEMS:
                # on_click, not "if st.button(...): set state" -- the
                # latter updates session_state only AFTER this same
                # button's own `type=` argument (primary/secondary) has
                # already been evaluated with the STALE value, so the
                # active highlight lags one click behind the content it's
                # supposed to match. Caught by screenshot (D37), not
                # assumed correct from the logic alone: clicking "Method
                # & limitations" switched the content immediately but
                # left "Merchant review" highlighted. on_click callbacks
                # run before the script body re-executes, so by the time
                # `type=` is evaluated on the next run, the state it
                # reads is already current.
                st.button(
                    item,
                    key=f"nav_{item}",
                    type="primary" if st.session_state["nav"] == item else "secondary",
                    width="stretch",
                    on_click=_set_nav,
                    args=(item,),
                )
        with st.container(key="about-demo-card"):
            st.markdown(
                "**About this demo**\n\n"
                "Historical replay on the Olist Brazilian marketplace test set (2018). The model "
                "detects sellers that have already gone quiet a little faster than an N=8 "
                "silent-weeks rule. It does not predict distress weeks in advance."
            )
            st.button(
                "Read more in Method tab",
                key="nav_about_link",
                width="stretch",
                on_click=_set_nav,
                args=("Method & limitations",),
            )

    with main_col:
        st.title("Reserve decision engine — demo")
        st.caption("Historical research replay (not a live predictor)")

        # ---- required honesty banner, always visible on the primary
        # view, not collapsible (DECISIONS.md D33, kept through D36/D37's
        # layout changes per explicit instruction not to hide or weaken
        # the historical-replay statement) ----
        st.warning(
            "**This is a historical replay of an evaluated result, not a live predictor.** The "
            "model detects that a seller has already gone quiet, a little faster than a fixed "
            "rule — it does not predict distress weeks in advance (0.53–0.59 AUC on that specific "
            "claim; near chance). Full evaluation, the outcomes breakdown at the FAR selected "
            "below, and the calibration caveat are in **Method & limitations**."
        )

        # ---- compact toolbar: FAR, merchant, week -- no permanent
        # sidebar of controls; the left rail is page navigation only ----
        with st.container(key="toolbar"):
            far_col, merchant_col, week_col = st.columns([1, 2, 1])

            with far_col:
                far_options = sorted(acceleration["far"].unique())
                far = st.selectbox(
                    "False-alarm rate (FAR)",
                    far_options,
                    index=far_options.index(DEFAULT_FAR),
                    format_func=far_label,
                    help="Share of a healthy seller's weekly rows flagged as a false alarm at this threshold.",
                )
            far_row = sweep.loc[sweep["false_alarm_rate"] == far].iloc[0]
            threshold = float(far_row["threshold"])
            pr_row_far = precision_recall[precision_recall["far"] == far]
            pr = pr_row_far.iloc[0] if len(pr_row_far) else None
            achieved = achieved_far_lookup.get(far)

            default_seller_id, default_alarm_week = default_merchant_and_week(acceleration)
            sellers = predictions[["seller_id", "category", "event_B"]].drop_duplicates("seller_id")
            sellers = sellers.sort_values(["event_B", "seller_id"], ascending=[False, True]).reset_index(drop=True)
            sellers["label"] = sellers.apply(
                lambda r: f"{r['seller_id'][:10]}…  ·  {r['category']}"
                + ("  · [known cessation in test set]" if r["event_B"] else ""),
                axis=1,
            )
            default_seller_pos = sellers.index[sellers["seller_id"] == default_seller_id]
            default_seller_idx = int(default_seller_pos[0]) if len(default_seller_pos) else 0
            with merchant_col:
                choice = st.selectbox(
                    "Merchant",
                    sellers["label"],
                    index=default_seller_idx,
                    help="Test-set sellers; confirmed cessations marked and listed first.",
                )
            seller_id = sellers.loc[sellers["label"] == choice, "seller_id"].iloc[0]

            merchant_rows = (
                predictions[predictions["seller_id"] == seller_id].sort_values("week").reset_index(drop=True)
            )
            weeks_available = merchant_rows["week"].dt.date.tolist()
            if seller_id == default_seller_id and default_alarm_week.date() in weeks_available:
                default_week_idx = weeks_available.index(default_alarm_week.date())
            else:
                default_week_idx = len(weeks_available) - 1
            with week_col:
                week_choice = st.selectbox(
                    "Week",
                    weeks_available,
                    index=default_week_idx,
                    help="Any week in this merchant's test-window history.",
                )

        row = merchant_rows[merchant_rows["week"].dt.date == week_choice].iloc[0]
        row_idx = merchant_rows.index[merchant_rows["week"].dt.date == week_choice][0]
        prev_row = merchant_rows.iloc[row_idx - 1] if row_idx > 0 else None

        is_event = bool(row["event_B"])
        hazard_this_week = float(row["calibrated_hazard"])
        hazard_last_week = float(prev_row["calibrated_hazard"]) if prev_row is not None else None
        flagged = hazard_this_week >= threshold
        weekly_gmv = float(gmv.loc[gmv["seller_id"] == seller_id, "weekly_gmv"].iloc[0])
        reserve_pct = costs["reserve_pct"]
        wc_rate = costs["working_capital_cost_weekly_rate"]
        benefit_capture = costs["benefit_capture_rate"]

        accel_at_far = acceleration[acceleration["far"] == far]
        n_events = len(accel_at_far)

        # First week this merchant's own hazard crosses the CURRENT
        # threshold, computed directly from the merchant's own trajectory
        # rather than only the event-only artefact -- works the same way
        # for a merchant that gets flagged without ever becoming a
        # confirmed cessation, not just the 237 that did.
        above = merchant_rows.loc[merchant_rows["calibrated_hazard"] >= threshold, "week"]
        model_alarm_week = above.min() if len(above) else None
        rule_confirm_week = row["event_week"] if is_event and pd.notna(row["event_week"]) else None

        if st.session_state["nav"] == "Merchant review":
            _render_merchant_review(
                row, prev_row, merchant_rows, threshold, far, is_event, accel_at_far,
                weekly_gmv, reserve_pct, wc_rate, benefit_capture, far_row, pr, pr_row_far,
                contrib_cols, hazard_this_week, hazard_last_week, flagged,
                model_alarm_week, rule_confirm_week, seller_id, achieved,
                predictions,
            )
        elif st.session_state["nav"] == "Method & limitations":
            _render_method_and_limitations(far, achieved, n_events, accel_at_far)
        else:
            _render_about_project()


def _render_merchant_review(
    row, prev_row, merchant_rows, threshold, far, is_event, accel_at_far,
    weekly_gmv, reserve_pct, wc_rate, benefit_capture, far_row, pr, pr_row_far,
    contrib_cols, hazard_this_week, hazard_last_week, flagged,
    model_alarm_week, rule_confirm_week, seller_id, achieved,
    predictions,
) -> None:
    # ---- five primary metric cards ----
    flag_class = "flag-on" if flagged else "flag-off"
    flag_text = "Flagged" if flagged else "Not flagged"
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1, st.container(key="metric-card-hazard"):
        delta_txt = ""
        if hazard_last_week is not None:
            delta_pp = (hazard_this_week - hazard_last_week) * 100
            delta_txt = f'<div class="hero-sub">{delta_pp:+.2f} pp vs. last week</div>'
        st.markdown(
            '<div class="hero-label">Calibrated hazard, this week</div>'
            f'<div class="hero-value" style="font-size:1.9rem">{hazard_this_week:.2%}</div>'
            f"{delta_txt}",
            unsafe_allow_html=True,
        )
    with m2, st.container(key="metric-card-flag"):
        st.markdown(
            '<div class="hero-label">Flag status</div>'
            f'<div class="hero-value {flag_class}" style="font-size:1.9rem">{flag_text}</div>'
            f'<div class="hero-sub">Score {"≥" if flagged else "<"} threshold ({threshold:.2%})</div>',
            unsafe_allow_html=True,
        )
    with m3, st.container(key="metric-card-threshold"):
        st.markdown(
            f'<div class="hero-label">Current flag threshold</div>'
            f'<div class="hero-value" style="font-size:1.9rem">{threshold:.2%}</div>'
            f'<div class="hero-sub">At {far_label(far)} FAR (calibrated)</div>',
            unsafe_allow_html=True,
        )
    with m4, st.container(key="metric-card-gmv"):
        st.markdown(
            '<div class="hero-label">Avg. weekly GMV</div>'
            f'<div class="hero-value" style="font-size:1.9rem">{reais(weekly_gmv, 0)}</div>'
            '<div class="hero-sub">In test window</div>',
            unsafe_allow_html=True,
        )
    with m5, st.container(key="metric-card-sellerfar"):
        st.markdown(
            '<div class="hero-label">Seller FAR (test set)</div>'
            f'<div class="hero-value" style="font-size:1.9rem">{far_row["seller_level_false_alarm_rate"]:.1%}</div>'
            '<div class="hero-sub">% of healthy sellers flagged</div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # ---- main analysis row: hazard trajectory (~60%) + cost trade-off
    # and historical outcome (~40%) ----
    chart_col, info_col = st.columns([3, 2])

    with chart_col:
        with st.container(key="chart-card"):
            top_row = st.columns([3, 2])
            with top_row[0]:
                st.subheader("Hazard trajectory (weekly)")
            with top_row[1]:
                range_choice = st.segmented_control(
                    "Range", list(RANGE_OPTIONS.keys()), default=DEFAULT_RANGE, label_visibility="collapsed"
                )
            range_choice = range_choice or DEFAULT_RANGE
            n_weeks = RANGE_OPTIONS[range_choice]

            # Trailing window ending at the selected week -- never a
            # future week relative to what's selected (consistent with
            # this app's point-in-time framing everywhere else).
            # .tail(n) degrades gracefully on its own when the merchant
            # has fewer observations than the chosen range: it returns
            # whatever rows exist, no error, no padding, no change to
            # the analytical result (DECISIONS.md D37, checked below).
            up_to_selected = merchant_rows[merchant_rows["week"] <= row["week"]]
            trail = up_to_selected.tail(n_weeks) if n_weeks is not None else up_to_selected

            chart, alarm_drawn, confirm_drawn = hazard_trajectory_chart(
                trail, threshold, row["week"], model_alarm_week, rule_confirm_week
            )
            st.altair_chart(chart, width="stretch")

            legend = (
                "— Calibrated hazard &nbsp; · &nbsp; "
                "<span style='color:#646B78'>┄</span> Threshold "
                f"({far_label(far)} FAR) &nbsp; · &nbsp; ● Selected week"
            )
            if model_alarm_week is not None:
                legend += " &nbsp; · &nbsp; <span style='color:#B5602E'>│</span> Model alarm"
            if rule_confirm_week is not None:
                legend += " &nbsp; · &nbsp; <span style='color:#1C1F24'>┊</span> N=8 rule confirmation"
            st.markdown(f'<div class="hero-sub">{legend}</div>', unsafe_allow_html=True)

            st.write("")
            # Compact alarm/confirmation summary strip, always stated as
            # text regardless of whether either marker was drawn on the
            # chart above -- so a narrow range that pushes one or both
            # off-chart doesn't lose the fact, just the visual marker
            # (DECISIONS.md D37: "don't stretch the axis, state it
            # instead").
            strip_cols = st.columns([2, 2, 1])
            with strip_cols[0]:
                alarm_txt = model_alarm_week.date() if model_alarm_week is not None else "never (this FAR)"
                off_chart = "" if alarm_drawn or model_alarm_week is None else " *(outside displayed range)*"
                st.markdown(f"**Model alarm:** {alarm_txt}{off_chart}")
            with strip_cols[1]:
                if rule_confirm_week is not None:
                    off_chart = "" if confirm_drawn else " *(outside displayed range)*"
                    st.markdown(f"**N=8 rule confirmation:** {rule_confirm_week.date()}{off_chart}")
                elif is_event:
                    st.markdown("**N=8 rule confirmation:** —")
                else:
                    st.markdown("**N=8 rule confirmation:** n/a (not a confirmed cessation)")
            with strip_cols[2]:
                if is_event and model_alarm_week is not None and rule_confirm_week is not None:
                    lead = (rule_confirm_week - model_alarm_week).days / 7
                    if lead > 0:
                        st.markdown(f"**{lead:.0f} weeks earlier**")
                    else:
                        st.markdown("**Same week**")

    with info_col:
        with st.container(key="cost-card"):
            st.subheader("Estimated cost trade-off at this reserve level")
            weekly_wc_cost = weekly_gmv * reserve_pct * wc_rate
            two_week_benefit = 2 * weekly_gmv * reserve_pct * benefit_capture
            cx, cy = st.columns(2)
            with cx:
                st.metric("If false alarm", f"{reais(weekly_wc_cost)} / wk")
                st.caption("Working-capital cost while flagged (config/costs.yaml).")
            with cy:
                st.metric("If caught ~2wk early", reais(two_week_benefit))
                st.caption(
                    "Illustrative — 2 weeks is the population median acceleration when the model "
                    "does beat the rule (a minority of cases; see the banner above)."
                )

        st.write("")

        with st.container(key="outcome-card"):
            st.subheader("Historical outcome (test set)")
            if not is_event:
                st.write(
                    "This merchant is **censored** in the test set — no confirmed cessation "
                    "observed within the study window."
                )
                if model_alarm_week is not None:
                    st.markdown(
                        f'<div class="timeline-row">Model alarm: <b>{model_alarm_week.date()}</b></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="timeline-row">Never flagged at {far_label(far)} FAR in this merchant\'s '
                        "test-window history.</div>",
                        unsafe_allow_html=True,
                    )
            else:
                outcome_row = accel_at_far[accel_at_far["seller_id"] == row["seller_id"]]
                status = outcome_row.iloc[0]["status"] if len(outcome_row) else None
                st.write("This merchant went on to a **confirmed cessation**.")
                if status == "never_flagged":
                    # Stated directly, per instruction, rather than
                    # implying an earlier detection that didn't happen.
                    st.write(
                        f"The model **never flagged** this merchant before the N=8 rule confirmed "
                        f"it on {row['event_week'].date()} — the same outcome the naive rule alone "
                        "would give."
                    )
                st.markdown(
                    f'<div class="timeline-row">Model alarm: '
                    f'<b>{model_alarm_week.date() if model_alarm_week is not None else "never"}</b></div>'
                    f'<div class="timeline-row">N=8 rule confirmation: <b>{row["event_week"].date()}</b></div>',
                    unsafe_allow_html=True,
                )
                if status == "beats_rule" and len(outcome_row):
                    weeks = outcome_row.iloc[0]["acceleration_weeks"]
                    st.markdown(
                        f'<div class="timeline-row">Lead time: <b>{weeks:.0f} weeks earlier</b></div>',
                        unsafe_allow_html=True,
                    )
                elif status == "ties_rule":
                    st.markdown('<div class="timeline-row">Lead time: <b>same week as the rule</b></div>', unsafe_allow_html=True)

    st.write("")

    # ---- simulated policy action ----
    with st.container(key="policy-card"):
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
    with st.container(key="changed-card"):
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
                .mark_bar(size=20)
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
                .properties(height=32 * len(top_movers))
            )
            st.altair_chart(zero_rule + bars, width="stretch")
            st.caption(
                "Exact decomposition for this linear model: each feature's contribution is its "
                "coefficient × standardised value; the deltas above sum to the change in the "
                "underlying log-odds score, not an approximation. Sorted by magnitude; colour is "
                "the one signed quantity in this chart, so it's used for meaning, not decoration."
            )

    # ---- bottom row: operating-point summary strip + about this merchant ----
    bottom_left, bottom_right = st.columns([3, 2])

    with bottom_left, st.container(key="opstrip-card"):
        st.subheader("Operating point summary (test set)")
        s = st.columns(4)
        s[0].metric("Target row FAR", far_label(far))
        s[1].metric("Achieved row FAR", f"{achieved:.1%}" if achieved is not None else "—")
        s[2].metric("Seller FAR", f"{far_row['seller_level_false_alarm_rate']:.1%}")
        s[3].metric("Flagged rows", f"{int(pr['n_flagged']):,}" if pr is not None else "—")
        s2 = st.columns(4)
        s2[0].metric("True events", f"{int(pr['true_events_caught'])}" if pr is not None else "—")
        s2[1].metric("Precision", f"{pr['precision']:.1%}" if pr is not None else "—")
        s2[2].metric("Recall", f"{pr['recall']:.1%}" if pr is not None else "—")
        st.caption(
            "Target vs. achieved row-level FAR differ because of isotonic tie-plateaus "
            "(DECISIONS.md D29/D30) — never displayed as the same number (D34)."
        )

    with bottom_right, st.container(key="about-card"):
        st.subheader("About this merchant (in test window)")
        # Only fields already present in the committed demo artefacts --
        # no order-level "first order"/"total orders" date exists in
        # demo_test_predictions.csv (checked, not assumed; it's a weekly
        # panel, not order-level), so those are not fabricated here.
        # tenure_weeks, category, and week are the stored fields used.
        category = merchant_rows["category"].iloc[0]
        first_week = merchant_rows["week"].min()
        last_week = merchant_rows["week"].max()
        weeks_observed = len(merchant_rows)
        dataset_last_week = predictions["week"].max()
        weeks_since_last = int((dataset_last_week - last_week).days // 7)
        tenure_at_first = int(merchant_rows["tenure_weeks"].iloc[0])

        a1, a2 = st.columns(2)
        a1.metric("Category", category)
        a2.metric("Tenure at first observation", f"{tenure_at_first} wk")
        a3, a4 = st.columns(2)
        a3.metric("First week observed", str(first_week.date()))
        a4.metric("Last week observed", str(last_week.date()))
        a5, a6 = st.columns(2)
        a5.metric("Weeks observed", weeks_observed)
        a6.metric("Weeks since last observed", weeks_since_last)
        st.caption(
            "Test-window fields only — no order-level history in the demo artefacts, so "
            "order dates/counts aren't shown rather than inferred."
        )

    with st.expander("Population-level economics at this FAR (from the evaluated test set)"):
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
    (DECISIONS.md D33) -- relocated, not cut and not softened. Now its
    own left-nav destination rather than a tab (DECISIONS.md D37), still
    reachable in one click from the primary view's banner and the "About
    this demo" card."""
    st.subheader("What this model actually does")
    st.warning(
        "**What this model actually does:** it does not predict distress weeks in advance "
        "(checked directly — DECISIONS.md D13/D14 — discrimination is 0.53–0.59 AUC, near "
        "chance, at every horizon tested before a seller's last order). What it does is "
        "sometimes recognise a seller going quiet a little faster than a fixed rule that "
        "simply waits eight silent weeks. The banner below updates for whichever false-alarm "
        "rate is selected in the toolbar."
    )

    # "Target" throughout, not "at X% FAR" bare -- the achieved row-level
    # FAR differs from the nominal target (isotonic tie-plateaus, D29/
    # D30), and stating only the nominal number here would make the same
    # nominal-as-achieved claim the sidebar used to (DECISIONS.md D34).
    achieved_clause = f" (achieved {achieved:.1%} on this test set)" if achieved is not None else ""
    st.subheader(f"Outcomes at a {far_label(far)} FAR target{achieved_clause}")
    if n_events == 0:
        # Defensive: with the toolbar selector restricted to the FARs the
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


def _render_about_project() -> None:
    """New left-nav destination (DECISIONS.md D37) -- a short, honest
    orientation page, not a new analysis. Everything here restates
    claims already established and cited elsewhere (README.md,
    DECISIONS.md); nothing new is computed for it."""
    st.subheader("About this project")
    st.write(
        "This demo presents one evaluated result from a larger research project: can payment "
        "telemetry alone flag a failing merchant earlier and cheaper than a naive rule that "
        "waits for eight silent weeks? The honest answer, worked out in full in `README.md`, is "
        "\"modestly, and only for a minority of merchants.\""
    )
    st.write(
        "The dataset is the Olist Brazilian marketplace public dataset (2017–2018) — a proxy "
        "domain, not payment-aggregator data, and one of this project's stated limitations "
        "(`README.md` Section 2). The model is a discrete-time hazard model (logistic "
        "regression), calibrated with isotonic regression fit on train data only "
        "(`DECISIONS.md` D21)."
    )
    st.write(
        "This app is a presentation layer only: every number on every page is read from a file "
        "written by an already-run, already-reported script under `src/`. Nothing here fits, "
        "scores, calibrates, or sweeps a threshold at runtime — see the module docstring at the "
        "top of `app.py` and `README.md`'s \"Interactive demo\" section for exactly which "
        "artefacts are read."
    )
    st.write(
        "Full evaluation, every decision made along the way, and the dead ends that turned out "
        "to matter: `README.md`, `DECISIONS.md`, and `FAILURES.md` in the repository root."
    )


if __name__ == "__main__":
    main()
