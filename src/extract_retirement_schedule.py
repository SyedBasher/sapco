"""
Extract BPDB's forward retirement schedule and the realised contract lengths
it implies.

The FY2020-21 annual report carries a table headed "Retirement Schedule up to
FY 2025" giving, for each plant due to leave the system, its COD and its
retirement date alongside ownership and fuel. It is the only BPDB report in the
set that looks forward rather than recording retirements after the fact.

Its value now is not the schedule itself, which has run its course, but the
pairs it contains. Retirement date less COD is a realised contract length, so
the table converts an assumption we would otherwise have to make about how long
Bangladeshi PPAs run into something estimated from BPDB's own record, separately
for public plants and for the private rental and quick-rental fleet.

Usage:
    python3 src/extract_retirement_schedule.py <report.pdf> <fy_label>
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

# 7   Siddirganj 100 MW Q.Rental PP   RE   Private   HFO   21-Jul-2011   20-Jul-2021   100
ROW = re.compile(
    r"^\s*(?P<n>\d{1,3})\s+"
    r"(?P<name>.+?)\s{2,}"
    r"(?P<unit_type>ST|CT|CC|RE|GT)\s+"
    r"(?P<ownership>Public|Private)\s+"
    r"(?P<fuel>[A-Za-z/. ]+?)\s{2,}"
    r"(?P<cod>\d{1,2}-[A-Za-z]{3}-\d{4})\s+"
    r"(?P<retire>\d{1,2}-[A-Za-z]{3}-\d{4})\s+"
    r"(?P<mw>[\d,]+)\s*$"
)

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_date(tok: str) -> date | None:
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", tok.strip())
    if not m:
        return None
    d, mon, y = int(m.group(1)), m.group(2).title(), int(m.group(3))
    if mon not in MONTHS:
        return None
    try:
        return date(y, MONTHS[mon], d)
    except ValueError:
        return None


def extract(lines: list[str]) -> list[dict]:
    rows, inside = [], False
    for line in lines:
        if re.search(r"Retirement Schedule", line, re.I):
            inside = True
            continue
        if inside and re.search(r"Ongoing Distribution Projects|Municipal Solid Waste",
                                line, re.I):
            inside = False
        if not inside:
            continue

        m = ROW.match(line)
        if not m:
            continue
        cod, retire = parse_date(m.group("cod")), parse_date(m.group("retire"))
        if not cod or not retire:
            continue

        tenure = (retire - cod).days / 365.25
        rows.append({
            "plant_name": re.sub(r"\s+", " ", m.group("name")).strip(),
            "unit_type": m.group("unit_type"),
            "ownership": m.group("ownership").lower(),
            "fuel_raw": m.group("fuel").strip(),
            "cod": cod.isoformat(),
            "retirement_date": retire.isoformat(),
            "tenure_years": round(tenure, 2),
            "capacity_mw": float(m.group("mw").replace(",", "")),
        })
    return rows


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: extract_retirement_schedule.py <report.pdf> <fy_label>")
    pdf, fy = Path(sys.argv[1]), sys.argv[2]
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          capture_output=True, text=True, check=True).stdout
    rows = extract(text.splitlines())
    for r in rows:
        r["source_doc"] = pdf.name
        r["source_fy"] = fy

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "retirement_schedule.csv"
    fields = ["plant_name", "unit_type", "ownership", "fuel_raw", "cod",
              "retirement_date", "tenure_years", "capacity_mw",
              "source_doc", "source_fy"]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} plants -> {dest.relative_to(ROOT)}")
    import statistics
    for own in ("public", "private"):
        sub = [r["tenure_years"] for r in rows if r["ownership"] == own]
        if sub:
            print(f"  {own:8s} n={len(sub):3d}  median tenure "
                  f"{statistics.median(sub):5.1f} y   range "
                  f"{min(sub):.1f}-{max(sub):.1f}")
    mw = sum(r["capacity_mw"] for r in rows)
    print(f"  total capacity in schedule: {mw:,.0f} MW")


if __name__ == "__main__":
    main()
