"""
Derived-layer computations over the plant spine.

Every function here is a closed-form identity applied to contract terms. None
of it estimates anything: if a contract term is not known, it must be supplied
explicitly by the caller, and the provenance of that term travels with it.

Definitions
-----------
CP_t  = 12 * c * C * 1000 * e_t          annual capacity payment, local currency
E_t   = C * 8760 * PF_t                  energy delivered, MWh
k_t   = CP_t / (E_t * 1000)              capacity charge per kWh delivered
dCP/de = 12 * c * C * 1000               local-currency cost of one unit of
                                         depreciation, per year
PV    = sum_{t=1..T} CP_t / (1+r)^t      present value of remaining obligation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

HOURS_PER_YEAR = 8760


@dataclass(frozen=True)
class ContractTerms:
    """Contract terms for one plant. `source` records where each came from."""

    plant_id: str
    capacity_mw: float
    cod: date
    ppa_years: int
    cap_rate_usd_kw_month: float
    currency: str = "USD"          # currency the capacity rate is set in
    offtaker: str = "BPDB"
    source: str = ""               # document reference, e.g. "Summit AR2023-24 n1.3"
    estimated_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def expiry(self) -> date:
        return date(
            self.cod.year + self.ppa_years, self.cod.month, self.cod.day
        )

    def years_remaining(self, asof: date) -> float:
        return max(0.0, (self.expiry - asof).days / 365.25)


def annual_capacity_payment(t: ContractTerms, fx: float = 1.0) -> float:
    """CP_t = 12 * c * C * 1000 * e_t. Returns local currency if fx given."""
    return 12 * t.cap_rate_usd_kw_month * t.capacity_mw * 1000 * fx


def energy_delivered_mwh(t: ContractTerms, plant_factor: float) -> float:
    """E_t = C * 8760 * PF_t."""
    return t.capacity_mw * HOURS_PER_YEAR * plant_factor


def capacity_charge_per_kwh(t: ContractTerms, plant_factor: float, fx: float = 1.0) -> float:
    """k_t = CP_t / E_t, expressed per kWh."""
    e_kwh = energy_delivered_mwh(t, plant_factor) * 1000
    if e_kwh <= 0:
        return float("inf")
    return annual_capacity_payment(t, fx) / e_kwh


def fx_sensitivity(t: ContractTerms) -> float:
    """dCP/de: local-currency cost per year of one unit of depreciation."""
    if t.currency != "USD":
        return 0.0
    return 12 * t.cap_rate_usd_kw_month * t.capacity_mw * 1000


def pv_remaining_obligation(
    t: ContractTerms, asof: date, discount_rate: float, fx: float = 1.0
) -> float:
    """PV of capacity payments from asof to expiry, discounted annually."""
    years = t.years_remaining(asof)
    if years <= 0:
        return 0.0
    cp = annual_capacity_payment(t, fx)
    whole, stub = int(years), years - int(years)
    pv = sum(cp / (1 + discount_rate) ** n for n in range(1, whole + 1))
    if stub > 0:
        pv += cp * stub / (1 + discount_rate) ** (whole + 1)
    return pv


def obligation_path(
    terms: list[ContractTerms], start_year: int, end_year: int, fx: float = 1.0
) -> dict[int, float]:
    """Fleet-wide capacity payment owed in each calendar year to end_year."""
    path = {y: 0.0 for y in range(start_year, end_year + 1)}
    for t in terms:
        cp = annual_capacity_payment(t, fx)
        for y in range(start_year, end_year + 1):
            if t.cod.year <= y < t.expiry.year:
                path[y] += cp
            elif y == t.expiry.year:
                path[y] += cp * (t.expiry.month - 1) / 12
    return path


def expiry_calendar(terms: list[ContractTerms]) -> dict[int, float]:
    """MW of contracted capacity reaching PPA expiry in each year."""
    cal: dict[int, float] = {}
    for t in terms:
        cal[t.expiry.year] = cal.get(t.expiry.year, 0.0) + t.capacity_mw
    return dict(sorted(cal.items()))
