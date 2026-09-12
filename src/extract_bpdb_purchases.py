"""
Extract plant-level electricity purchase data from the notes to BPDB's audited
financial statements (note 28.x in the annual report).

Each row of note 28.1-28.4 gives, for one producer:
    units purchased (kWh) in the current and prior fiscal year, and
    amount paid (BDT) in the current and prior fiscal year.

That is the payment layer, disclosed rather than estimated. What the note does
NOT split is the capacity component from the energy component of the amount
paid; that decomposition is done separately in decompose.py.

Usage:
    python3 src/extract_bpdb_purchases.py <report.pdf> <fy_label>
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

NOTES = {
    "28.1": "ipp",
    "28.2": "india",
    "28.3": "rental",
    "28.4": "public",
}

# A data row ends in four numeric columns: kWh cy, kWh py, BDT cy, BDT py.
# Any of the four may be "-" where the value is nil.
NUM = r"(-|[\d,]+)"
ROW = re.compile(
    r"^\s*(?P<name>.+?)\s{2,}"
    + NUM + r"\s{2,}" + NUM + r"\s{2,}" + NUM + r"\s{2,}" + NUM + r"\s*$"
)

# Older reports present the same content as a chapter table with six columns:
# kWh cy, BDT cy, cost/kWh cy, kWh py, BDT py, cost/kWh py.
ROW6 = re.compile(
    r"^\s*(?P<name>.+?)\s{2,}"
    + NUM + r"\s{2,}" + NUM + r"\s{2,}([\d.]+)\s{2,}"
    + NUM + r"\s{2,}" + NUM + r"\s{2,}([\d.]+)\s*$"
)

CHAPTER_HEAD = re.compile(
    r"COMPARISION OF ELECTRICITY PURCHASE FROM (?P<who>IPP AND SIPP|RENTAL"
    r"|PUBLIC PLANTS?|INDIA)",
    re.I,
)
CHAPTER_CLASS = {
    "ipp and sipp": "ipp",
    "rental": "rental",
    "public plant": "public",
    "public plants": "public",
    "india": "india",
}

SKIP = re.compile(
    r"particulars|unit kwh|amount in bdt|annual report|balance as at|"
    r"fy\s*20|30-jun|cost/kwh|sub-?total|^\s*$",
    re.I,
)


def to_num(tok: str) -> float | None:
    tok = tok.strip()
    if tok in {"-", ""}:
        return 0.0
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def pdf_text(pdf: Path) -> list[str]:
    txt = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    return txt.splitlines()


def extract(lines: list[str]) -> list[dict]:
    rows: list[dict] = []
    current: str | None = None

    for line in lines:
        m = re.match(r"^\s*(28\.\d)\s+Electricity purchase", line)
        if m:
            current = NOTES.get(m.group(1))
            continue
        if re.match(r"^\s*28\.[5-9]\s", line):
            current = None
            continue
        m = CHAPTER_HEAD.search(line)
        if m:
            current = CHAPTER_CLASS.get(m.group("who").lower().strip())
            continue
        if current is None or SKIP.search(line):
            continue

        m6 = ROW6.match(line)
        if m6:
            name = re.sub(r"\s+", " ", m6.group("name")).strip()
            vals = [to_num(m6.group(i)) for i in (2, 3, 5, 6)]
            if len(name) < 3 or not re.search(r"[A-Za-z]", name):
                continue
            if any(v is None for v in vals):
                continue
            kwh_cy, bdt_cy, kwh_py, bdt_py = vals
            rows.append({
                "producer": name, "purchase_class": current,
                "kwh_cy": kwh_cy, "kwh_py": kwh_py,
                "bdt_cy": bdt_cy, "bdt_py": bdt_py,
            })
            continue

        m = ROW.match(line)
        if not m:
            continue

        name = re.sub(r"\s+", " ", m.group("name")).strip()
        if len(name) < 3 or not re.search(r"[A-Za-z]", name):
            continue

        vals = [to_num(m.group(i)) for i in (2, 3, 4, 5)]
        if any(v is None for v in vals):
            continue

        kwh_cy, kwh_py, bdt_cy, bdt_py = vals
        rows.append(
            {
                "producer": name,
                "purchase_class": current,
                "kwh_cy": kwh_cy,
                "kwh_py": kwh_py,
                "bdt_cy": bdt_cy,
                "bdt_py": bdt_py,
            }
        )
    return rows


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: extract_bpdb_purchases.py <report.pdf> <fy_label>")
    pdf, fy = Path(sys.argv[1]), sys.argv[2]

    rows = extract(pdf_text(pdf))
    for r in rows:
        r["fy"] = fy
        r["source_doc"] = pdf.name
        # Implied all-in cost per kWh, where the plant generated anything.
        r["bdt_per_kwh_cy"] = round(r["bdt_cy"] / r["kwh_cy"], 4) if r["kwh_cy"] else ""
        r["zero_generation_payment"] = "Y" if (r["kwh_cy"] == 0 and r["bdt_cy"] > 0) else ""

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"bpdb_purchases_{fy}.csv"
    fields = [
        "fy", "producer", "purchase_class", "kwh_cy", "kwh_py",
        "bdt_cy", "bdt_py", "bdt_per_kwh_cy", "zero_generation_payment",
        "source_doc",
    ]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    by_class: dict[str, int] = {}
    for r in rows:
        by_class[r["purchase_class"]] = by_class.get(r["purchase_class"], 0) + 1
    print(f"{len(rows)} producer rows -> {dest.relative_to(ROOT)}")
    print("  by class:", by_class)


if __name__ == "__main__":
    main()
