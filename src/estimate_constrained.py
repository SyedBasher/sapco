"""
Estimate the two-part tariff subject to the ceilings the accounts impose.

The unconstrained fuel-year panel in estimate_panel.py is checked against the
sponsors' disclosures only after the fact. This module puts the same evidence
inside the estimator, solving

    min_{CP, v}  sum_it ( P_it - CP_i - v_{f(i),t} E_it )^2
    subject to   0 <= CP_i <= R^elec_i   for plants whose accounts disclose it
                 0 <= CP_i              for every other plant
                 0 <= v_{f,t}

as a bounded least-squares problem. The point is not to force five plants into
line. It is that those five bind the fuel-year energy rates they share with
everyone else, so five observed ceilings propagate to every plant burning the
same fuel. A constraint that binds is information; a constraint that does not
bind costs nothing.

Ceilings are the "Sales revenue - Electricity" line from Summit Power's note
31, which excludes the HFO fuel pass-through. A plant's capacity payment must
be paid out of that line, so it is an upper bound and not an estimate. Where
the ceiling applies to a single fiscal year but the intercept is fitted across
six, the ceiling is applied to the intercept directly, which is conservative
only if the capacity payment did not fall over the sample; that assumption is
recorded rather than assumed away.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.optimize import lsq_linear

from estimate_panel import FY_ORDER, match_fuel

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

MIN_OBS = 4


def load_ceilings() -> dict[str, float]:
    """Producer -> non-fuel revenue ceiling, from the validation table."""
    path = PROC / "validation_against_accounts.csv"
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r.get("summit_electricity_revenue_bdt"):
            out[r["producer"]] = float(r["summit_electricity_revenue_bdt"])
    return out


def load_panel() -> tuple[list[dict], dict[str, str]]:
    panel = [r for r in csv.DictReader(
        (PROC / "purchase_panel.csv").open(encoding="utf-8"))
        if r["purchase_class"] == "ipp"]

    fleet, seen = [], set()
    for path in sorted(PROC.glob("fleet_inventory_FY*.csv"), reverse=True):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            k = (r["plant_name"].strip().lower(), r["fuel"])
            if k in seen:
                continue
            seen.add(k)
            fleet.append(r)

    fuel_of = match_fuel(sorted({r["producer"] for r in panel}), fleet)
    return panel, fuel_of


def main() -> None:
    panel, fuel_of = load_panel()
    ceilings = load_ceilings()

    rows = [r for r in panel if r["producer"] in fuel_of
            and r["fy"] in FY_ORDER and float(r["bdt"]) > 0]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["producer"]] = counts.get(r["producer"], 0) + 1
    rows = [r for r in rows if counts[r["producer"]] >= MIN_OBS]

    plants = sorted({r["producer"] for r in rows})
    fuel_years = sorted({(fuel_of[r["producer"]], r["fy"]) for r in rows})
    p_idx = {p: i for i, p in enumerate(plants)}
    fy_idx = {k: len(plants) + i for i, k in enumerate(fuel_years)}

    n, k = len(rows), len(plants) + len(fuel_years)
    X = np.zeros((n, k))
    y = np.zeros(n)
    for i, r in enumerate(rows):
        X[i, p_idx[r["producer"]]] = 1.0
        X[i, fy_idx[(fuel_of[r["producer"]], r["fy"])]] = float(r["kwh"])
        y[i] = float(r["bdt"])

    lower = np.zeros(k)
    upper = np.full(k, np.inf)
    bound_count = 0
    for p, i in p_idx.items():
        if p in ceilings:
            upper[i] = ceilings[p]
            bound_count += 1

    fit = lsq_linear(X, y, bounds=(lower, upper), method="trf",
                     tol=1e-12, max_iter=500)
    beta = fit.x
    resid = y - X @ beta
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))

    # Which ceilings are actually binding, to within a tenth of a per cent.
    binding = [p for p in plants
               if p in ceilings and beta[p_idx[p]] >= 0.999 * ceilings[p]]

    print(f"observations                 : {n}")
    print(f"plants estimated             : {len(plants)}")
    print(f"ceilings imposed             : {bound_count}")
    print(f"ceilings binding at optimum  : {len(binding)}")
    print(f"overall R^2                  : {r2:.4f}")

    prev = {r["producer"]: float(r["fixed_payment_bdt"])
            for r in csv.DictReader(
                (PROC / "panel_fixed_payments.csv").open(encoding="utf-8"))}

    ests = []
    for p in plants:
        cp = beta[p_idx[p]]
        ests.append({
            "producer": p,
            "fuel": fuel_of[p],
            "n_obs": counts[p],
            "fixed_payment_bdt": round(cp, 0),
            "ceiling_bdt": round(ceilings[p], 0) if p in ceilings else "",
            "ceiling_binding": "Y" if p in binding else "",
            "unconstrained_bdt": round(prev.get(p, float("nan")), 0)
                                 if p in prev else "",
        })
    ests.sort(key=lambda r: -r["fixed_payment_bdt"])
    with (PROC / "constrained_fixed_payments.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ests[0].keys()))
        w.writeheader()
        w.writerows(ests)

    rates = [{"fuel": f, "fy": t,
              "energy_rate_bdt_kwh": round(beta[fy_idx[(f, t)]], 4)}
             for f, t in fuel_years]
    with (PROC / "constrained_energy_rates.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["fuel", "fy", "energy_rate_bdt_kwh"])
        w.writeheader()
        w.writerows(rates)

    total = sum(e["fixed_payment_bdt"] for e in ests)
    print(f"implied fixed payments       : Tk {total/1e7:,.0f} crore")
    print()
    print("energy rate by fuel and year (Tk/kWh), constrained:")
    fuels = sorted({f for f, _ in fuel_years})
    print("  " + "fuel".ljust(14) + "".join(t[2:].rjust(9) for t in FY_ORDER))
    for f in fuels:
        line = "  " + f.ljust(14)
        for t in FY_ORDER:
            line += (f"{beta[fy_idx[(f, t)]]:9.2f}"
                     if (f, t) in fy_idx else " " * 9)
        print(line)

    print()
    print("plants whose estimate moved most, Tk crore:")
    moved = [e for e in ests if e["unconstrained_bdt"] != ""]
    moved.sort(key=lambda e: -abs(e["fixed_payment_bdt"] - e["unconstrained_bdt"]))
    print(f"  {'producer':44s} {'before':>9s} {'after':>9s} {'ceiling':>9s}")
    for e in moved[:12]:
        ceil = (f"{e['ceiling_bdt']/1e7:,.0f}" if e["ceiling_bdt"] != "" else "-")
        print(f"  {e['producer'][:44]:44s} {e['unconstrained_bdt']/1e7:>9,.0f}"
              f" {e['fixed_payment_bdt']/1e7:>9,.0f} {ceil:>9s}")


if __name__ == "__main__":
    main()
