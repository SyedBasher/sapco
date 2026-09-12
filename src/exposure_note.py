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
USD = 122.0   # Tk per US$, spot; stated on the page

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
    "disclosed_retirement_date": "BPDB schedule",
    "assumed_15y_from_bpdb_cod": "COD + 15 yrs",
    "assumed_15y_from_gem_start_year": "COD + 15 yrs",
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


# Categorical slots in fixed order (validated for adjacent pairs, which is the
# stacked-bar case). Never cycled: past eight, plants fold into "Other".
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#8a8983"


def short_name(producer: str) -> str:
    """A legend-length label: the part that distinguishes this plant."""
    s = re.sub(r"\b(Power|Generation|Energy|Company|Co|Ltd|Limited|Pvt|"
               r"Private|Plant|Systems?|Services?|Infra\w*)\b\.?", " ", producer)
    s = re.sub(r"\s*[-–]\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .,-")
    return s or producer


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
        half = next((y for y in years if path[y] <= 0.5 * base), last)
        if half < last:
            gone = sum(1 for r in plants if first < int(r["expiry"][:4]) <= half)
            title = (f"Contracted fixed payments halve by {half} and run out "
                     f"in {last}; {gone} of {n} PPAs expire in between")
        else:
            title = (f"Contracted fixed payments hold near Tk {base/CRORE:,.0f} "
                     f"crore until {last}, when the last PPA expires")

    note = ("Each column shows the fixed payment owed that year under contracts "
            "already signed, in Tk crore, broken down by plant. A band "
            "disappears when that plant\u2019s contract expires, on the date given "
            "in the table below. Where that date is our own estimate rather than "
            "a disclosed one, the band may end a year or two early or late, "
            "though its height does not depend on it.")
    return title, note


def plant_path(r: dict, years: list[int]) -> dict[int, float]:
    cp = float(r["annual_fixed_payment_bdt"])
    cod = date.fromisoformat(r["cod"])
    exp = date.fromisoformat(r["expiry"])
    out = {}
    for y in years:
        if cod.year <= y < exp.year:
            out[y] = cp
        elif y == exp.year:
            out[y] = cp * (exp.month - 1) / 12
        else:
            out[y] = 0.0
    return out


def path_at_tenure(plants: list[dict], years_tenure: float,
                   horizon: int = 2050) -> dict[int, float]:
    """
    Recompute the obligation path with a different contract length.

    Disclosed retirement dates are left alone; only plants whose expiry rests
    on the median-tenure assumption move. That is the whole point of showing
    the sensitivity — it separates what is known from what is assumed.
    """
    path = {y: 0.0 for y in range(2026, horizon + 1)}
    for r in plants:
        cp = float(r["annual_fixed_payment_bdt"])
        cod = date.fromisoformat(r["cod"])
        if r["expiry_basis"] == "disclosed_retirement_date":
            exp = date.fromisoformat(r["expiry"])
        else:
            exp = date(cod.year + int(years_tenure), cod.month, cod.day)
        for y in path:
            if cod.year <= y < exp.year:
                path[y] += cp
            elif y == exp.year:
                path[y] += cp * (exp.month - 1) / 12
    return {y: v for y, v in path.items() if v > 0}


def sensitivity_block(plants: list[dict]) -> str:
    """
    How much of the total rests on the tenure assumption, in one sentence.

    Disclosed retirement dates are held fixed; only the assumed expiries move,
    which is the point — it separates what is known from what is supposed.
    """
    if not any(r["expiry_basis"] != "disclosed_retirement_date" for r in plants):
        return ""
    out = {}
    for yrs in (12, 18, 22):
        pth = path_at_tenure(plants, yrs)
        if pth:
            out[yrs] = (sum(pth.values()), max(pth))
    if not out:
        return ""
    verbs = {12: "Shortening it to twelve years leaves",
             18: "stretching it to eighteen gives",
             22: "and to twenty-two"}
    clauses = "; ".join(
        f"{verbs.get(y, f'at {y} years')} Tk {v/CRORE:,.0f} crore "
        f"outstanding to {last}"
        for y, (v, last) in out.items())
    return (
        '<p class="sens"><b>If the contracts run longer or shorter.</b> '
        'The fifteen-year contract length used here is the median implied by '
        'BPDB\'s own retirement schedule, where plants ran anywhere from five '
        f'years to twenty-two. {clauses}. If you know what the contracts '
        'actually say, read the line that matches — the annual payments are '
        'unaffected either way.</p>')


def nice_ticks(peak: float, n: int = 4) -> list[float]:
    """Round tick values at or just above the peak, in crore."""
    raw = peak / CRORE / n
    mag = 10 ** (len(f"{int(raw)}") - 1) if raw >= 1 else 1
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * mag
        if step * n >= peak / CRORE:
            return [step * i for i in range(n + 1)]
    return [raw * i for i in range(n + 1)]


def bar_chart(path: dict[int, float], plants: list[dict]) -> str:
    """
    Stacked columns, one band per plant, on a gridded plot.

    The stack shows which contract falls away in which year rather than only
    the total. Bands take the categorical palette in fixed order, never
    cycled; a ninth plant folds into "Other". Gridlines and the frame are
    drawn in the rule colour so they stay behind the data, and the legend is
    always present because there is more than one series.
    """
    if not path:
        return ""
    years = sorted(path)
    peak = max(path.values())
    ticks = nice_ticks(peak)
    top = ticks[-1] * CRORE

    W, H = 640, 156
    pad_l, pad_b, pad_t = 34, 18, 8
    n = len(years)
    plot_w = W - pad_l
    plot_h = H - pad_b - pad_t
    slot = plot_w / n
    bw = min(34.0, max(10.0, slot - 12))

    def y_of(v: float) -> float:
        return pad_t + plot_h * (1 - v / top)

    out = []
    for tv in ticks:
        y = y_of(tv * CRORE)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W}" y2="{y:.1f}" '
                   f'class="grid"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" '
                   f'class="tick">{tv:,.0f}</text>')
    out.append(f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" '
               f'height="{plot_h:.1f}" class="frame"/>')

    ranked = sorted(plants, key=lambda r: -float(r["annual_fixed_payment_bdt"]))
    # A plant whose contract ended before the window contributes no band, so
    # giving it a legend key would label something the reader cannot see.
    ranked = [r for r in ranked if sum(plant_path(r, years).values()) > 0]
    shown, folded = ranked[:8], ranked[8:]
    series = [(short_name(r["producer"]), SERIES[i], plant_path(r, years))
              for i, r in enumerate(shown)]
    if folded:
        merged = {y: sum(plant_path(r, years)[y] for r in folded) for y in years}
        series.append((f"Other ({len(folded)})", OTHER, merged))

    base_y = y_of(0)
    for i, y in enumerate(years):
        x = pad_l + i * slot + (slot - bw) / 2
        cursor = base_y
        for _, colour, pp in series:
            v = pp[y]
            if v <= 0:
                continue
            h = plot_h * v / top
            out.append(
                f'<rect x="{x:.1f}" y="{cursor - h:.1f}" width="{bw:.1f}" '
                f'height="{max(1.0, h - 2):.1f}" fill="{colour}"/>')
            cursor -= h
        out.append(
            f'<text x="{x + bw/2:.1f}" y="{cursor - 6:.1f}" '
            f'text-anchor="middle" class="vlabel">{path[y]/CRORE:,.0f}</text>')
        out.append(
            f'<text x="{x + bw/2:.1f}" y="{H - 5}" text-anchor="middle" '
            f'class="tick">{y}</text>')

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" '
           f'role="img" aria-label="Contracted fixed payment by year and plant, '
           f'Tk crore">' + "".join(out) + "</svg>")
    legend = "".join(
        f'<span class="key"><i style="background:{c}"></i>{html.escape(nm)}</span>'
        for nm, c, _ in series)
    return svg + f'<div class="legend">{legend}</div>'


CSS = """
:root{--surface-1:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--ink-3:#8a8983;
--series-1:#2a78d6;--rule:#e3e2dd}
*{box-sizing:border-box}
body{margin:0;background:#f3f2ee;color:var(--ink);
font:12px/1.45 Cambria,Caladea,Georgia,"Times New Roman",serif;
--sans:Calibri,Carlito,"Segoe UI",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.page{width:210mm;min-height:297mm;margin:0 auto;padding:13mm 16mm;
background:var(--surface-1)}
h1{font-size:18px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--ink-2);margin:0 0 12px;font-size:11.5px}
.kpis{display:flex;gap:22px;border-top:1px solid var(--rule);
border-bottom:1px solid var(--rule);padding:9px 0;margin-bottom:10px}
.kpi{flex:1}
.kpi .v{font-family:var(--sans);font-size:21px;font-weight:600;
font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.15}
.kpi .l{font-family:var(--sans);font-size:10px;color:var(--ink-2);
text-transform:uppercase;letter-spacing:.06em;margin-top:3px}
.kpi .alt{font-family:var(--sans);font-size:10.5px;color:var(--ink-3);
font-variant-numeric:tabular-nums;margin-top:1px}
h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;
color:var(--ink-2);margin:11px 0 5px;font-weight:600}
.fig-title{font-size:13.5px;font-weight:600;margin:10px 0 2px;line-height:1.35;
letter-spacing:-.005em}
.fig-sub{font-size:10.5px;color:var(--ink-2);margin:0 0 6px}
.fig-note{font-size:10px;color:var(--ink-2);line-height:1.45;margin:2px 0 0}
.legend{display:flex;flex-wrap:wrap;gap:3px 14px;margin:5px 0 0;
font-family:var(--sans);font-size:10px;color:var(--ink-2)}
.key{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.key i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none}
.purpose{border-left:2px solid var(--series-1);padding:2px 0 2px 11px;
margin:0 0 9px;font-size:11px;line-height:1.48;color:var(--ink-2)}
.purpose b{color:var(--ink);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;font-family:var(--sans);font-weight:600;
color:var(--ink-2);font-size:10px;
text-transform:uppercase;letter-spacing:.05em;padding:0 8px 5px 0;
border-bottom:1px solid var(--rule)}
td{padding:3px 8px 3px 0;border-bottom:1px solid #f0efea}
.num{text-align:right;font-family:var(--sans);
font-variant-numeric:tabular-nums;font-size:11.5px}
.muted{color:var(--ink-3);font-size:11px}
.grid{stroke:#eeede8;stroke-width:1}
.frame{fill:none;stroke:#b9b8b1;stroke-width:1.1}
.tick{fill:var(--ink-3);font-size:9.5px;font-family:Calibri,Carlito,sans-serif}
.vlabel{fill:var(--ink);font-size:10.5px;font-weight:600;
font-variant-numeric:tabular-nums;font-family:Calibri,Carlito,sans-serif}
.years{width:100%;font-size:10.5px;color:var(--ink-2);margin-top:4px;
font-variant-numeric:tabular-nums}
.years td{border:0;padding:1px 0;text-align:center}
.note{margin-top:9px;padding-top:7px;border-top:1px solid var(--rule);
font-size:9.5px;color:var(--ink-2);line-height:1.45}
.note b{color:var(--ink);font-weight:600}
p.sens{margin:8px 0 0;font-size:9.5px;color:var(--ink-2);
line-height:1.5}
p.sens b{color:var(--ink);font-weight:600}
.contact{margin-top:6px;font-family:var(--sans);font-size:10px;
color:var(--ink-2)}
.contact a{color:var(--ink-2)}
@media print{body{background:#fff}.page{width:auto;min-height:0;padding:0}
.note,.contact,p.sens{break-inside:avoid;page-break-inside:avoid}}
@page{size:A4;margin:14mm 16mm}
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
        f'<p class="sub">Prepared {date.today():%d %B %Y} · '
        f'SAPCO, South Asia Power Contracts Observatory</p>',
        '<p class="purpose">Part of what BPDB pays a power producer is fixed — owed whether or not the plant runs. This note works out how much that is, plant by plant, and when each contract ends. The contracts themselves are not public, so everything here is drawn from published accounts, BPDB\'s and the sponsors\' own. The aim is to spare a lender or a counterparty the days of reading annual reports it would otherwise take. Every figure is an estimate, and the table shows what each is based on; none of it is a valuation or advice.</p>',
        '<div class="kpis">',
        f'<div class="kpi"><div class="v">{annual/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore owed in 2026</div>'
        f'<div class="alt">US$ {annual/USD/1e6:,.0f}m</div></div>',
        f'<div class="kpi"><div class="v">{len(plants)}</div>'
        f'<div class="l">plants under contract</div>'
        f'<div class="alt">&nbsp;</div></div>',
        f'<div class="kpi"><div class="v">{total/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore remaining</div>'
        f'<div class="alt">US$ {total/USD/1e9:,.2f}bn</div></div>',
        f'<div class="kpi"><div class="v">{pv/CRORE:,.0f}</div>'
        f'<div class="l">Tk crore, PV at 9%</div>'
        f'<div class="alt">US$ {pv/USD/1e9:,.2f}bn</div></div>',
        '</div>',
        f'<p class="fig-title">{html.escape(fig_title)}</p>',
        ('<p class="fig-sub">Contracted fixed payment by year and plant, Tk crore</p>'
         if path else ''),
        bar_chart(path, plants),
        f'<p class="fig-note">{fig_note}</p>' if fig_note else '',
        '<h2>Plants</h2>',
        '<table><thead><tr><th>Plant</th><th>Fuel</th>'
        '<th class="num">Fixed payment<br>Tk crore/yr</th>'
        '<th class="num">COD</th><th class="num">Expiry</th>'
        '<th>Expiry basis</th></tr></thead><tbody>',
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

    body.append(sensitivity_block(plants))
    body.append(
        '<div class="note">'
        '<b>Method.</b> Fixed payments are estimated from BPDB\'s audited '
        'accounts, which disclose units purchased and taka paid for each '
        'producer. Payment is decomposed as '
        '<i>P<sub>it</sub> = CP<sub>i</sub> + v<sub>f,t</sub> E<sub>it</sub></i>, '
        'with a plant-specific fixed component and an energy rate common to '
        'plants of the same fuel in the same year, estimated over FY2019-20 to '
        'FY2024-25. Where a sponsor reports revenue net of fuel for a plant, '
        'that figure caps its fixed component, since the capacity payment has '
        'to be paid out of it; no fixed component is allowed to be negative. '
        f'<b>Limitations.</b> Of the {len(plants)} plants above, {assumed} carry '
        f'an expiry '
        'assumed at 15 years from commissioning — the median realised contract '
        'length in BPDB\'s retirement schedule — rather than a disclosed date, '
        'so the run-off profile is indicative. The estimate is held down '
        'where such a cap exists, but nothing confirms it: none of the sponsors '
        'examined publishes a capacity rate. Figures are nominal '
        'and undiscounted except where stated. '
        f'Dollar equivalents convert at Tk {USD:.0f} = US$1 and are indicative '
        'only: the currency in which each contract is denominated is not '
        'disclosed, and applying one spot rate to payments running to the '
        '2030s understates that uncertainty. '
        '<b>Sources.</b> BPDB annual reports FY2019-20 to FY2024-25; sponsor '
        'audited financial statements; Global Energy Monitor Integrated Power '
        'Tracker, August 2026.'
        '</div>'
    )
    body.append(
        '<div class="contact">For corrections or comments, please contact '
        'Syed Basher at '
        '<a href="mailto:syed.basher@gmail.com">syed.basher@gmail.com</a>.</div>'
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
