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

import pandas as pd
import streamlit as st
import yaml

FIG_DIR = Path("figures")

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


def far_label(far: float) -> str:
    return f"{far:.0%}"


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

    # ---- required honesty banners, always visible, not collapsible ----
    st.warning(
        "**What this model actually does:** it does not predict distress weeks in advance "
        "(checked directly — DECISIONS.md D13/D14 — discrimination is 0.53–0.59 AUC, near "
        "chance, at every horizon tested before a seller's last order). What it does is "
        "sometimes recognise a seller going quiet a little faster than a fixed rule that "
        "simply waits eight silent weeks. The banner below updates for whichever false-alarm "
        "rate is selected in the sidebar — read it before reading anything else on this page."
    )

    # ---- sidebar controls ----
    st.sidebar.header("Operating point")
    far_options = sorted(sweep["false_alarm_rate"].unique())
    far = st.sidebar.selectbox("False-alarm rate (FAR)", far_options, index=far_options.index(0.05), format_func=far_label)
    threshold = float(sweep.loc[sweep["false_alarm_rate"] == far, "threshold"].iloc[0])

    accel_at_far = acceleration[acceleration["far"] == far]
    n_events = len(accel_at_far)
    n_never = int((accel_at_far["status"] == "never_flagged").sum())
    n_beats = int((accel_at_far["status"] == "beats_rule").sum())
    n_ties = int((accel_at_far["status"] == "ties_rule").sum())
    median_accel = accel_at_far.loc[accel_at_far["status"] == "beats_rule", "acceleration_weeks"].median()

    st.info(
        f"**At a {far_label(far)} false-alarm rate, on the {n_events} confirmed cessations in the "
        f"test set:** {n_never} ({n_never / n_events:.0%}) are never flagged before the naive "
        f"N=8-week rule would confirm them anyway — the model gives them nothing. "
        f"{n_beats} ({n_beats / n_events:.0%}) are flagged earlier, by a median of "
        f"{median_accel:.1f} weeks. {n_ties} ({n_ties / n_events:.0%}) are flagged the same week "
        "the rule would fire. This is a minority-benefit result, not broad early warning — "
        "see DECISIONS.md D14 §2 / D21."
    )

    st.sidebar.header("Merchant")
    sellers = predictions[["seller_id", "category", "event_B"]].drop_duplicates("seller_id")
    sellers = sellers.sort_values(["event_B", "seller_id"], ascending=[False, True])
    sellers["label"] = sellers.apply(
        lambda r: f"{r['seller_id'][:10]}…  ·  {r['category']}"
        + ("  · [known cessation in test set]" if r["event_B"] else ""),
        axis=1,
    )
    choice = st.sidebar.selectbox("Select a merchant", sellers["label"])
    seller_id = sellers.loc[sellers["label"] == choice, "seller_id"].iloc[0]

    merchant_rows = predictions[predictions["seller_id"] == seller_id].sort_values("week").reset_index(drop=True)
    weeks_available = merchant_rows["week"].dt.date.tolist()
    week_choice = st.sidebar.selectbox("Week", weeks_available, index=len(weeks_available) - 1)
    row = merchant_rows[merchant_rows["week"].dt.date == week_choice].iloc[0]
    row_idx = merchant_rows.index[merchant_rows["week"].dt.date == week_choice][0]
    prev_row = merchant_rows.iloc[row_idx - 1] if row_idx > 0 else None

    is_event = bool(row["event_B"])
    weekly_gmv = float(gmv.loc[gmv["seller_id"] == seller_id, "weekly_gmv"].iloc[0])
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    st.divider()
    col_a, col_b, col_c = st.columns(3)

    hazard_this_week = float(row["calibrated_hazard"])
    hazard_last_week = float(prev_row["calibrated_hazard"]) if prev_row is not None else None
    col_a.metric(
        "Calibrated hazard estimate, this week",
        f"{hazard_this_week:.2%}",
        delta=(f"{(hazard_this_week - hazard_last_week):+.2%} vs. last week" if hazard_last_week is not None else None),
        delta_color="inverse",
    )

    flagged = hazard_this_week >= threshold
    col_b.metric("Flagged at this FAR?", "Yes" if flagged else "No")
    col_c.metric("Merchant's own avg. weekly GMV", f"R${weekly_gmv:,.0f}")

    st.subheader("Recommended action")
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
        "scoped out; DECISIONS.md D15). The reserve percentage itself is an assumed parameter "
        "from `config/costs.yaml`, not measured."
    )

    st.subheader("What changed since last week")
    if prev_row is None:
        st.write("No prior week in the test window for this merchant.")
    else:
        deltas = pd.DataFrame(
            {
                "feature": [humanize(c) for c in contrib_cols],
                "Δ contribution to score": [row[c] - prev_row[c] for c in contrib_cols],
            }
        )
        deltas["abs"] = deltas["Δ contribution to score"].abs()
        top_movers = deltas.sort_values("abs", ascending=False).head(5).drop(columns="abs")
        top_movers["direction"] = top_movers["Δ contribution to score"].apply(
            lambda v: "↑ raises hazard" if v > 0 else ("↓ lowers hazard" if v < 0 else "no change")
        )
        st.dataframe(top_movers, hide_index=True, width="stretch")
        st.caption(
            "Exact decomposition for this linear model: each feature's contribution is its "
            "coefficient × standardised value; the deltas above sum to the change in the "
            "underlying log-odds score, not an approximation."
        )

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

    st.subheader("Estimated cost trade-off at this reserve level")
    weekly_wc_cost = weekly_gmv * reserve_pct * wc_rate
    two_week_benefit = 2 * weekly_gmv * reserve_pct * benefit_capture
    col_x, col_y = st.columns(2)
    with col_x:
        st.metric("If this is a false alarm (stays healthy)", f"R${weekly_wc_cost:,.2f} / week held")
        st.caption("Working-capital cost charged to a healthy merchant while flagged (config/costs.yaml).")
    with col_y:
        st.metric("If it fails and is caught ~2 weeks early", f"R${two_week_benefit:,.2f}")
        st.caption(
            "Illustrative, not a prediction for this merchant specifically — 2 weeks is the "
            "population median acceleration when the model does beat the rule (a minority of "
            "cases; see the banner above)."
        )

    with st.expander("Population-level economics at this FAR (from the evaluated test set)"):
        far_row = sweep[sweep["false_alarm_rate"] == far].iloc[0]
        pr_row = precision_recall[precision_recall["far"] == far]
        st.write(
            f"- Net Δcost vs. the naive rule: **R${far_row['net_delta_cost_per_1000_merchant_weeks_reais']:.2f} "
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
