"""Presentation figures only -- no new analysis. Every number here is
already computed and reported in DECISIONS.md (D12-D14, D16, D18) and the
existing figures/*.json outputs; this script re-derives the same
deterministic per-event breakdown needed for the histograms (calling the
already-fitted model's scoring functions, not refitting anything) and
composes three README-ready figures from it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt

from features import build_features
from model import PRIMARY_N, TEST_CUTOFF, predict, run_for_n, transform_features
from panel import build_panel
from phase2_acceleration_vs_rule import compute_threshold
from phase4_calibrated_sweep import fit_calibrator
from policy import acceleration_weeks_at_threshold, score_event_histories

FIG_DIR = Path("figures")

# --- numbers already established (DECISIONS.md D12) --------------------
APPARENT_AUC_RANGE = (0.892, 0.969)  # N=12 / N=4 at-event-week test AUC; primary N=8 = 0.914

CONFIRM_ANCHORED = {
    1: {"auc": 0.909, "mean_pos": 0.0540, "mean_neg": 0.0099},
    2: {"auc": 0.876, "mean_pos": 0.0366, "mean_neg": 0.0099},
    4: {"auc": 0.804, "mean_pos": 0.0071, "mean_neg": 0.0099},
    8: {"auc": 0.499, "mean_pos": 0.0001, "mean_neg": 0.0099},
}
LAST_ORDER_ANCHORED = {
    1: {"auc": 0.584},
    2: {"auc": 0.586},
    4: {"auc": 0.534},
    8: {"auc": 0.555},
}

ABLATION = {
    "levels only\n(12 features)": {"train": 0.702, "test": 0.682},
    "+ trend\n(28 features)": {"train": 0.712, "test": 0.678},
    "+ trend + accel\n(37 features,\nfull model)": {"train": 0.714, "test": 0.678},
}

PRIMARY_FAR = 0.05


def fig1_lead_time_waterfall() -> None:
    fig = plt.figure(figsize=(9, 12))
    gs = gridspec.GridSpec(3, 1, height_ratios=[1, 1.3, 1.3], hspace=0.55)

    # --- Stage 1: apparent performance ---
    ax1 = fig.add_subplot(gs[0])
    lo, hi = APPARENT_AUC_RANGE
    ax1.barh([0], [hi - lo], left=lo, height=0.35, color="#C44E52")
    ax1.set_xlim(0.4, 1.0)
    ax1.set_ylim(-1.1, 0.9)
    ax1.set_yticks([])
    ax1.axvline(0.5, color="black", linestyle=":", linewidth=1)
    ax1.text(0.5, 0.7, "chance", fontsize=8, ha="center", transform=ax1.get_xaxis_transform())
    ax1.set_title(
        "STAGE 1 — apparent test performance (at-event-week, D12)", loc="left", fontsize=11, fontweight="bold"
    )
    ax1.annotate(
        f"AUC {lo:.2f}–{hi:.2f} across N=4/8/12",
        xy=((lo + hi) / 2, 0.175), xytext=((lo + hi) / 2, 0.65),
        ha="center", va="bottom", fontsize=10, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#333333", lw=1),
    )
    ax1.text(
        0.4, -0.95,
        "A naive read stops here: this looks like strong, useful prediction.",
        ha="left", fontsize=9, style="italic", color="#555555",
    )

    # --- Stage 2: confirmation-anchored lead-time audit ---
    ax2 = fig.add_subplot(gs[1])
    ks = sorted(CONFIRM_ANCHORED)
    aucs = [CONFIRM_ANCHORED[k]["auc"] for k in ks]
    ax2.plot(ks, aucs, marker="o", markersize=9, color="#C44E52", linewidth=2)
    ax2.axhline(0.5, color="black", linestyle=":", linewidth=1)
    ax2.set_xticks(ks)
    ax2.set_ylim(0.4, 1.0)
    ax2.set_xlabel("k = weeks before EVENT CONFIRMATION (last_active_week + 8)")
    ax2.set_ylabel("AUC")
    ax2.set_title(
        "STAGE 2 — lead-time audit, confirmation-anchored (D13)", loc="left", fontsize=11, fontweight="bold"
    )
    for k in ks:
        ax2.annotate(
            f"{CONFIRM_ANCHORED[k]['auc']:.3f}", (k, CONFIRM_ANCHORED[k]["auc"]),
            textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9,
        )
    ax2.annotate(
        "k=8 lands exactly on the seller's LAST ACTIVE WEEK.\n"
        "Soon-to-fail sellers scored BELOW censored ones here:\n"
        "mean score 0.0001 vs. 0.0099 for still-healthy sellers.\n"
        "→ not predicting distress -- recognising silence\n   that has already begun.",
        xy=(8, 0.499), xytext=(3.2, 0.46),
        fontsize=8.5, color="#333333",
        arrowprops=dict(arrowstyle="->", color="#C44E52", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.4", fc="#FFF3F3", ec="#C44E52", lw=0.8),
    )

    # --- Stage 3: last-order-anchored, corrected ---
    ax3 = fig.add_subplot(gs[2])
    ks3 = sorted(LAST_ORDER_ANCHORED)
    aucs3 = [LAST_ORDER_ANCHORED[k]["auc"] for k in ks3]
    ax3.plot(ks3, aucs3, marker="s", markersize=9, color="#4C72B0", linewidth=2)
    ax3.axhline(0.5, color="black", linestyle=":", linewidth=1)
    ax3.set_xticks(ks3)
    ax3.set_ylim(0.4, 1.0)
    ax3.set_xlabel("k = weeks before the seller's ACTUAL LAST ORDER (still trading)")
    ax3.set_ylabel("AUC")
    ax3.set_title(
        "STAGE 3 — anchor corrected: genuinely before the seller stops (D14 §1)",
        loc="left", fontsize=11, fontweight="bold",
    )
    for k in ks3:
        ax3.annotate(
            f"{LAST_ORDER_ANCHORED[k]['auc']:.3f}", (k, LAST_ORDER_ANCHORED[k]["auc"]),
            textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9,
        )
    ax3.annotate(
        "Stage 2's k was measured from CONFIRMATION\n"
        "(8 weeks after the last order), not from the last\n"
        "order itself -- every k<8 there was already INSIDE\n"
        "the silence period. This is the honest test.\n"
        "0.53–0.59 at every horizon: still near chance.",
        xy=(4.5, 0.55), xytext=(4.7, 0.75),
        fontsize=8.5, color="#333333",
        arrowprops=dict(arrowstyle="->", color="#4C72B0", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.4", fc="#F0F4FA", ec="#4C72B0", lw=0.8),
    )

    fig.suptitle(
        "Does the model predict distress in advance?\nA lead-time audit, three stages, top to bottom",
        fontsize=13, y=0.99,
    )
    fig.text(
        0.5, 0.005,
        "Conclusion: no evidence of genuine multi-week advance warning survives. See Section 3 / DECISIONS.md D13-D14.",
        ha="center", fontsize=10, fontweight="bold",
    )
    fig.savefig(FIG_DIR / "readme_lead_time_waterfall.png", dpi=150, bbox_inches="tight")
    print(f"wrote {FIG_DIR / 'readme_lead_time_waterfall.png'}")


def fig2_ablation() -> None:
    fig, ax = plt.subplots(figsize=(8, 7))
    tiers = list(ABLATION.keys())
    x = np.arange(len(tiers))
    train_vals = [ABLATION[t]["train"] for t in tiers]
    test_vals = [ABLATION[t]["test"] for t in tiers]

    ax.bar(x - 0.18, train_vals, width=0.36, label="train AUC", color="#8C8C8C")
    ax.bar(x + 0.18, test_vals, width=0.36, label="test AUC", color="#C44E52")
    for xi, v in zip(x - 0.18, train_vals):
        ax.text(xi, v + 0.008, f"{v:.3f}", ha="center", fontsize=10)
    for xi, v in zip(x + 0.18, test_vals):
        ax.text(xi, v + 0.008, f"{v:.3f}", ha="center", fontsize=10, fontweight="bold")
    ax.axhline(0.5, color="black", linestyle=":", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(tiers)
    ax.set_ylabel("AUC (event-within-8-weeks, actively-trading rows only)")
    ax.set_ylim(0.4, 0.8)
    ax.set_title("The ablation: does trend/acceleration beat levels?", fontsize=13)
    ax.legend(loc="upper left")

    caption = (
        "Test AUC is flat to slightly down as trend and acceleration are added (0.682→0.678→0.678)\n"
        "while train AUC rises (0.702→0.714) -- added fitting capacity, no added generalising signal.\n"
        "This hypothesis was stated in BRIEF.md before any code in this repository was written --\n"
        "no commit in this repo's history predates it (BRIEF.md itself is gitignored by request,\n"
        "not part of the tracked deliverable). It was tested directly here, and rejected."
    )
    fig.tight_layout(rect=(0, 0.20, 1, 1))
    fig.text(0.5, 0.02, caption, ha="center", va="bottom", fontsize=9, style="italic")
    fig.savefig(FIG_DIR / "readme_ablation.png", dpi=150)
    print(f"wrote {FIG_DIR / 'readme_ablation.png'}")


def fig3_model_vs_rule() -> None:
    """Uses the CALIBRATED model (D21's established operating
    configuration), not raw scores -- matches the demo (app.py,
    figures/demo_event_acceleration.csv) exactly, so this figure and the
    demo can't drift into reporting different numbers for the same
    quantity (DECISIONS.md D26)."""
    raw_dir = Path("data/raw")
    panel = build_panel(raw_dir)
    features_df = build_features(raw_dir)
    fit = run_for_n(panel, features_df, PRIMARY_N)
    clf, scaler, feature_cols, freq_map, labels = (
        fit["_clf"], fit["_scaler"], fit["_feature_cols"], fit["_freq_map"], fit["_labels"]
    )
    calibrator = fit_calibrator(fit)

    censored = labels[~labels["event_B"]]
    neg_rows = features_df[
        features_df["seller_id"].isin(censored.index) & (features_df["week"] > TEST_CUTOFF)
    ].copy()
    neg_scored = transform_features(neg_rows, freq_map)
    neg_scores = calibrator.predict(predict(clf, scaler, neg_scored, feature_cols))
    threshold = compute_threshold(neg_scores, PRIMARY_FAR)

    histories, events = score_event_histories(fit, features_df)
    for hist in histories.values():
        if len(hist):
            hist["score"] = calibrator.predict(hist["score"].to_numpy())
    acc_weeks = acceleration_weeks_at_threshold(histories, events, threshold)

    rows = []
    for seller_id in events.index:
        hist = histories[seller_id]
        above = hist.loc[hist["score"] >= threshold, "week"]
        alarm_week = above.min() if len(above) else pd.NaT
        rows.append({"seller_id": seller_id, "model_alarm_week": alarm_week, "acceleration_weeks": acc_weeks.loc[seller_id]})
    acc_df = pd.DataFrame(rows)

    n_total = len(acc_df)
    never = int(acc_df["model_alarm_week"].isna().sum())
    earlier = acc_df[acc_df["model_alarm_week"].notna() & (acc_df["acceleration_weeks"] > 0)]
    ties = n_total - never - len(earlier)

    fig = plt.figure(figsize=(10, 8))
    gs = gridspec.GridSpec(2, 1, height_ratios=[1, 1.6], hspace=0.45)

    # --- prominent composition bar ---
    ax1 = fig.add_subplot(gs[0])
    segs = [
        ("gets ZERO benefit\nover the naive rule", never / n_total, "#C44E52"),
        ("ties the rule\n(0 weeks earlier)", ties / n_total, "#B0B0B0"),
        ("beats the rule", len(earlier) / n_total, "#55A868"),
    ]
    left = 0.0
    for label, frac, color in segs:
        ax1.barh([0], [frac], left=left, color=color, height=0.6)
        if frac > 0.03:
            ax1.text(
                left + frac / 2, 0, f"{frac:.0%}\n{label}", ha="center", va="center",
                fontsize=12 if frac > 0.5 else 9.5,
                fontweight="bold" if frac > 0.5 else "normal",
                color="white" if frac > 0.15 else "black",
            )
        left += frac
    ax1.set_xlim(0, 1)
    ax1.set_yticks([])
    ax1.set_xticks([])
    for spine in ax1.spines.values():
        spine.set_visible(False)
    ax1.set_title(
        f"At a 5% false-alarm rate (calibrated model), what happens to all {n_total} "
        "test-period cessations?",
        fontsize=13, loc="left", fontweight="bold",
    )

    # --- distribution for the ones that DO beat the rule ---
    ax2 = fig.add_subplot(gs[1])
    finite = earlier["acceleration_weeks"]
    ax2.hist(finite, bins=range(0, int(finite.max()) + 2), color="#55A868", edgecolor="white")
    median = finite.median()
    ax2.axvline(median, color="black", linestyle="--", linewidth=1.5, label=f"median = {median:.1f} weeks")
    ax2.set_xlabel(f"weeks earlier than the N=8 rule (for the {len(earlier) / n_total:.0%} that do beat it)")
    ax2.set_ylabel("events")
    ax2.set_title("For the minority that benefit: how much earlier?", fontsize=11, loc="left")
    ax2.legend()

    fig.suptitle("Model vs. the operational baseline (naive N=8 silence rule)", fontsize=14, y=1.0)
    fig.savefig(FIG_DIR / "readme_model_vs_rule.png", dpi=150, bbox_inches="tight")
    print(f"wrote {FIG_DIR / 'readme_model_vs_rule.png'}")
    print(
        f"never={never} ({never / n_total:.1%}), ties={ties} ({ties / n_total:.1%}), "
        f"earlier={len(earlier)} ({len(earlier) / n_total:.1%})"
    )


def main() -> None:
    fig1_lead_time_waterfall()
    fig2_ablation()
    fig3_model_vs_rule()


if __name__ == "__main__":
    main()
