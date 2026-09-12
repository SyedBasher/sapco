"""
Estimate the two-part tariff with fuel-year controls.

The per-plant regression in build_panel.py forces one energy rate to stand for
six years, so any plant whose fuel cost or exchange-rate exposure moved ends up
with an implausible fit. The fix is to let the energy rate vary by fuel and
year while holding the capacity payment fixed to the plant:

    P_it = CP_i + v_{f(i),t} * E_it + e_it

CP_i enters as a plant-specific intercept and v_{f,t} as the coefficient on
generation interacted with that plant's fuel and the fiscal year. Fuel prices
and the taka rate move every plant of a given fuel in the same direction in a
given year, so a common fuel-year rate absorbs them; what is left in the
intercept is the part of the payment that does not respond to dispatch.

The estimator is ordinary least squares by way of a least-squares solve on the
stacked design matrix. Standard errors are not reported: with six annual
observations per plant they would be optimistic, and the quantity of interest
here is the fitted intercept rather than a test against zero.
"""

from __future__ import annotations

import csv
import re
import difflib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

FY_ORDER = ["FY2019-20", "FY2020-21", "FY2021-22",
            "FY2022-23", "FY2023-24", "FY2024-25"]

STOP = {"ltd", "limited", "power", "plant", "company", "co", "pvt", "private",
        "generation", "energy", "mw", "pp", "ps", "ppl", "unit", "the", "and",
        "bangladesh", "lid", "lttd", "gen", "corp", "services", "service",
        "infrastructure", "infracture", "solar", "park", "int", "ltdd"}


def tokens(name: str) -> set[str]:
    s = re.sub(r"[^\w\s]", " ", str(name).lower())
    s = re.sub(r"\d+", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in STOP}


def match_fuel(producers: list[str], fleet: list[dict]) -> dict[str, str]:
    """Map each purchase-note producer to a fuel using the fleet inventory."""
    fleet_tok = [(tokens(f["plant_name"]), f["fuel"], f["plant_name"])
                 for f in fleet if f["fuel"]]
    out: dict[str, str] = {}
    for p in producers:
        pt = tokens(p)
        if not pt:
            continue
        best, best_score = None, 0.0
        for ft, fuel, fname in fleet_tok:
            if not ft:
                continue
            inter = len(pt & ft)
            if inter == 0:
                continue
            score = inter / len(pt | ft)
            # break ties with whole-string similarity
            score += 0.25 * difflib.SequenceMatcher(
                None, p.lower(), fname.lower()).ratio()
            if score > best_score:
                best, best_score = fuel, score
        if best and best_score >= 0.45:
            out[p] = best
    return out


def main() -> None:
    panel = list(csv.DictReader((PROC / "purchase_panel.csv").open(encoding="utf-8")))
    panel = [r for r in panel if r["purchase_class"] == "ipp"]
    # Pool every year's inventory: a producer that stopped generating before
    # FY2024-25 appears only in an earlier one.
    fleet, seen = [], set()
    for path in sorted(PROC.glob("fleet_inventory_FY*.csv"), reverse=True):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            k = (r["plant_name"].strip().lower(), r["fuel"])
            if k in seen:
                continue
            seen.add(k)
            fleet.append(r)

    names = sorted({r["producer"] for r in panel})
    fuel_of = match_fuel(names, fleet)
    print(f"producers in IPP panel      : {len(names)}")
    print(f"matched to a fuel            : {len(fuel_of)}")

    rows = [r for r in panel if r["producer"] in fuel_of
            and r["fy"] in FY_ORDER and float(r["bdt"]) > 0]
    # keep plants with enough within-plant variation to identify an intercept
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["producer"]] = counts.get(r["producer"], 0) + 1
    rows = [r for r in rows if counts[r["producer"]] >= 4]

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

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))

    print(f"observations                 : {n}")
    print(f"plants estimated             : {len(plants)}")
    print(f"fuel-year rates estimated    : {len(fuel_years)}")
    print(f"overall R^2                  : {r2:.4f}")

    ests = []
    for p in plants:
        cp = beta[p_idx[p]]
        ests.append({
            "producer": p,
            "fuel": fuel_of[p],
            "n_obs": counts[p],
            "fixed_payment_bdt": round(cp, 0),
            "flag": "" if cp > 0 else "negative_intercept",
        })
    ests.sort(key=lambda r: -r["fixed_payment_bdt"])
    with (PROC / "panel_fixed_payments.csv").open("w", newline="",
                                                  encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ests[0].keys()))
        w.writeheader()
        w.writerows(ests)

    rates = [{"fuel": f, "fy": t, "energy_rate_bdt_kwh": round(beta[fy_idx[(f, t)]], 4)}
             for f, t in fuel_years]
    with (PROC / "panel_energy_rates.csv").open("w", newline="",
                                                encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["fuel", "fy", "energy_rate_bdt_kwh"])
        w.writeheader()
        w.writerows(rates)

    good = [e for e in ests if e["flag"] == ""]
    print(f"positive fixed payments      : {len(good)} of {len(ests)}")
    print(f"implied fixed payments       : "
          f"Tk {sum(e['fixed_payment_bdt'] for e in good)/1e7:,.0f} crore")
    print()
    print("estimated energy rate by fuel and year (Tk/kWh):")
    fuels = sorted({f for f, _ in fuel_years})
    hdr = "  " + "fuel".ljust(14) + "".join(t[2:].rjust(9) for t in FY_ORDER)
    print(hdr)
    for f in fuels:
        line = "  " + f.ljust(14)
        for t in FY_ORDER:
            v = beta[fy_idx[(f, t)]] if (f, t) in fy_idx else None
            line += (f"{v:9.2f}" if v is not None else " " * 9)
        print(line)


if __name__ == "__main__":
    main()
