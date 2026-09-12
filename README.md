# Bangladesh Power Contract Obligations

A plant-level database of generation capacity in Bangladesh and the contractual
obligations attached to it, assembled entirely from public online sources.

The premise is that the identity of every plant is public, the terms of many
contracts are public but buried in the notes to audited financial statements,
and the resulting payment obligations are published nowhere. The first two
layers are collection work. The third is where the analysis lives.

## Layers

| Layer | Contents | Source family | Status |
|---|---|---|---|
| v0.1 Identity spine | plant, capacity, fuel, commissioning date, ownership, sponsor | BPDB annual reports; Global Energy Monitor cross-check | **built, partial coverage** |
| v0.2 Contract layer | off-taker, COD, retirement/expiry date, tariff structure | BPDB retirement schedule (FY2020-21 report); listed-IPP notes to accounts for the rest | partial |
| v0.3 Payment layer | kWh and taka paid per producer per year; fixed/energy split estimated | BPDB notes 28.1-28.4 and the equivalent chapter tables — **disclosed, not imputed** | **built, FY2019-20 to FY2024-25** |
| v0.4 Derived layer | obligation path, per-unit idle cost, FX exposure, expiry calendar | computed | **module built and tested** |

Layers v0.1 and the expiry calendar are intended to be public. The payment
layer, the imputed rates and the sponsor exposure notes are held back.

## Current state

`data/processed/plant_master.csv` holds 114 plants totalling 15,179 MW,
covering units commissioned between 2010 and mid-2020, extracted from the BPDB
annual report for FY2019-20.

Classification is complete — no unknown fuel and no unknown ownership records.
104 of 114 commissioning dates are recovered to the day, 9 to the month, 1 not
at all.

The coverage stops at mid-2020 because that is where the source document stops.
Extending it to 2026 requires the later BPDB annual reports, which is the single
most important next input.

## Known reconciliation issue

Capacity is recorded as BPDB records it, which is generally net or derated.
Third-party trackers record gross nameplate. Payra Unit 1 appears here at
622 MW against 660 MW in Global Energy Monitor, with the same May 2020
commissioning. Both numbers are right for their own purpose and the database
must carry both rather than choosing, since obligation calculations are struck
on contracted capacity, which is a third figure again.

## Method note

Nothing in the spine is estimated. Where a field could not be recovered it is
left empty and flagged, never filled by inference. Estimation begins only at
the payment layer, where it is labelled as such and reported with intervals.

The validation test for the whole database is that bottom-up modelled capacity
payments, summed across the fleet, should reproduce BPDB's published aggregate
capacity payment within a few per cent, year by year. Until that reconciliation
holds, the estimates are not publishable.

## Layout

```
data/raw/         verbatim extractions, one file per source document
data/processed/   plant_master.csv
src/              build_plant_master.py, obligations.py
docs/             schema and data dictionary
```

## Running

```
python3 src/build_plant_master.py
```

No dependencies beyond the standard library.


## Panel results (11 September 2026)

The four machine-readable annual reports each state a current and a prior year,
so together they cover FY2019-20 to FY2024-25: 767 producer-year observations
across 194 producers. Estimating

    P_it = CP_i + v_i * E_it + e_it

on each producer's own series gives 118 producers with three or more
observations, of which 78 return a positive fixed payment and a positive energy
rate, with a median R-squared of 0.77 and Tk 13,894 crore of implied fixed
payments in total.

The low-R-squared cases are informative rather than defective. Summit Barishal
at 0.01 and United Jamalpur at 0.11 are plants whose payments moved with fuel
prices and the exchange rate rather than with dispatch, which is precisely the
variation the next specification has to control for.

The FY2021-22 report is a scanned image and does not extract, but it does not
need to: FY2021-22 appears as the comparative year in the FY2022-23 report.

## Fuel-controlled panel (12 September 2026)

Letting the energy rate vary by fuel and year while the capacity payment stays
fixed to the plant,

    P_it = CP_i + v_{f(i),t} * E_it + e_it

raises the overall R-squared to 0.969 and returns a positive fixed payment for
42 of the 44 plants that survive the fuel match and the four-observation
threshold, totalling Tk 9,421 crore. The per-plant specification it replaces
had a median R-squared of 0.77 and failed the sign test on 40 of 118 plants.

The estimated energy rates are economically legible, in taka per kWh:

    fuel        FY20   FY21   FY22   FY23   FY24   FY25
    gas         1.69   1.71   2.02   3.29   4.12   5.10
    hfo         3.99   5.96  12.25  14.22  15.56  15.35
    solar      10.82  10.85  10.89  13.64  14.54  15.85

Solar is the validation case. A solar plant has no fuel cost, so its energy
rate should move only with the exchange rate, and over the six years it rises
by 46.5 per cent against a taka depreciation of roughly 44 per cent. The
estimator is recovering the currency exposure it ought to recover. HFO steps
up in FY2021-22 with the oil price and the taka together; gas roughly triples
from FY2022-23, which is larger than depreciation alone and points to the
administered price changes of that period — worth checking against the BERC
orders before it is published.

Two caveats travel with these numbers. Only 62 of the 99 IPP producers in the
panel could be matched to a fuel, and the four-observation threshold reduces
that to 44, so the Tk 9,421 crore is a floor covering part of the fleet rather
than a fleet total. Improving the producer-to-plant crosswalk is the single
largest remaining gain.

## The split is not yet robust (12 September 2026)

Pooling the fleet inventories from all four reports lifts the fuel match from
62 producers to 68 and the estimable set from 44 plants to 47, with the overall
R-squared rising to 0.981 and 46 of 47 intercepts positive. The fleet total of
implied fixed payments falls from Tk 9,421 crore to Tk 7,690 crore.

That last movement is the warning. Comparing the 34 plants estimated by both
specifications, the median ratio of the panel estimate to the per-plant
estimate is 0.78, but the tenth percentile is 0.46 and the ninetieth is 2.88.
Individual plants move by factors of two to seven: RPCL Gazipur rises from
Tk 28 crore to Tk 188 crore, Confidence Rangpur falls from Tk 482 crore to
Tk 175 crore. The aggregates are in the same territory; the plant-level numbers
are not stable, and plant-level numbers are the product.

The reason is that both specifications identify the split only from the
covariation of payment with generation. With six annual observations per plant
and shocks that hit fuel cost and the exchange rate together, the intercept and
the slope trade off against each other, and a fuel misclassification moves both.
A higher R-squared does not settle this, because the fit is dominated by the
level of payment rather than by its decomposition.

What would settle it is an external anchor: an observed capacity rate for even
a dozen plants, against which the estimator can be calibrated and the rest
checked. That is the contract layer from the listed IPPs' notes to accounts —
the step deprioritised when the BPDB payment data turned out to be disclosed.
It is now the critical path, not an optional enrichment.

## An external anchor, and what it decides (12 September 2026)

The sponsors' own audited accounts supply the anchor the purchase panel could
not. Summit Power's note 31 reports revenue plant by plant, separated into
"Sales revenue - Electricity" and "Sales revenue - HFO", with the IFRS 16
straight-lining adjustment on a third line. The HFO line is the fuel
pass-through, so whatever the capacity payment is, it must be paid out of the
electricity line. That gives a hard restriction from outside the estimator:

    CP_i <= R^elec_i

Two results follow, and the first is the more important.

BPDB's recorded payments reconcile against Summit's own revenue. Rupatoli
Tk 377 crore against 365, Madanganj Unit-2 332 against 353, Kodda Unit-1 1,393
against 1,351, Kodda Unit-2 1,535 against 1,599 — gaps of three to six per
cent, consistent with accrual timing, between two entirely independent
accounts of the same transactions. The purchase panel is not an artefact of
how BPDB keeps its books.

The ceiling then decides between the two specifications. Of the five Summit
plants that can be tested, the per-plant regression breaches the ceiling on
four, claiming a capacity payment larger than the plant's entire non-fuel
revenue — which cannot be true. The fuel-controlled panel breaches it on one,
Jangalia, and that plant stopped generating during the sample, so its
intercept is fitted on years when it was still running and BPDB paid it nothing
in FY2024-25.

The fuel-controlled estimates are therefore the ones to carry forward, not
because their R-squared is higher but because they satisfy a restriction
imposed by evidence the estimator never saw. The natural next step is to impose
the ceiling as a constraint rather than checking it after the fact, and to
widen the anchor set: United Power discloses the split more finely still —
capacity payment, fuel payment, O&M payment, energy payment, supplemental and
true-up bills — though at group rather than plant level.

Doreen and Baraka were also examined. Doreen reports plant-level revenue and
units but does not separate the capacity component; Baraka does not disclose
the split at all. Coverage of the anchor is therefore uneven across sponsors,
which is itself worth recording.

## Imposing the ceiling inside the estimator (12 September 2026)

The disclosures are now a constraint rather than an after-the-fact check. The
same specification is solved as a bounded least-squares problem,

    min  sum_it ( P_it - CP_i - v_{f(i),t} E_it )^2
    s.t. 0 <= CP_i <= R^elec_i   where the accounts disclose the ceiling
         0 <= CP_i               otherwise
         0 <= v_{f,t}

so that the five plants with known ceilings bind the fuel-year rates they share
with every other plant of the same fuel, and the non-negativity restriction
stops any intercept absorbing payment as a negative number.

The fit is essentially unchanged at an R-squared of 0.981, and the fleet total
of fixed payments moves from Tk 7,690 crore to Tk 7,851 crore. Only one of the
five ceilings binds — Jangalia, which falls from Tk 44 crore to its ceiling of
Tk 7 crore — and one non-negativity restriction binds, Haripur, whose intercept
was minus Tk 56 crore and is now zero.

Two of those small movements have a larger consequence than their size
suggests. Both bound plants burn gas, so correcting them pulls the gas energy
rate down across the series, from 1.69 to 1.51 taka per kWh in FY2019-20 and
from 5.10 to 4.94 in FY2024-25, and every gas plant's intercept rises to
compensate: Summit Meghnaghat from Tk 471 crore to 499, Bibiyana II from 176 to
226, Meghnaghat Power from 156 to 210. Five observed ceilings and one sign
restriction therefore reach plants whose accounts disclose nothing, which was
the point of putting them inside the estimator rather than beside it.

The stability question that opened this line of work is now answered. Across
the 46 plants estimated both ways, the ratio of constrained to unconstrained
estimates has a median of 1.000, a tenth percentile of 1.000 and a ninetieth of
1.19. The comparison that prompted the worry — per-plant against fuel-controlled
panel — ran 0.46 to 2.88 over the same kind of range. The specification, not the
constraint, was doing the damage; with the specification settled, the estimates
are no longer sensitive to how the restrictions are applied.

What this does not establish is the level. Every ceiling is an upper bound, so
they can rule an estimate out but never confirm one, and four of the five do not
bind at all. Tk 7,851 crore remains a figure resting on 47 plants of a larger
fleet, and confirming the level rather than bounding it still requires a
disclosed capacity rate, which none of the four sponsors examined publishes.
