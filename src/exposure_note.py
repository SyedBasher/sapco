"""
Generate a one-page contracted-exposure note for a sponsor group.

The note is the commercial object the rest of the database exists to produce.
It answers, for one sponsor, the question a lender actually has: how much of
this group's revenue is contractually fixed, and in which year does each piece
of it stop.

It is deliberately a print document rather than a dashboard. The reader is a
credit committee, it will be forwarded as a PDF, and its limitations are stated
on the page rather than in a footnote nobody opens.

Usage:
    python3 src/exposure_note.py "Summit"            one sponsor
    python3 src/exposure_note.py --all               every sponsor group
"""

from __future__ import annotations

import csv
import html
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "notes"

DISCOUNT = 0.09
CRORE = 1e7

# Sponsor group -> pattern matching the producer names BPDB uses.
GROUPS = {
    "Summit": r"Summit|ACE Alliance",
    "United": r"United",
    "Confidence": r"Confidence",
    "Acron": r"Acron|Acorn",
    "Doreen": r"Doreen",
    "Orion": r"Orion",
    "Desh Energy": r"Desh Energy",
    "Baraka": r"Baraka",
    "RPCL": r"RPCL|RPC LTD",
    "Midland": r"Midland",
    "Regent": r"Regent",
    "Lanka": r"Lanka|Lakdhanvi",
    "Meghnaghat Power": r"^Meghnaghat",
    "Kushiara": r"Kushiara",
    "Anlima": r"Anlima",
    "Karnaphuli": r"Karnaphuli",
    "Chandpur": r"^Chandpur",
    "Bhairab": r"Bhairab",
    "HF Power": r"HF Power",
    "Spectra": r"Spectra",
}

FUEL_LABEL = {"gas": "Gas", "hfo": "HFO", "hsd": "HSD", "solar": "Solar",
              "coal_imported": "Imported coal", "coal_domestic": "Coal",
              "wind": "Wind", "hydro": "Hydro"}

BASIS_LABEL = {
    "disclosed_retirement_date": "disclosed",
    "assumed_15y_from_bpdb_cod": "assumed",
    "assumed_15y_from_gem_start_year": "assumed",
}


def group_of(producer: str) -> str | None:
    for name, pattern in GROUPS.items():
        if re.search(pattern, producer, re.I):
            return name
    return None


def load() -> dict[str, list[dict]]:
    rows = list(csv.DictReader(
        (PROC / "obligation_plants.csv").open(encoding="utf-8")))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g = group_of(r["producer"])
        if g:
            out[g].append(r)
    return out


def yearly_path(plants: list[dict], horizon: int = 2045) -> dict[int, float]:
    path = {y: 0.0 for y in range(2026, horizon + 1)}
    for r in plants:
        cp = float(r["annual_fixed_payment_bdt"])
        cod = date.fromisoformat(r["cod"])
        exp = date.fromisoformat(r["expiry"])
        for y in path:
            if cod.year <= y < exp.year:
                path[y] += cp
            elif y == exp.year:
                path[y] += cp * (exp.month - 1) / 12
    return {y: v for y, v in path.items() if v > 0}


def chart_story(path: dict[int, float], plants: list[dict]) -> tuple[str, str]:
    """Return (action title, figure note), both stated from the data."""
    years = sorted(path)
    if not years:
        ended = max((r["expiry"] for r in plants), default="")
        return (f"Every contract in this group has already expired"
                + (f", the last in {ended[:4]}" if ended else ""),
                "No fixed payment is owed on the present contracts. The plants "
                "below are shown with the payments they carried while their "
                "PPAs ran.")
    first, last = years[0], years[-1]
    base, n = path[first], len(plants)

    if n == 1:
        title = (f"A single PPA carries Tk {base/CRORE:,.0f} crore a year "
                 f"and expires in {last}")
    else:
        # The year the obligation has halved says more than the steepest
        # single step, which on a run-off is always the final year.
        half = next((y for y in years if path[y] <= 0.5 * base), last)
        if half < last:
            gone = sum(1 for r in plants if first < int(r["expiry"][:4]) <= half)
            title = (f"Contracted fixed payments halve by {half} and run out "
                     f"in {last}; {gone} of {n} PPAs expire in between")
        else:
            title = (f"Contracted fixed payments hold near Tk {base/CRORE:,.0f} "
                     f"crore until {last}, when the last PPA expires")

    note = (f"Each bar is the fixed payment owed in that year under contracts "
            f"already signed, in Tk crore. The obligation runs from "
            f"Tk {base/CRORE:,.0f} crore in {first} to "
            f"Tk {path[last]/CRORE:,.0f} crore in {last}, after which nothing "
            f"further is owed on the present contracts. Expiry dates marked "
            f"\u2018assumed\u2019 in the table below carry the median realised "
            f"contract length rather than a disclosed date, so the timing of "
            f"each step is indicative while its size is not.")
    return title, note


def bar_chart(path: dict[int, float]) -> str:
    """
    Single series, value-labelled, no axis.

    Every bar carries its number and the y-axis is removed entirely, which is
    the consulting convention and is defensible here: with the axis gone the
    labels are the scale rather than a duplicate of it. Ten bars at four
    significant figures stay legible at print size; beyond about fifteen this
    would have to revert to a labelled axis and selective callouts.
    """
    if not path:
        return ""
    years = sorted(path)
    peak = max(path.values())
    W, H = 640, 168
    pad_b, pad_t = 18, 18
    n = len(years)
    slot = W / n
    bw = min(30.0, max(10.0, slot - 10))
    plot_h = H - pad_b

    out = [f'<line x1="0" y1="{plot_h}" x2="{W}" y2="{plot_h}" class="axis"/>']
    for i, y in enumerate(years):
        h = max(2.0, (plot_h - pad_t) * path[y] / peak)
        x = pad_l = i * slot + (slot - bw) / 2
        cx = x + bw / 2
        out.append(
            f'<rect x="{x:.1f}" y="{plot_h - h:.1f}" width="{bw:.1f}" '
            f'height="{h:.1f}" rx="3" fill="var(--series-1)"/>')
        out.append(
            f'<text x="{cx:.1f}" y="{plot_h - h - 5:.1f}" text-anchor="middle" '
            f'class="vlabel">{path[y]/CRORE:,.0f}</text>')
        out.append(
            f'<text x="{cx:.1f}" y="{H - 5}" text-anchor="middle" '
            f'class="tick">{y}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" '
            f'role="img" aria-label="Contracted fixed payment by year, Tk crore">'
            + "".join(out) + "</svg>")


CSS = """
:root{--surface-1:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--ink-3:#8a8983;
--series-1:#2a78d6;--rule:#e3e2dd}
*{box-sizing:border-box}
body{margin:0;background:#f3f2ee;color:var(--ink);
font:13px/1.5 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
.page{width:210mm;min-height:297mm;margin:0 auto;padding:18mm 16mm;
background:var(--surface-1)}
h1{font-size:20px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--ink-2);margin:0 0 18px;font-size:12px}
.kpis{display:flex;gap:22px;border-top:1px solid var(--rule);
border-bottom:1px solid var(--rule);padding:12px 0;margin-bottom:18px}
.kpi{flex:1}
.kpi .v{font-size:22px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kpi .l{font-size:10.5px;color:var(--ink-2);text-transform:uppercase;
letter-spacing:.06em;margin-top:2px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;
color:var(--ink-2);margin:20px 0 8px;font-weight:600}
.fig-title{font-size:14px;font-weight:600;margin:16px 0 2px;line-height:1.35;
letter-spacing:-.005em}
.fig-sub{font-size:10.5px;color:var(--ink-2);margin:0 0 6px}
.fig-note{font-size:10.5px;color:var(--ink-2);line-height:1.5;margin:2px 0 0}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;font-weight:600;color:var(--ink-2);font-size:10.5px;
text-transform:uppercase;letter-spacing:.05em;padding:0 8px 5px 0;
border-bottom:1px solid var(--rule)}
td{padding:5px 8px 5px 0;border-bottom:1px solid #f0efea}
.num{text-align:right;font-variant-numeric:tabular-nums}
.muted{color:var(--ink-3);font-size:11px}
.axis{stroke:var(--rule);stroke-width:1}
.tick{fill:var(--ink-3);font-size:9.5px;font-family:inherit}
.vlabel{fill:var(--ink);font-size:10.5px;font-variant-numeric:tabular-nums;
font-family:inherit}
.years{width:100%;font-size:10.5px;color:var(--ink-2);margin-top:4px;
font-variant-numeric:tabular-nums}
.years td{border:0;padding:1px 0;text-align:center}
.note{margin-top:22px;padding-top:10px;border-top:1px solid var(--rule);
font-size:10.5px;color:var(--ink-2);line-height:1.55}
.note b{color:var(--ink);font-weight:600}
@media print{body{background:#fff}.page{width:auto;min-height:0;padding:0}}
@page{size:A4;margin:16mm}
"""


def render(sponsor: str, plants: list[dict]) -> str:
    plants = sorted(plants, key=lambda r: -float(r["annual_fixed_payment_bdt"]))
    path = yearly_path(plants)
    annual = path.get(2026, 0.0)      # owed in the current year
    listed = sum(float(r["annual_fixed_payment_bdt"]) for r in plants)
    total = sum(path.values())
    pv = sum(v / (1 + DISCOUNT) ** (y - 2025) for y, v in path.items())
    last = max(path) if path else None
    assumed = sum(1 for r in plants if r["expiry_basis"] != "disclosed_retirement_date")
    fig_title, fig_note = chart_story(path, plants)

    body = [
        f'<h1>{html.escape(sponsor)} — contracted capacity-payment exposure</h1>',
        f'<p class="sub">Estimated fixed payments from BPDB and their expiry '
        f'profile · prepared {date.today():%d %B %Y}</p>',
        '<div class="kpis">',
        f'<div class="kpi"><div class="v">{annual/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore owed in 2026</div></div>',
        f'<div class="kpi"><div class="v">{len(plants)}</div>'
        f'<div class="l">plants</div></div>',
        f'<div class="kpi"><div class="v">{total/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore remaining</div></div>',
        f'<div class="kpi"><div class="v">{pv/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore, PV at 9%</div></div>',
        '</div>',
        f'<p class="fig-title">{html.escape(fig_title)}</p>',
        ('<p class="fig-sub">Contracted fixed payment by year, Tk crore</p>'
         if path else ''),
        bar_chart(path),
        f'<p class="fig-note">{fig_note}</p>' if fig_note else '',
        '<h2>Plants</h2>',
        '<table><thead><tr><th>Plant</th><th>Fuel</th>'
        '<th class="num">Fixed payment<br>Tk crore/yr</th>'
        '<th class="num">COD</th><th class="num">Expiry</th>'
        '<th>Basis</th></tr></thead><tbody>',
    ]
    for r in plants:
        body.append(
            f'<tr><td>{html.escape(r["producer"])}</td>'
            f'<td>{FUEL_LABEL.get(r["fuel"], r["fuel"])}</td>'
            f'<td class="num">{float(r["annual_fixed_payment_bdt"])/CRORE:,.0f}</td>'
            f'<td class="num">{r["cod"][:4]}</td>'
            f'<td class="num">{r["expiry"][:4]}</td>'
            f'<td class="muted">{BASIS_LABEL.get(r["expiry_basis"], "")}</td></tr>'
        )
    body.append(
        f'<tr><td><b>Total</b></td><td></td>'
        f'<td class="num"><b>{listed/CRORE:,.0f}</b></td>'
        f'<td colspan="3"></td></tr></tbody></table>'
    )

    body.append(
        '<div class="note">'
        '<b>Method.</b> Fixed payments are estimated from BPDB\'s audited '
        'accounts, which disclose units purchased and taka paid for each '
        'producer. Payment is decomposed as '
        '<i>P<sub>it</sub> = CP<sub>i</sub> + v<sub>f,t</sub> E<sub>it</sub></i>, '
        'with a plant-specific fixed component and an energy rate common to '
        'plants of the same fuel in the same year, estimated over FY2019-20 to '
        'FY2024-25 and bounded above by the non-fuel revenue sponsors report in '
        'their own accounts. '
        f'<b>Limitations.</b> Of the plants above, {assumed} carry an expiry '
        'assumed at 15 years from commissioning — the median realised contract '
        'length in BPDB\'s retirement schedule — rather than a disclosed date, '
        'so the run-off profile is indicative. The fixed component is bounded '
        'by disclosure but not confirmed by it: no sponsor publishes a capacity '
        'rate. Figures are nominal and undiscounted except where stated. '
        '<b>Sources.</b> BPDB annual reports FY2019-20 to FY2024-25; sponsor '
        'audited financial statements; Global Energy Monitor Integrated Power '
        'Tracker, August 2026.'
        '</div>'
    )

    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{html.escape(sponsor)} — contracted exposure</title>'
            f'<style>{CSS}</style></head><body>'
            f'<div class="page">{"".join(body)}</div></body></html>')


def main() -> None:
    groups = load()
    if not groups:
        sys.exit("no sponsor groups matched; run obligation_curve.py first")

    if len(sys.argv) < 2:
        print("sponsor groups available:")
        for g, p in sorted(groups.items(),
                           key=lambda x: -sum(float(r["annual_fixed_payment_bdt"])
                                              for r in x[1])):
            v = sum(float(r["annual_fixed_payment_bdt"]) for r in p)
            print(f"  {g:20s} {len(p):2d} plants  Tk {v/CRORE:>6,.0f} crore/yr")
        return

    OUT.mkdir(exist_ok=True)
    targets = sorted(groups) if sys.argv[1] == "--all" else [sys.argv[1]]
    for t in targets:
        if t not in groups:
            print(f"  no such sponsor group: {t}")
            continue
        path = OUT / f"exposure-{t.lower().replace(' ', '-')}.html"
        path.write_text(render(t, groups[t]), encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
