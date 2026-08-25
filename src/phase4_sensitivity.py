"""Phase 4, priority 1: sensitivity analysis on the two cost parameters
D16 flagged as load-bearing. Computed analytically from the existing
Phase 3 sweep (figures/phase3_far_sweep.csv) -- no need to rescore the
model, because both cost terms are exactly linear in their own parameter
and in reserve_pct (DECISIONS.md D16 already noted this; used directly
here):

  benefit_total(capture) = benefit_total_reais_base * capture   [base capture = 1.0]
  cost_total(wc_rate)    = cost_total_reais_base * (wc_rate / 0.0035)

So the breakeven value of either parameter, holding the other at its
config/costs.yaml default, is closed-form:

  breakeven_capture(FAR)  = cost_total_reais_base(FAR) / benefit_total_reais_base(FAR)
  breakeven_wc_rate(FAR)  = benefit_total_reais_base(FAR) * 0.0035 / cost_total_reais_base(FAR)

Two outputs:
1. A breakeven table across the full 1%-10% FAR sweep, for both
   parameters (weekly and annualised for the working-capital rate, since
   annualised is the more interpretable unit for judging plausibility).
2. A tornado plot at FAR=5% (the sweep's midpoint, used as the
   representative operating point) -- net delta cost per 1,000
   merchant-weeks at the low/high bound of each parameter's plausible
   range, holding the other two at their config/costs.yaml defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml

SWEEP_PATH = Path("figures/phase3_far_sweep.csv")
COSTS_PATH = Path("config/costs.yaml")
TORNADO_FAR = 0.05  # midpoint of the swept range, used as the representative operating point

# Plausible ranges for the tornado plot, chosen independently of the
# breakeven table (i.e. NOT picked to land on one side or the other of
# breakeven -- these are meant to bound "realistic," full stop).
PARAM_RANGES = {
    "benefit_capture_rate": (0.10, 1.00),
    # 0.10 = a deliberately pessimistic case: only a tenth of extra reserve
    # actually offsets the eventual loss. 1.00 = the config default and
    # structurally the natural ceiling here -- the reserve is money the
    # aggregator already withheld from the merchant's own settlements, not
    # a debt that needs collecting, so near-full capture is the more
    # realistic end of this range, not merely optimistic (see D17).
    "working_capital_cost_weekly_rate": (0.0019, 0.0115),
    # ~10%-60% annualised cost of capital. Config default (0.0035) is
    # ~18% annualised; 60% is already a high-end small-business/emerging-
    # market financing rate, not a central estimate.
    "reserve_pct": (0.10, 0.30),
    # Typical rolling-reserve range (costs.yaml comment). Scales both
    # benefit and cost by the same factor (D16) -- included for
    # completeness, not because it can flip the sign.
}


def load_sweep() -> pd.DataFrame:
    return pd.read_csv(SWEEP_PATH)


def load_costs() -> dict:
    with open(COSTS_PATH) as f:
        return yaml.safe_load(f)


def breakeven_table(sweep: pd.DataFrame, base_costs: dict) -> pd.DataFrame:
    base_wc = base_costs["working_capital_cost_weekly_rate"]
    out = sweep[["false_alarm_rate", "benefit_total_reais", "cost_total_reais"]].copy()
    out["breakeven_benefit_capture_rate"] = out["cost_total_reais"] / out["benefit_total_reais"]
    out["breakeven_wc_rate_weekly"] = out["benefit_total_reais"] * base_wc / out["cost_total_reais"]
    out["breakeven_wc_rate_annualised_pct"] = out["breakeven_wc_rate_weekly"] * 52 * 100
    return out


def net_delta_at(
    far_row: pd.Series, base_costs: dict, capture: float, wc_rate: float, reserve_pct: float
) -> float:
    """Net delta cost per 1,000 merchant-weeks at arbitrary parameter
    values, derived by rescaling the base sweep row (linear in each
    parameter, see module docstring)."""
    base_reserve = base_costs["reserve_pct"]
    base_wc = base_costs["working_capital_cost_weekly_rate"]
    base_capture = base_costs["benefit_capture_rate"]

    reserve_scale = reserve_pct / base_reserve
    benefit = far_row["benefit_total_reais"] * (capture / base_capture) * reserve_scale
    cost = far_row["cost_total_reais"] * (wc_rate / base_wc) * reserve_scale

    net_delta = cost - benefit
    # per-1000-merchant-weeks scale factor is constant across parameter
    # changes -- recover it from the base row's own ratio.
    scale = far_row["net_delta_cost_per_1000_merchant_weeks_reais"] / far_row["net_delta_cost_reais"]
    return net_delta * scale


def tornado_data(sweep: pd.DataFrame, base_costs: dict, far: float) -> list[dict]:
    far_row = sweep.loc[sweep["false_alarm_rate"].sub(far).abs().idxmin()]
    base_net = net_delta_at(
        far_row,
        base_costs,
        base_costs["benefit_capture_rate"],
        base_costs["working_capital_cost_weekly_rate"],
        base_costs["reserve_pct"],
    )

    rows = []
    for param, (lo, hi) in PARAM_RANGES.items():
        kwargs_lo = {
            "capture": base_costs["benefit_capture_rate"],
            "wc_rate": base_costs["working_capital_cost_weekly_rate"],
            "reserve_pct": base_costs["reserve_pct"],
        }
        kwargs_hi = dict(kwargs_lo)
        param_to_kwarg = {
            "benefit_capture_rate": "capture",
            "working_capital_cost_weekly_rate": "wc_rate",
            "reserve_pct": "reserve_pct",
        }
        key = param_to_kwarg[param]
        kwargs_lo[key] = lo
        kwargs_hi[key] = hi

        net_lo = net_delta_at(far_row, base_costs, **kwargs_lo)
        net_hi = net_delta_at(far_row, base_costs, **kwargs_hi)
        rows.append(
            {
                "parameter": param,
                "low_value": lo,
                "high_value": hi,
                "net_delta_at_low": net_lo,
                "net_delta_at_high": net_hi,
                "swing": abs(net_hi - net_lo),
            }
        )
    rows.sort(key=lambda r: -r["swing"])
    return rows, base_net, far_row["false_alarm_rate"]


def plot_tornado(rows: list[dict], base_net: float, far: float) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    labels = [r["parameter"] for r in rows]
    y = range(len(rows))

    for i, r in enumerate(rows):
        lo, hi = sorted([r["net_delta_at_low"], r["net_delta_at_high"]])
        ax.barh(i, hi - lo, left=lo, color="#4C72B0", alpha=0.8, height=0.5)
        ax.text(lo, i, f" {lo:.1f}", va="center", ha="right", fontsize=8)
        ax.text(hi, i, f" {hi:.1f}", va="center", ha="left", fontsize=8)

    ax.axvline(base_net, color="black", linestyle="-", linewidth=1, label=f"base case ({base_net:.1f})")
    ax.axvline(0, color="red", linestyle="--", linewidth=1, label="breakeven with N=8 rule")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.set_xlabel("net delta cost per 1,000 merchant-weeks (R$)\n(negative = model policy still wins)")
    ax.set_title(f"Tornado: sensitivity of the FAR={far:.0%} result to each cost parameter")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig("figures/phase4_tornado.png", dpi=150)
    print("wrote figures/phase4_tornado.png")


def main() -> None:
    sweep = load_sweep()
    costs = load_costs()

    be = breakeven_table(sweep, costs)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)
    print("=== breakeven table (holding the OTHER parameter at its config/costs.yaml default) ===")
    print(be.to_string(index=False))
    be.to_csv("figures/phase4_breakeven.csv", index=False)

    ann_lo = be["breakeven_wc_rate_annualised_pct"].min()
    ann_hi = be["breakeven_wc_rate_annualised_pct"].max()
    print(
        f"\nplausibility check: breakeven working-capital rate ranges "
        f"{ann_lo:.0f}%-{ann_hi:.0f}% annualised across the sweep "
        f"(the config default is ~18%); breakeven capture rate ranges "
        f"{be['breakeven_benefit_capture_rate'].min():.1%}-{be['breakeven_benefit_capture_rate'].max():.1%} "
        "(the config default is 100%)."
    )

    rows, base_net, far_used = tornado_data(sweep, costs, TORNADO_FAR)
    print(f"\n=== tornado at FAR={far_used:.0%}, base net delta = {base_net:.2f} R$/1000 merchant-weeks ===")
    for r in rows:
        print(
            f"{r['parameter']:35s} [{r['low_value']}, {r['high_value']}] -> "
            f"net delta in [{min(r['net_delta_at_low'], r['net_delta_at_high']):.1f}, "
            f"{max(r['net_delta_at_low'], r['net_delta_at_high']):.1f}]  swing={r['swing']:.1f}"
        )
    plot_tornado(rows, base_net, far_used)

    out = {
        "breakeven_table": be.to_dict(orient="records"),
        "tornado_far": far_used,
        "tornado_base_net_delta": base_net,
        "tornado_rows": rows,
    }
    with open("figures/phase4_sensitivity.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote figures/phase4_sensitivity.json")


if __name__ == "__main__":
    main()
