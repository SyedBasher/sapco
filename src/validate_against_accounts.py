"""
Validate the estimated fixed payments against the sponsors' own audited accounts.

Summit Power's note 31 reports revenue plant by plant, separated into "Sales
revenue - Electricity" and "Sales revenue - HFO", with the IFRS 16
straight-lining adjustment shown as a third line. The HFO line is the fuel
pass-through. Whatever the capacity payment is, it must come out of the
electricity line, so that line is a hard ceiling:

    CP_i <= R^elec_i

That is a restriction the data can impose from outside the estimator, which is
what the purchase panel alone could not supply. It also gives an independent
check on the BPDB purchase panel itself, since Summit's total revenue per plant
and BPDB's recorded payment to that plant are two separate accounts of the
same transaction.

Figures below are keyed verbatim from Summit Power Limited, Annual Report
2024-25, note 31 (consolidated column, year to 30 June 2025).
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

# plant -> (electricity revenue, HFO revenue, IFRS 16 straight-lining impact)
SUMMIT_FY2025 = {
    "Rupatoli Power Plant": (1_916_040_717, 1_770_512_356, -32_957_422),
    "Madanganj Power Plant (Unit-2)": (1_036_373_456, 2_500_269_425, -5_545_798),
    "Kodda Power Plant (Unit-1)": (3_204_482_641, 10_832_405_837, -523_165_796),
    "Kodda Power Plant (Unit-2)": (5_887_842_544, 9_687_324_838, 412_683_030),
    "Jangalia Power Plant": (70_406_328, 0, 0),
}

# BPDB purchase-note producer -> Summit plant, matched on capacity, location
# and revenue level.
CROSSWALK = {
    "Summit Barishal Power Ltd.": "Rupatoli Power Plant",
    "Summit Narayangonj Power Unit II Ltd.": "Madanganj Power Plant (Unit-2)",
    "ACE Alliance Power Ltd. (149MW) (Summit Gazipur)": "Kodda Power Plant (Unit-1)",
    "Summit Gazipur II Power Ltd. - Kodda (300MW)": "Kodda Power Plant (Unit-2)",
    "Summit Purbachal Power Ltd.-Jangalia": "Jangalia Power Plant",
}


def load(name: str, value: str, require_clean: bool = True) -> dict[str, float]:
    out = {}
    for r in csv.DictReader((PROC / name).open(encoding="utf-8")):
        if require_clean and r.get("flag"):
            continue
        if r.get(value):
            out[r["producer"]] = float(r[value])
    return out


def main() -> None:
    bpdb = load("bpdb_purchases_FY2024-25.csv", "bdt_cy", require_clean=False)
    per_plant = load("two_part_tariff_estimates.csv", "fixed_payment_bdt")
    panel = load("panel_fixed_payments.csv", "fixed_payment_bdt")

    rows = []
    for producer, plant in CROSSWALK.items():
        elec, hfo, ifrs = SUMMIT_FY2025[plant]
        total = elec + hfo + ifrs
        paid = bpdb.get(producer)
        rows.append({
            "plant": plant,
            "producer": producer,
            "bpdb_paid_bdt": paid if paid is not None else "",
            "summit_total_revenue_bdt": total,
            "summit_electricity_revenue_bdt": elec,
            "reconciliation_gap_pct": (
                round((paid - total) / total * 100, 1)
                if paid is not None and total else ""
            ),
            "per_plant_estimate_bdt": per_plant.get(producer, ""),
            "panel_estimate_bdt": panel.get(producer, ""),
            "per_plant_breaches_ceiling": (
                "Y" if per_plant.get(producer, 0) > elec else ""
            ),
            "panel_breaches_ceiling": (
                "Y" if panel.get(producer, 0) > elec else ""
            ),
        })

    dest = PROC / "validation_against_accounts.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    cr = lambda x: x / 1e7
    print("Reconciliation of BPDB payments against Summit's own revenue, Tk crore")
    for r in rows:
        if r["bpdb_paid_bdt"] == "":
            continue
        print(f"  {r['plant'][:32]:32s} BPDB {cr(r['bpdb_paid_bdt']):>8,.0f}"
              f"   Summit {cr(r['summit_total_revenue_bdt']):>8,.0f}"
              f"   gap {r['reconciliation_gap_pct']:>6}%")

    print()
    print("Ceiling test: estimated fixed payment vs non-fuel revenue, Tk crore")
    breaches = {"per_plant": 0, "panel": 0, "testable": 0}
    for r in rows:
        if not r["per_plant_estimate_bdt"] and not r["panel_estimate_bdt"]:
            continue
        breaches["testable"] += 1
        breaches["per_plant"] += r["per_plant_breaches_ceiling"] == "Y"
        breaches["panel"] += r["panel_breaches_ceiling"] == "Y"
        pp = r["per_plant_estimate_bdt"]
        pa = r["panel_estimate_bdt"]
        print(f"  {r['plant'][:32]:32s} ceiling {cr(r['summit_electricity_revenue_bdt']):>6,.0f}"
              f"   per-plant {(f'{cr(pp):,.0f}' if pp else '-'):>6s}"
              f"{' BREACH' if r['per_plant_breaches_ceiling'] else '      '}"
              f"   panel {(f'{cr(pa):,.0f}' if pa else '-'):>6s}"
              f"{' BREACH' if r['panel_breaches_ceiling'] else ''}")

    print()
    print(f"  testable plants          : {breaches['testable']}")
    print(f"  per-plant specification  : {breaches['per_plant']} breaches")
    print(f"  fuel-controlled panel    : {breaches['panel']} breaches")
    print(f"\nwrote {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
