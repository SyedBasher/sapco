"""
Assemble the plant-level purchase panel and estimate the two-part tariff.

Each BPDB annual report states the current and prior fiscal year, so the four
machine-readable reports (FY2020-21, FY2022-23, FY2023-24, FY2024-25) between
them cover FY2019-20 to FY2024-25. Overlapping observations are deduplicated,
preferring the report in which the year is the CURRENT year, since that column
is the audited one.

For each producer with enough observations the payment identity

    P_it = CP_i + v_i * E_it + e_it

is estimated by ordinary least squares on that producer's own time series. The
intercept is the fixed payment owed irrespective of dispatch; the slope is the
effective energy rate. Both are nominal and therefore absorb fuel-price and
exchange-rate movement over the sample, which is why the fit statistics are
reported alongside and why a poor fit is a finding rather than a nuisance.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

FY_ORDER = ["FY2019-20", "FY2020-21", "FY2021-22",
            "FY2022-23", "FY2023-24", "FY2024-25"]


def prior_fy(fy: str) -> str:
    a = int(fy[2:6])
    return f"FY{a-1}-{str(a)[-2:]}"


def norm_producer(name: str) -> str:
    """Light normalisation so the same plant matches across reports."""
    s = name.strip().rstrip(".")
    s = re.sub(r"\s+", " ", s)
    s = s.replace("Bangladsh", "Bangladesh")
    s = re.sub(r"\bLtd\b\.?", "Ltd", s)
    s = re.sub(r"\bLimited\b", "Ltd", s)
    s = re.sub(r"\s*\(Pvt\.?\)\s*", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def load() -> dict[tuple[str, str], dict]:
    """Return {(producer_key, fy): observation}, audited column preferred."""
    obs: dict[tuple[str, str], dict] = {}
    for path in sorted(PROC.glob("bpdb_purchases_FY*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            key = norm_producer(r["producer"])
            fy_cy = r["fy"]
            for fy, kwh, bdt, is_current in (
                (fy_cy, r["kwh_cy"], r["bdt_cy"], True),
                (prior_fy(fy_cy), r["kwh_py"], r["bdt_py"], False),
            ):
                k = (key, fy)
                if k in obs and not is_current:
                    continue
                obs[k] = {
                    "producer_key": key,
                    "producer": r["producer"].strip(),
                    "purchase_class": r["purchase_class"],
                    "fy": fy,
                    "kwh": float(kwh),
                    "bdt": float(bdt),
                    "audited_column": "Y" if is_current else "",
                    "source_doc": r["source_doc"],
                }
    return obs


def ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, r_squared) for a simple regression."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return float("nan"), float("nan"), float("nan")
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    return slope, intercept, r2


def main() -> None:
    obs = load()

    panel = sorted(
        obs.values(),
        key=lambda r: (r["producer_key"], FY_ORDER.index(r["fy"])
                       if r["fy"] in FY_ORDER else 99),
    )
    dest = PROC / "purchase_panel.csv"
    fields = ["producer_key", "producer", "purchase_class", "fy",
              "kwh", "bdt", "audited_column", "source_doc"]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(panel)

    by_plant: dict[str, list[dict]] = {}
    for r in panel:
        by_plant.setdefault(r["producer_key"], []).append(r)

    ests = []
    for key, rows in by_plant.items():
        pts = [(r["kwh"], r["bdt"]) for r in rows if r["kwh"] > 0 or r["bdt"] > 0]
        if len(pts) < 3:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        slope, intercept, r2 = ols(xs, ys)
        if slope != slope:
            continue
        ests.append({
            "producer": rows[-1]["producer"],
            "purchase_class": rows[-1]["purchase_class"],
            "n_obs": len(pts),
            "energy_rate_bdt_kwh": round(slope, 4),
            "fixed_payment_bdt": round(intercept, 0),
            "r_squared": round(r2, 4),
            "flag": "" if (slope > 0 and intercept > 0)
                    else "sign_implausible",
        })

    ests.sort(key=lambda r: -r["fixed_payment_bdt"])
    dest2 = PROC / "two_part_tariff_estimates.csv"
    with dest2.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ests[0].keys()))
        w.writeheader()
        w.writerows(ests)

    good = [e for e in ests if e["flag"] == ""]
    print(f"panel: {len(panel)} observations, {len(by_plant)} producers"
          f" -> {dest.relative_to(ROOT)}")
    print(f"estimated: {len(ests)} producers with 3+ observations"
          f" -> {dest2.relative_to(ROOT)}")
    print(f"  sign-plausible : {len(good)}")
    print(f"  median R^2     : "
          f"{sorted(e['r_squared'] for e in good)[len(good)//2]:.3f}")
    print(f"  implied fixed payments (plausible only): "
          f"Tk {sum(e['fixed_payment_bdt'] for e in good)/1e7:,.0f} crore")


if __name__ == "__main__":
    main()
