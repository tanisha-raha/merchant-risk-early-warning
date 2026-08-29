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
    with open("config/costs.yaml") as f:
        costs = yaml.safe_load(f)
    return predictions, gmv, acceleration, sweep, precision_recall, costs


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


def main() -> None:
    st.set_page_config(page_title="Reserve decision engine (demo)", layout="wide")

    predictions, gmv, acceleration, sweep, precision_recall, costs = load_data()
    contrib_cols = [c for c in predictions.columns if c.startswith("contrib__")]

    st.title("Reserve decision engine — demo")
    st.caption(
        "A demonstration of an evaluated research result on the Olist Brazilian marketplace "
        "test set (2018), not a production system. Every number on this page is read from a "
        "file written by an already-run, already-reported script — nothing here is fit or "
        "scored live. Full evaluation and limitations: `README.md`, `DECISIONS.md`."
    )

    # ---- required honesty banner #1, always visible, not collapsible ----
    st.subheader("Read this first")
    st.warning(
        "**What this model actually does:** it does not predict distress weeks in advance "
        "(checked directly — DECISIONS.md D13/D14 — discrimination is 0.53–0.59 AUC, near "
        "chance, at every horizon tested before a seller's last order). What it does is "
        "sometimes recognise a seller going quiet a little faster than a fixed rule that "
        "simply waits eight silent weeks. The banner below updates for whichever false-alarm "
        "rate is selected in the sidebar — read it before reading anything else on this page."
    )

    # ---- sidebar: operating point ----
    st.sidebar.header("Operating point")
    st.sidebar.caption(
        "False-alarm rate (FAR), row-level: the share of a healthy seller's individual weekly "
        "snapshots the model flags anyway (not the share of merchants — see below). Higher FAR "
        "catches more real cessations, earlier, at the cost of more false alarms."
    )
    far_options = sorted(acceleration["far"].unique())
    far = st.sidebar.selectbox(
        "False-alarm rate (FAR)",
        far_options,
        index=far_options.index(DEFAULT_FAR),
        format_func=far_label,
    )
    far_row = sweep.loc[sweep["false_alarm_rate"] == far].iloc[0]
    threshold = float(far_row["threshold"])

    # Row-level and seller-level FAR are different quantities -- one
    # healthy seller contributes many weekly rows, so "5% FAR" flags a
    # much larger share of distinct sellers at least once. Shown together
    # here rather than just the row-level number, matching README Section
    # 3's footnote so this distinction is visible where FAR is chosen.
    st.sidebar.markdown(f"**Weekly (row-level) false-alarm rate:** {far_label(far)}")
    st.sidebar.caption(
        f"Equivalent seller-level FAR in test set: **{far_row['seller_level_false_alarm_rate']:.1%}** "
        "— the share of healthy sellers flagged at least once, not the share of weekly rows."
    )
    pr_row_far = precision_recall[precision_recall["far"] == far]
    if len(pr_row_far):
        pr = pr_row_far.iloc[0]
        alerts_per_true = pr["n_flagged"] / pr["true_events_caught"] if pr["true_events_caught"] else float("nan")
        st.sidebar.caption(
            f"At this FAR: **{int(pr['n_flagged']):,} flagged rows**, **{int(pr['true_events_caught'])} "
            f"true events caught**, **{pr['precision']:.1%} precision**, **{pr['recall']:.1%} recall** "
            f"— roughly {alerts_per_true:.0f} alerts per true cessation row caught."
        )

    accel_at_far = acceleration[acceleration["far"] == far]
    n_events = len(accel_at_far)

    st.subheader(f"Outcomes at {far_label(far)} FAR")
    if n_events == 0:
        # Defensive: with the selector restricted above this shouldn't be
        # reachable, but the artefact and the selector are two separate
        # files -- if they ever drift apart again, show this instead of
        # dividing by zero.
        st.info(
            f"No confirmed cessations are recorded at a {far_label(far)} false-alarm rate in "
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
            f"**At a {far_label(far)} false-alarm rate, on the {n_events} confirmed cessations in the "
            f"test set:** {n_never} ({n_never / n_events:.0%}) are never flagged before the naive "
            f"N=8-week rule would confirm them anyway — the model gives them nothing. "
            f"{beats_clause}"
            f"{n_ties} ({n_ties / n_events:.0%}) are flagged the same week "
            "the rule would fire. This is a minority-benefit result, not broad early warning — "
            "see DECISIONS.md D14 §2 / D21."
        )

    # ---- sidebar: merchant + week ----
    default_seller_id, default_alarm_week = default_merchant_and_week(acceleration)

    st.sidebar.divider()
    st.sidebar.header("Merchant")
    st.sidebar.caption(
        "Any seller in the held-out test window. Sellers with a confirmed cessation in the "
        "test set are marked and listed first. Defaults to a merchant the model actually "
        "flags, so the page below isn't empty on load."
    )
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
    st.sidebar.caption("Any week in this merchant's history within the test window.")
    week_choice = st.sidebar.selectbox("Week", weeks_available, index=default_week_idx)
    row = merchant_rows[merchant_rows["week"].dt.date == week_choice].iloc[0]
    row_idx = merchant_rows.index[merchant_rows["week"].dt.date == week_choice][0]
    prev_row = merchant_rows.iloc[row_idx - 1] if row_idx > 0 else None

    is_event = bool(row["event_B"])
    weekly_gmv = float(gmv.loc[gmv["seller_id"] == seller_id, "weekly_gmv"].iloc[0])
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    # ---- merchant snapshot ----
    st.divider()
    st.header("Merchant snapshot")
    with st.container(border=True):
        col_a, col_b, col_c = st.columns(3, border=True)

        hazard_this_week = float(row["calibrated_hazard"])
        hazard_last_week = float(prev_row["calibrated_hazard"]) if prev_row is not None else None
        # The delta is a difference of two percentages, i.e. percentage
        # points, not itself a percentage -- ".2%" formatting on the raw
        # difference understated it by ~100x. "pp" makes the unit explicit.
        col_a.metric(
            "Calibrated hazard estimate, this week",
            f"{hazard_this_week:.2%}",
            delta=(
                f"{(hazard_this_week - hazard_last_week) * 100:+.2f} pp vs. last week"
                if hazard_last_week is not None
                else None
            ),
            delta_color="off",  # a hazard estimate has no "danger direction" -- see banners
        )
        flagged = hazard_this_week >= threshold
        col_b.metric("Flagged at this FAR?", "Yes" if flagged else "No")
        col_c.metric("Merchant's own avg. weekly GMV", reais(weekly_gmv, 0))

        trail = merchant_rows[merchant_rows["week"] <= row["week"]].tail(12)
        spark_df = trail[["week", "calibrated_hazard"]].rename(columns={"calibrated_hazard": "hazard"})
        line = (
            alt.Chart(spark_df)
            .mark_line(point=True, color="#4C72B0")
            .encode(
                x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %d", grid=False)),
                y=alt.Y("hazard:Q", title=None, axis=alt.Axis(format="%", grid=False)),
                tooltip=[alt.Tooltip("week:T", title="Week"), alt.Tooltip("hazard:Q", title="Hazard", format=".2%")],
            )
        )
        rule = (
            alt.Chart(pd.DataFrame({"threshold": [threshold]}))
            .mark_rule(strokeDash=[4, 4], color="#888888")
            .encode(y="threshold:Q")
        )
        st.altair_chart((line + rule).properties(height=140), width="stretch")
        st.caption(
            f"Calibrated hazard, last {len(trail)} available week(s) in the test window. Dashed "
            f"line: this FAR's flag threshold ({threshold:.4f})."
        )

    # ---- simulated policy action ----
    with st.container(border=True):
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
            st.write(f"**No additional reserve recommended** at the {far_label(far)} operating point.")
        st.caption(
            "This is a binary threshold policy — flag or don't — with a fixed reserve percentage "
            "when flagged, not a continuous hazard-to-reserve formula (that fuller design was "
            "scoped out; DECISIONS.md D15)."
        )

    # ---- what changed since last week ----
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
        top_movers = deltas.sort_values("abs", ascending=False).head(5).drop(columns="abs").reset_index(drop=True)
        top_movers["direction"] = top_movers["delta"].apply(
            lambda v: "raises hazard" if v > 0 else "lowers hazard"
        )
        chart = (
            alt.Chart(top_movers)
            .mark_bar()
            .encode(
                x=alt.X("delta:Q", title="Δ contribution to log-odds score"),
                y=alt.Y("feature:N", sort=top_movers["feature"].tolist(), title=None),
                color=alt.Color(
                    "direction:N",
                    scale=alt.Scale(domain=["raises hazard", "lowers hazard"], range=["#DD8452", "#4C72B0"]),
                    legend=alt.Legend(title=None, orient="bottom"),
                ),
                tooltip=[
                    alt.Tooltip("feature:N", title="Feature"),
                    alt.Tooltip("delta:Q", title="Δ contribution", format="+.4f"),
                ],
            )
            .properties(height=32 * len(top_movers))
        )
        st.altair_chart(chart, width="stretch")
        st.caption(
            "Exact decomposition for this linear model: each feature's contribution is its "
            "coefficient × standardised value; the deltas above sum to the change in the "
            "underlying log-odds score, not an approximation."
        )

    # ---- known outcome ----
    if is_event:
        st.subheader("Known outcome in the test set (not a live prediction)")
        outcome_row = accel_at_far[accel_at_far["seller_id"] == seller_id]
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
    with st.container(border=True):
        st.subheader("Estimated cost trade-off at this reserve level")
        weekly_wc_cost = weekly_gmv * reserve_pct * wc_rate
        two_week_benefit = 2 * weekly_gmv * reserve_pct * benefit_capture
        col_x, col_y = st.columns(2, border=True)
        with col_x:
            st.metric("If this is a false alarm (stays healthy)", f"{reais(weekly_wc_cost)} / week held")
            st.caption("Working-capital cost charged to a healthy merchant while flagged (config/costs.yaml).")
        with col_y:
            st.metric("If it fails and is caught ~2 weeks early", reais(two_week_benefit))
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

    # ---- required honesty banner #2, always visible, not collapsible ----
    st.divider()
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
