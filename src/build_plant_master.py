"""
Build the plant identity spine (plant_master.csv) from BPDB annual-report
commissioning tables.

Input : data/raw/*_commissioning.psv   (verbatim rows extracted from the PDF)
Output: data/processed/plant_master.csv

The spine carries only fields that are DISCLOSED in the source. Nothing here is
estimated. Contract and payment fields are added in a later stage from a
different source family and are kept in a separate table joined on plant_id.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------

# Ordered: first match wins, so compound fuels resolve before single fuels.
FUEL_MAP: list[tuple[str, str]] = [
    (r"imported\s*coal", "coal_imported"),
    (r"\bcoal\b", "coal_domestic"),
    (r"gas\s*/\s*hsd", "gas_hsd_dual"),
    (r"gas\s*/\s*(hfo|fo)", "gas_hfo_dual"),
    (r"(hfo|fo)\s*/\s*gas", "gas_hfo_dual"),
    (r"\bhsd\b", "hsd"),
    (r"\bhfo\b", "hfo"),
    (r"\bfo\b", "hfo"),
    (r"diesel", "hsd"),
    (r"\bgas\b", "gas"),
    (r"solar", "solar"),
    (r"import", "import"),
]

# Owner string -> (ownership_class, entity)
SOE = {
    "BPDB": "BPDB",
    "EGCB": "EGCB",
    "APSCL": "APSCL",
    "NWPGCL": "NWPGCL",
    "RPCL": "RPCL",
    "BCPCL": "BCPCL",
}

MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}
MONTH_ABBR = {m[:3]: i for m, i in MONTHS.items()}


# --------------------------------------------------------------------------
# Field normalisers
# --------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", " ", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def norm_fuel(raw: str) -> str:
    s = raw.strip().lower()
    for pattern, label in FUEL_MAP:
        if re.search(pattern, s):
            return label
    return "unknown"


def norm_owner(raw: str) -> tuple[str, str]:
    """Return (ownership_class, owning_entity)."""
    s = raw.strip()
    if re.search(r"rental", s, re.I):
        return "rental", "BPDB"
    if re.search(r"\bJV\b", s, re.I):
        return "jv", s.replace(" JV", "").strip()
    if re.search(r"import", s, re.I):
        return "import", "BPDB"
    if re.fullmatch(r"IPP", s, re.I):
        return "ipp", ""
    for key, entity in SOE.items():
        if key in s.upper():
            return "public", entity
    return "unknown", s


def extract_sponsor(plant_name: str) -> str:
    """Pull the sponsor out of the plant name where BPDB discloses it."""
    m = re.search(r"Sponsor\s*:\s*([^)]+)\)", plant_name, re.I)
    if m:
        return m.group(1).strip().rstrip(".")
    # Bare parenthetical that is not a unit descriptor is usually the sponsor.
    m = re.search(r"\(([^)]+)\)\s*$", plant_name)
    if m:
        cand = m.group(1).strip()
        noise = r"unit|gt|st|ccpp|fast track|\d|mw|conversion|south|north"
        if not re.search(noise, cand, re.I):
            return cand
    return ""


def parse_commissioning(raw: str) -> tuple[str, str, str]:
    """
    Return (iso_date, precision, note).

    precision is 'day', 'month' or 'none'. Where the source gives a staged
    commissioning ("GT: ...; ST: ..."), the FIRST stage is taken as the
    commissioning date and the full string is preserved in note.
    """
    s = raw.strip()
    if not s or s.upper() == "UNPARSED":
        return "", "none", raw

    note = s if (";" in s or ":" in s) else ""
    # Drop stage labels, keep the first date fragment.
    first = re.split(r";", s)[0]
    first = re.sub(r"^\s*(GT|ST|CC)\s*:\s*", "", first, flags=re.I).strip()

    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s*,?\s*(\d{4})", first)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mnum = MONTHS.get(mon) or MONTH_ABBR.get(mon[:3])
        if mnum:
            try:
                return date(year, mnum, day).isoformat(), "day", note
            except ValueError:
                pass

    m = re.search(r"([A-Za-z]+)\s*,?\s*(\d{4})", first)
    if m:
        mon, year = m.group(1).lower(), int(m.group(2))
        mnum = MONTHS.get(mon) or MONTH_ABBR.get(mon[:3])
        if mnum:
            return date(year, mnum, 1).isoformat(), "month", note

    m = re.search(r"(\d{4})", first)
    if m:
        return date(int(m.group(1)), 1, 1).isoformat(), "none", note

    return "", "none", raw


def guess_location(plant_name: str) -> str:
    """First comma-delimited token is usually the place name in BPDB tables."""
    head = plant_name.split("(")[0]
    if "," in head:
        return head.split(",")[0].strip()
    tokens = head.split()
    return tokens[0] if tokens else ""


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

FIELDS = [
    "plant_id",
    "plant_name",
    "location",
    "capacity_mw",
    "fuel",
    "fuel_raw",
    "ownership_class",
    "owning_entity",
    "sponsor",
    "commissioning_date",
    "date_precision",
    "commissioning_note",
    "source_doc",
]


def build(rows: list[dict], source_doc: str) -> list[dict]:
    out, seen = [], {}
    for r in rows:
        name = r["plant_name_raw"].strip()
        iso, precision, note = parse_commissioning(r["commissioning_raw"])
        ownership, entity = norm_owner(r["owner_raw"])
        sponsor = extract_sponsor(name)
        if ownership == "ipp" and not entity:
            entity = sponsor

        year = iso[:4] if iso else "na"
        base = f"bd-{slugify(name)[:48]}-{year}"
        seen[base] = seen.get(base, 0) + 1
        plant_id = base if seen[base] == 1 else f"{base}-{seen[base]}"

        try:
            cap = float(r["capacity_mw_raw"])
        except ValueError:
            cap = ""

        out.append(
            {
                "plant_id": plant_id,
                "plant_name": name,
                "location": guess_location(name),
                "capacity_mw": cap,
                "fuel": norm_fuel(r["fuel_raw"]),
                "fuel_raw": r["fuel_raw"].strip(),
                "ownership_class": ownership,
                "owning_entity": entity,
                "sponsor": sponsor,
                "commissioning_date": iso,
                "date_precision": precision,
                "commissioning_note": note,
                "source_doc": source_doc,
            }
        )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    for path in sorted(RAW.glob("*_commissioning.psv")):
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh, delimiter="|"))
        all_rows.extend(build(rows, path.stem))

    dest = OUT / "plant_master.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    print(f"wrote {len(all_rows)} plants -> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
