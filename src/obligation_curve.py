"""
Build the forward capacity-payment obligation curve.

Each plant's annual fixed payment is estimated in estimate_constrained.py. To
turn a set of annual payments into a path, each needs a date at which it stops,
which is the PPA expiry:

    expiry_i = COD_i + T_i

Commissioning dates come from BPDB's own commissioning tables via the plant
spine, which reaches 2020, and from Global Energy Monitor's start year for
units commissioned after that. GEM gives a year rather than a date, which is
adequate for an annual path and is recorded as such. Tenure is not disclosed
for most plants, so it is taken from BPDB's
retirement schedule, where COD and retirement date appear together and the
realised contract length can simply be computed: a median of 15.0 years across
36 private plants, which matches the 15-year tenure Doreen discloses for its own
PPAs. Public plants in that table run a median of 34.7 years, but those are
asset lifetimes rather than contracts and no public plant enters this curve.

The obligation owed in year y is then

    O_y = sum_i CP_i * 1{ COD_i <= y < expiry_i }

with a part-year weight in the year of expiry. Nothing here is discounted; the
present value is a separate calculation in obligations.py, and the undiscounted
path is what a fiscal framework needs.

Every tenure that is assumed rather than disclosed is flagged in the output, and
plants whose commissioning date cannot be recovered are excluded and counted
rather than guessed at.
"""

from __future__ import annotations

import csv
import difflib
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

ASSUMED_TENURE_YEARS = 15.0   # median realised, private plants, BPDB schedule
HORIZON = 2045

STOP = {"ltd", "limited", "power", "plant", "company", "co", "pvt", "private",
        "generation", "energy", "mw", "pp", "ps", "ppl", "unit", "the", "and",
        "bangladesh", "lid", "lttd", "gen", "corp", "services", "service",
        "infrastructure", "infracture", "park", "int", "ltdd", "sponsor",
        "rental", "quick", "peaking", "conversion", "years"}


def tokens(name: str) -> set[str]:
    s = re.sub(r"[^\w\s]", " ", str(name).lower())
    s = re.sub(r"\d+", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in STOP}


def best_match(name: str, candidates: list[tuple[set[str], str, dict]]) -> dict | None:
    nt = tokens(name)
    if not nt:
        return None
    best, score_best = None, 0.0
    for ct, cname, row in candidates:
        if not ct or not (nt & ct):
            continue
        score = len(nt & ct) / len(nt | ct)
        score += 0.25 * difflib.SequenceMatcher(
            None, name.lower(), cname.lower()).ratio()
        if score > score_best:
            best, score_best = row, score
    return best if score_best >= 0.45 else None


def main() -> None:
    ests = list(csv.DictReader(
        (PROC / "constrained_fixed_payments.csv").open(encoding="utf-8")))
    spine = list(csv.DictReader(
        (PROC / "plant_master.csv").open(encoding="utf-8")))
    retire = {r["plant_name"]: r for r in csv.DictReader(
        (PROC / "retirement_schedule.csv").open(encoding="utf-8"))}
    gem = [r for r in csv.DictReader(
        (ROOT / "data" / "interim" / "gem_bangladesh.csv").open(encoding="utf-8"))
        if r.get("Start year")]

    spine_idx = [(tokens(r["plant_name"]), r["plant_name"], r)
                 for r in spine if r["commissioning_date"]]
    # Every plant with an estimated fixed payment is an IPP, so a match against
    # a public plant in the retirement schedule is a false positive by
    # construction. Confidence Rangpur matching a 1988 public unit at Rangpur is
    # what this guard exists to stop.
    retire_idx = [(tokens(k), k, v) for k, v in retire.items()
                  if v.get("ownership") == "private"]
    gem_idx = [(tokens(r["Plant / Project name"]), r["Plant / Project name"], r)
               for r in gem]

    rows, unmatched = [], []
    for e in ests:
        cp = float(e["fixed_payment_bdt"])
        if cp <= 0:
            continue
        producer = e["producer"]

        # A disclosed retirement date beats any assumption.
        rsched = best_match(producer, retire_idx)
        if rsched:
            cod = date.fromisoformat(rsched["cod"])
            expiry = date.fromisoformat(rsched["retirement_date"])
            basis = "disclosed_retirement_date"
        else:
            sp = best_match(producer, spine_idx)
            if sp:
                cod = date.fromisoformat(sp["commissioning_date"])
                basis = "assumed_15y_from_bpdb_cod"
            else:
                g = best_match(producer, gem_idx)
                if not g:
                    unmatched.append(producer)
                    continue
                try:
                    cod = date(int(float(g["Start year"])), 7, 1)
                except (ValueError, TypeError):
                    unmatched.append(producer)
                    continue
                basis = "assumed_15y_from_gem_start_year"
            expiry = date(int(cod.year + ASSUMED_TENURE_YEARS),
                          cod.month, cod.day)

        rows.append({
            "producer": producer,
            "fuel": e["fuel"],
            "annual_fixed_payment_bdt": cp,
            "cod": cod.isoformat(),
            "expiry": expiry.isoformat(),
            "expiry_basis": basis,
        })

    dest = PROC / "obligation_plants.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Obligation path and expiry calendar.
    path = {y: 0.0 for y in range(2026, HORIZON + 1)}
    cal = {y: 0.0 for y in range(2026, HORIZON + 1)}
    for r in rows:
        cp = r["annual_fixed_payment_bdt"]
        exp = date.fromisoformat(r["expiry"])
        cod = date.fromisoformat(r["cod"])
        for y in path:
            if cod.year <= y < exp.year:
                path[y] += cp
            elif y == exp.year:
                path[y] += cp * (exp.month - 1) / 12
        if exp.year in cal:
            cal[exp.year] += cp

    with (PROC / "obligation_curve.csv").open("w", newline="",
                                              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "obligation_bdt", "expiring_annual_payment_bdt"])
        for y in sorted(path):
            w.writerow([y, round(path[y], 0), round(cal[y], 0)])

    from collections import Counter
    by_basis = Counter(r["expiry_basis"] for r in rows)
    disclosed = by_basis["disclosed_retirement_date"]
    print(f"plants with an estimated fixed payment : {len(ests)}")
    print(f"  dated and carried into the curve     : {len(rows)}")
    print(f"    expiry disclosed                   : {disclosed}")
    print(f"    assumed 15y from BPDB COD          : "
          f"{by_basis['assumed_15y_from_bpdb_cod']}")
    print(f"    assumed 15y from GEM start year      : "
          f"{by_basis['assumed_15y_from_gem_start_year']}")
    print(f"  no commissioning date recoverable    : {len(unmatched)}")
    print()
    print("Obligation path, Tk crore a year")
    live = [y for y in sorted(path) if path[y] > 0]
    for y in live:
        bar = "#" * int(path[y] / 1e7 / 60)
        print(f"  {y}  {path[y]/1e7:>7,.0f}   {bar}")
    print()
    print(f"total remaining, undiscounted : Tk {sum(path.values())/1e7:,.0f} crore")
    print(f"wrote {dest.relative_to(ROOT)} and obligation_curve.csv")


if __name__ == "__main__":
    main()
