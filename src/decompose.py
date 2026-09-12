"""
Separate the fixed (capacity) component from the variable (energy) component of
BPDB's payments to each producer.

BPDB discloses, per producer per year, units purchased E and amount paid P, but
not the split between the two components of the tariff. Under a standard
two-part PPA the payment is

    P_t = CP_t + v_t * E_t

where CP is the capacity payment owed regardless of dispatch and v is the
energy rate per kWh. With two years of observations on the same plant, and
holding CP and v fixed across them, the system is exactly identified:

    v  = (P_1 - P_0) / (E_1 - E_0)
    CP = P_1 - v * E_1

The assumption is strong. Fuel prices and the exchange rate both moved between
FY2023-24 and FY2024-25, so v is not in fact constant, and any plant whose
solved v or CP comes out negative is telling us exactly that. Those cases are
flagged rather than reported. With the five annual reports from FY2020-21
onward the same identity becomes a short panel per plant,

    P_it = CP_i + v_i * E_it + b_i * fuel_t + c_i * fx_t + e_it

which is the estimator this module is a placeholder for.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

MIN_GENERATION_GAP_KWH = 1_000_000  # below this the solve is numerically unstable


def two_point(E1: float, E0: float, P1: float, P0: float) -> tuple[float, float]:
    v = (P1 - P0) / (E1 - E0)
    return v, P1 - v * E1


def run(purchases_csv: Path) -> list[dict]:
    out: list[dict] = []
    for r in csv.DictReader(purchases_csv.open(encoding="utf-8")):
        if r["purchase_class"] != "ipp":
            continue
        E1, E0 = float(r["kwh_cy"]), float(r["kwh_py"])
        P1, P0 = float(r["bdt_cy"]), float(r["bdt_py"])

        if E1 == 0 and P1 > 0:
            out.append({
                "producer": r["producer"], "method": "observed_zero_dispatch",
                "energy_rate_bdt_kwh": "", "fixed_payment_bdt": P1,
                "fixed_share": 1.0, "flag": "",
            })
            continue

        if E1 == 0 or E0 == 0 or abs(E1 - E0) < MIN_GENERATION_GAP_KWH:
            out.append({
                "producer": r["producer"], "method": "two_point",
                "energy_rate_bdt_kwh": "", "fixed_payment_bdt": "",
                "fixed_share": "", "flag": "insufficient_variation",
            })
            continue

        v, cp = two_point(E1, E0, P1, P0)
        flag = "" if (v > 0 and cp > 0) else "sign_implausible_needs_panel"
        out.append({
            "producer": r["producer"], "method": "two_point",
            "energy_rate_bdt_kwh": round(v, 4),
            "fixed_payment_bdt": round(cp, 0),
            "fixed_share": round(cp / P1, 4) if P1 else "",
            "flag": flag,
        })
    return out


def main() -> None:
    src = PROC / "bpdb_purchases_FY2024-25.csv"
    rows = run(src)
    dest = PROC / "capacity_decomposition_FY2024-25.csv"
    fields = ["producer", "method", "energy_rate_bdt_kwh",
              "fixed_payment_bdt", "fixed_share", "flag"]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    good = [r for r in rows if r["flag"] == "" and r["method"] == "two_point"]
    total = sum(float(r["fixed_payment_bdt"]) for r in good)
    print(f"{len(rows)} producers -> {dest.relative_to(ROOT)}")
    print(f"  usable two-point decompositions : {len(good)}")
    print(f"  implied fixed payments          : Tk {total/1e7:,.0f} crore")
    print(f"  flagged for the panel           : "
          f"{sum(1 for r in rows if r['flag'] == 'sign_implausible_needs_panel')}")


if __name__ == "__main__":
    main()
