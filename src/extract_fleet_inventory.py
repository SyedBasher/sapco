"""
Extract the current fleet inventory from a BPDB annual report.

The inventory table lists, for every plant on the system at the fiscal year
end: name, fuel, installed capacity, net generation for the year, and a remark
(under maintenance, retired on a date, and so on). It is organised by sector
(PUBLIC, JOINT VENTURE, IPP, NENP & SIPP) and within sector by zone.

This supersedes the commissioning-table spine for current-state work, because
it reports the fleet as it stands rather than as it was added, and because the
generation column makes the plant factor observable:

    PF = G / (C * 8760)      with G in MWh and C in MW

Usage:
    python3 src/extract_fleet_inventory.py <report.pdf> <fy_label>
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

SECTORS = {"PUBLIC", "JOINT VENTURE", "PRIVATE", "IPP", "NENP & SIPP",
           "RENTAL", "QUICK RENTAL", "IMPORT"}
ZONE = re.compile(r"^\s*([A-Z][A-Z\s']+ ZONE)\s*$")
SECTOR = re.compile(r"^\s*(PUBLIC|JOINT VENTURE|PRIVATE|IPP|NENP & SIPP|"
                    r"RENTAL|QUICK RENTAL|IMPORT)\s*$")

# n | name | fuel | capacity (or -) | generation | optional remark
ROW = re.compile(
    r"^\s*(?P<n>\d{1,3})\s+"
    r"(?P<name>.+?)\s{2,}"
    r"(?P<fuel>Gas|GAS|F\.?\s?oil|F\.?\s?Oil|HSD|HFO|Solar|Wind|Hydro|"
    r"Imported Coal|Coal|Diesel|Furnace Oil)\s{2,}"
    r"(?P<cap>-|[\d,]+)\s{2,}"
    r"(?P<gen>-?[\d,.]+)"
    r"(?:\s{2,}(?P<remark>.+?))?\s*$"
)

# Some years omit the generation column and letter multi-unit sub-rows:
#   1     b) Ghorasal Repowered CCPP Unit-4          Gas              210
ROW3 = re.compile(
    r"^\s*(?:(?P<n>\d{1,3})\s+)?(?:[a-z]\)\s*)?"
    r"(?P<name>.+?)\s{2,}"
    r"(?P<fuel>Gas|GAS|F\.?\s?oil|F\.?\s?Oil|HSD|HFO|Solar|Wind|Hydro|"
    r"Imported Coal|Coal|Diesel|Furnace Oil)\s{2,}"
    r"(?P<cap>-|[\d,]+)\s*$"
)

FUEL_NORM = {
    "gas": "gas", "f.oil": "hfo", "f oil": "hfo", "foil": "hfo",
    "hfo": "hfo", "furnace oil": "hfo", "hsd": "hsd", "diesel": "hsd",
    "solar": "solar", "wind": "wind", "hydro": "hydro",
    "imported coal": "coal_imported", "coal": "coal_domestic",
}


def num(tok: str) -> float | str:
    tok = tok.strip().replace(",", "")
    if tok in {"-", ""}:
        return ""
    try:
        return float(tok)
    except ValueError:
        return ""


def extract(lines: list[str]) -> list[dict]:
    rows: list[dict] = []
    sector, zone = "", ""
    for line in lines:
        m = SECTOR.match(line)
        if m:
            s = m.group(1).strip()
            # "PRIVATE" is a banner above "IPP"; keep the finer label.
            sector = sector if s == "PRIVATE" and sector == "IPP" else s
            continue
        m = ZONE.match(line)
        if m:
            zone = m.group(1).strip()
            continue

        m = ROW.match(line) or ROW3.match(line)
        if not m:
            continue
        has_gen = "gen" in m.groupdict()
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        name = re.sub(r"^[a-z]\)\s*", "", name)
        if len(name) < 4 or not re.search(r"[A-Za-z]{3}", name):
            continue

        fuel_raw = m.group("fuel").strip()
        fuel = FUEL_NORM.get(
            re.sub(r"\.\s*", ".", fuel_raw.lower()).replace(".", " ").strip()
            .replace("  ", " "), ""
        ) or FUEL_NORM.get(fuel_raw.lower().replace(".", ""), "unknown")

        cap = num(m.group("cap"))
        gen = num(m.group("gen")) if has_gen else ""
        remark = ((m.group("remark") or "").strip() if has_gen else "")

        pf = ""
        if isinstance(cap, float) and cap > 0 and isinstance(gen, float) and gen > 0:
            pf = round(gen * 1000 / (cap * 8760), 4)

        rows.append({
            "plant_name": name,
            "sector": sector,
            "zone": zone,
            "fuel": fuel,
            "fuel_raw": fuel_raw,
            "capacity_mw": cap,
            "generation_gwh": gen,
            "plant_factor": pf,
            "remark": remark,
            "retired": "Y" if re.search(r"retired", remark, re.I) else "",
        })
    return rows


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: extract_fleet_inventory.py <report.pdf> <fy_label>")
    pdf, fy = Path(sys.argv[1]), sys.argv[2]
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          capture_output=True, text=True, check=True).stdout
    rows = extract(text.splitlines())
    for r in rows:
        r["fy"] = fy
        r["source_doc"] = pdf.name

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"fleet_inventory_{fy}.csv"
    fields = ["fy", "plant_name", "sector", "zone", "fuel", "fuel_raw",
              "capacity_mw", "generation_gwh", "plant_factor", "remark",
              "retired", "source_doc"]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    cap = sum(r["capacity_mw"] for r in rows if isinstance(r["capacity_mw"], float))
    gen = sum(r["generation_gwh"] for r in rows if isinstance(r["generation_gwh"], float))
    print(f"{len(rows)} plants -> {dest.relative_to(ROOT)}")
    print(f"  capacity {cap:,.0f} MW   generation {gen:,.0f} GWh")
    by = {}
    for r in rows:
        by[r["sector"]] = by.get(r["sector"], 0) + 1
    print("  by sector:", by)


if __name__ == "__main__":
    main()
