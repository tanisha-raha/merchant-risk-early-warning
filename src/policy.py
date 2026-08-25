"""Phase 3: does the model's acceleration over the naive N=8 silence rule
(DECISIONS.md D14 sec.2 -- median ~2 weeks, for a minority of events)
justify its false-alarm cost?

**Not a reserve-sizing surface.** The brief's original Phase 3 design (a
reserve percentage as a function of hazard and merchant size) assumed the
model carries genuine multi-week early-warning signal to size a nuanced
policy against. D13/D14 found it doesn't, past ~2 weeks. Scope narrowed
accordingly (DECISIONS.md D15): sweep the row-level false-alarm rate from
1% to 10% (same test-period censored-row population used throughout
Phase 2) and report expected cost, per 1,000 merchant-weeks, of a
model-triggered early-reserve policy versus the rule -- using the exact
same acceleration mechanics as
`phase2_acceleration_vs_rule.py` (D14 sec.2), reused here rather than
reimplemented.

Cost model (config/costs.yaml -- every parameter there, none hardcoded):
- Benefit: for an event the model accelerates (crosses threshold strictly
  before event_week), extra reserve = acceleration_weeks x that seller's
  own average weekly revenue x reserve_pct x benefit_capture_rate.
- Cost: for every TEST-period row belonging to a CENSORED (healthy)
  seller whose score crosses the threshold, working-capital burden =
  weekly revenue x reserve_pct x working_capital_cost_weekly_rate.
- Net = cost - benefit, summed over the test period, normalised to cost
  per 1,000 merchant-weeks. The N=8 rule is cost 0 by construction (it
  has no false alarms -- the label IS its output, D14 sec.2) and no
  acceleration -- it IS the zero point this sweep is measured against.

Parameters are set once from documented, plausible defaults and NOT
tuned to make the model win, per instruction.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from features import build_features
from model import PRIMARY_N, TEST_CUTOFF, predict, run_for_n, transform_features
from panel import build_panel

FAR_SWEEP = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]


def load_costs(path: Path = Path("config/costs.yaml")) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def per_seller_weekly_gmv(panel: pd.DataFrame) -> pd.Series:
    """Each seller's own mean weekly revenue over their full observed
    history (including zero-order weeks) -- a stable per-merchant rate,
    not a single noisy week."""
    return panel.groupby("seller_id")["revenue"].mean()


def score_event_histories(fit: dict, features_df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Once, for every test-period event: the full (week, score) series
    over its out-of-sample history, from TEST_CUTOFF+1 through
    event_week. Scored once and reused across the whole FAR sweep --
    only the threshold changes per sweep point, not the scores."""
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]
    events = labels[labels["event_B"] & (labels["event_week"] > TEST_CUTOFF)]

    histories = {}
    for seller_id, row in events.iterrows():
        event_week = row["event_week"]
        hist = features_df[
            (features_df["seller_id"] == seller_id)
            & (features_df["week"] > TEST_CUTOFF)
            & (features_df["week"] <= event_week)
        ].sort_values("week")
        if hist.empty:
            histories[seller_id] = pd.DataFrame(columns=["week", "score"])
            continue
        scored = transform_features(hist, freq_map)
        scores = predict(clf, scaler, scored, feature_cols)
        histories[seller_id] = pd.DataFrame({"week": hist["week"].to_numpy(), "score": scores})
    return histories, events


def score_censored_rows(fit: dict, features_df: pd.DataFrame) -> pd.DataFrame:
    clf, scaler, freq_map, labels = fit["_clf"], fit["_scaler"], fit["_freq_map"], fit["_labels"]
    feature_cols = fit["_feature_cols"]
    censored = labels[~labels["event_B"]]
    rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    scored = transform_features(rows, freq_map)
    rows = rows.assign(score=predict(clf, scaler, scored, feature_cols))
    return rows


def acceleration_weeks_at_threshold(histories: dict, events: pd.DataFrame, threshold: float) -> pd.Series:
    out = {}
    for seller_id, hist in histories.items():
        above = hist.loc[hist["score"] >= threshold, "week"]
        if len(above) == 0:
            out[seller_id] = 0.0
            continue
        alarm_week = above.min()
        event_week = events.loc[seller_id, "event_week"]
        out[seller_id] = max((event_week - alarm_week).days / 7, 0.0)
    return pd.Series(out, index=events.index)


def run_sweep(
    fit: dict,
    features_df: pd.DataFrame,
    panel: pd.DataFrame,
    costs: dict,
    far_sweep: list[float] = FAR_SWEEP,
) -> pd.DataFrame:
    reserve_pct = costs["reserve_pct"]
    wc_rate = costs["working_capital_cost_weekly_rate"]
    benefit_capture = costs["benefit_capture_rate"]

    weekly_gmv = per_seller_weekly_gmv(panel)

    histories, events = score_event_histories(fit, features_df)
    event_gmv = events.index.to_series().map(weekly_gmv)

    censored_rows = score_censored_rows(fit, features_df)
    censored_rows = censored_rows.assign(weekly_gmv=censored_rows["seller_id"].map(weekly_gmv))
    neg_scores = censored_rows["score"].to_numpy()

    total_test_merchant_weeks = fit["drift"]["test_rows"]

    rows_out = []
    for far in far_sweep:
        threshold = float(np.quantile(neg_scores, 1 - far))

        acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)
        benefit_total = float((acc_weeks * event_gmv * reserve_pct * benefit_capture).sum())

        flagged = censored_rows["score"] >= threshold
        cost_total = float((censored_rows.loc[flagged, "weekly_gmv"] * reserve_pct * wc_rate).sum())

        net_delta = cost_total - benefit_total
        per_1000 = net_delta / total_test_merchant_weeks * 1000

        seller_far = (
            flagged.groupby(censored_rows["seller_id"]).any().mean() if flagged.any() else 0.0
        )

        rows_out.append(
            {
                "false_alarm_rate": far,
                "threshold": threshold,
                "n_events_accelerated": int((acc_weeks > 0).sum()),
                "n_events_total": len(events),
                "benefit_total_reais": benefit_total,
                "cost_total_reais": cost_total,
                "net_delta_cost_reais": net_delta,
                "net_delta_cost_per_1000_merchant_weeks_reais": per_1000,
                "seller_level_false_alarm_rate": float(seller_far),
            }
        )

    return pd.DataFrame(rows_out)


def main() -> None:
    costs = load_costs()
    print(f"cost parameters: {costs}\n")

    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)
    fit = run_for_n(panel, features_df, PRIMARY_N)

    sweep = run_sweep(fit, features_df, panel, costs)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)
    print(sweep.to_string(index=False))

    any_win = (sweep["net_delta_cost_per_1000_merchant_weeks_reais"] < 0).any()
    print()
    if any_win:
        best = sweep.loc[sweep["net_delta_cost_per_1000_merchant_weeks_reais"].idxmin()]
        print(
            f"HEADLINE: model-based policy beats the naive N=8 rule at FAR={best['false_alarm_rate']:.0%}, "
            f"saving R${-best['net_delta_cost_per_1000_merchant_weeks_reais']:.2f} per 1,000 merchant-weeks."
        )
    else:
        worst = sweep.loc[sweep["net_delta_cost_per_1000_merchant_weeks_reais"].idxmin()]
        print(
            "HEADLINE: no false-alarm rate in [1%, 10%] beats the naive N=8 rule. "
            f"Best case (FAR={worst['false_alarm_rate']:.0%}) still costs "
            f"R${worst['net_delta_cost_per_1000_merchant_weeks_reais']:.2f} MORE per 1,000 merchant-weeks "
            "than doing nothing but the rule."
        )

    out_path = Path("figures") / "phase3_far_sweep.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sweep.to_json(out_path, orient="records", indent=2)
    sweep.to_csv(Path("figures") / "phase3_far_sweep.csv", index=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
