#!/usr/bin/env python3
"""Compliance Pack POC — synthetic Salesforce-shaped data generator.

Represents what Lakeflow Connect Salesforce ingestion would deliver to
Bronze in production. Self-contained: this script writes nothing — it
returns lists of dicts. The seeder in `scripts/seed_salesforce_data.py`
is the consumer; it pushes the rows into UC tables via SQL.

Three Salesforce standard objects, mirrored 1:1:

  Lead     — prospect, has personal PII (lead's identity)
  Contact  — known person at a customer account, FK → Account
  Account  — company/org, has a business identifier (VAT number)

All values are deterministic (seed=43 — separate from the medallion
generator's seed=42 to keep namespaces independent), and obviously fake
but format-matching so the classifier's pattern library catches them
end-to-end.

Usage as library::

    from generate_salesforce_data import generate
    payload = generate(seed=43)        # → {"leads": [...], "contacts": [...], "accounts": [...]}

CLI for inspection::

    python3 generate_salesforce_data.py --counts
    python3 generate_salesforce_data.py --sample lead 5

Counts default to 100 leads / 60 contacts / 30 accounts (per BACKLOG).
"""

from __future__ import annotations

import argparse
import json
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Defaults (matched to BACKLOG P0 / Day 3)
# ---------------------------------------------------------------------------
DEFAULT_SEED = 43
DEFAULT_LEADS = 100
DEFAULT_CONTACTS = 60
DEFAULT_ACCOUNTS = 30
GENERATOR_DATE = date(2026, 4, 27)
TZ = timezone.utc

# ---------------------------------------------------------------------------
# UK-specific reference data (subset — repeats are fine for a synthetic set)
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Oliver", "George", "Harry", "Jack", "Jacob", "Noah", "Charlie", "Muhammad",
    "Thomas", "Oscar", "William", "James", "Leo", "Alfie", "Henry",
    "Olivia", "Amelia", "Isla", "Ava", "Emily", "Isabella", "Mia", "Poppy",
    "Ella", "Lily", "Charlotte", "Freya", "Grace", "Evie", "Sophia",
    "Sarah", "David", "Emma", "Daniel", "Rebecca", "Michael", "Laura",
]
LAST_NAMES = [
    "Smith", "Jones", "Williams", "Brown", "Taylor", "Davies", "Wilson",
    "Evans", "Thomas", "Johnson", "Roberts", "Walker", "Wright", "Robinson",
    "Thompson", "White", "Hughes", "Edwards", "Green", "Hall", "Wood",
    "Harris", "Clarke", "Patel", "Jackson", "Turner", "Cooper", "Ward",
]
COMPANY_PREFIXES = [
    "Anchor", "Trident", "Albion", "Nimbus", "Granite", "Thistle", "Beacon",
    "Indigo", "Crimson", "Helix", "Polaris", "Quanta", "Vertex", "Zenith",
    "Foxglove", "Catalyst", "Oasis", "Fulcrum", "Mosaic", "Ridgeline",
]
COMPANY_SUFFIXES = [
    "Technologies", "Industries", "Solutions", "Systems", "Logistics",
    "Pharma", "Foods", "Bank", "Capital", "Healthcare", "Retail",
    "Energy", "Telecom", "Infrastructure", "Holdings", "Networks",
]
INDUSTRIES = [
    "Banking", "Insurance", "Healthcare", "Pharma", "Retail", "E-commerce",
    "Manufacturing", "Telecom", "Education", "Logistics", "FinTech",
    "Hospitality", "Real Estate",
]
JOB_TITLES = [
    "Chief Technology Officer", "VP Engineering", "Head of Data",
    "Director of Compliance", "Senior Software Engineer", "Product Manager",
    "Data Engineer", "Chief Privacy Officer", "Legal Counsel",
    "Marketing Manager", "Procurement Manager", "Operations Lead",
]
LEAD_STATUSES = ["new", "working", "qualified", "unqualified", "converted"]
LEAD_SOURCES = ["web", "referral", "event", "outbound", "partner", "linkedin"]
UK_REGIONS = [
    "Greater London", "Greater Manchester", "West Midlands", "West Yorkshire",
    "Merseyside", "South Yorkshire", "Tyne and Wear", "Strathclyde",
    "Edinburgh", "Glasgow City", "Cardiff", "Belfast",
]
UK_CITIES = {
    "Greater London": ["London"],
    "Greater Manchester": ["Manchester", "Salford"],
    "West Midlands": ["Birmingham", "Coventry"],
    "West Yorkshire": ["Leeds", "Bradford"],
    "Merseyside": ["Liverpool"],
    "South Yorkshire": ["Sheffield"],
    "Tyne and Wear": ["Newcastle"],
    "Strathclyde": ["Glasgow"],
    "Edinburgh": ["Edinburgh"],
    "Glasgow City": ["Glasgow"],
    "Cardiff": ["Cardiff"],
    "Belfast": ["Belfast"],
}


def _uk_postcode(rng: random.Random) -> str:
    """UK postcode in canonical A9 9AA / AA9 9AA form."""
    area = rng.choice([
        "SW1A", "EC1A", "W1A", "WC1H", "NW1", "SE1", "E14", "N1", "M1",
        "B1", "L1", "G1", "EH1", "CF10", "BT1", "OX1", "CB2", "BS1",
    ])
    sector = rng.randint(0, 9)
    unit = "".join(rng.choices("ABDEFGHJLNPQRSTUWXYZ", k=2))
    return f"{area} {sector}{unit}"


# ---------------------------------------------------------------------------
# UK-PII format helpers (formats only — values are random/fake)
# ---------------------------------------------------------------------------

def _vat_number(rng: random.Random) -> str:
    """UK VAT registration number: 'GB' + 9 digits."""
    return "GB" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def _phone_uk(rng: random.Random) -> str:
    """+44 7XXX XXXXXX, mobile prefix 7."""
    rest = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return f"+44 7{rest[:3]} {rest[3:]}"


def _email(rng: random.Random, first: str, last: str, company_slug: str) -> str:
    suffix = rng.randint(0, 99)
    return f"{first.lower()}.{last.lower()}{suffix:02d}@{company_slug}.example.com"


def _company_name(rng: random.Random) -> str:
    return f"{rng.choice(COMPANY_PREFIXES)} {rng.choice(COMPANY_SUFFIXES)}"


def _company_slug(name: str) -> str:
    return name.lower().split()[0]


def _region_city(rng: random.Random) -> tuple[str, str, str]:
    region = rng.choice(UK_REGIONS)
    return region, rng.choice(UK_CITIES[region]), _uk_postcode(rng)


def _date_in_window(rng: random.Random, start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, delta))


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def _generate_accounts(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(n):
        name = _company_name(rng)
        region, city, postcode = _region_city(rng)
        out.append({
            "account_id":         f"001{i:08d}",
            "name":                name,
            "industry":            rng.choice(INDUSTRIES),
            "annual_revenue":      float(rng.randint(50, 50_000)) * 1_000,  # £ thousands
            "num_employees":       rng.randint(20, 25_000),
            "billing_city":        city,
            "billing_state":       region,
            "billing_country":     "United Kingdom",
            "billing_postal_code": postcode,
            "vat_number":          _vat_number(rng),
            "primary_phone":       _phone_uk(rng),
            "website":             f"https://www.{_company_slug(name)}.example.com",
            "created_date":        _date_in_window(rng, date(2023, 1, 1), GENERATOR_DATE).isoformat(),
        })
    return out


def _generate_contacts(rng: random.Random, n: int, accounts: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(n):
        first = rng.choice(FIRST_NAMES)
        last  = rng.choice(LAST_NAMES)
        acct  = rng.choice(accounts)
        slug  = _company_slug(acct["name"])
        out.append({
            "contact_id":         f"003{i:08d}",
            "account_id":          acct["account_id"],
            "first_name":          first,
            "last_name":           last,
            "email":               _email(rng, first, last, slug),
            "phone":               _phone_uk(rng),
            "mobile":              _phone_uk(rng),
            "title":               rng.choice(JOB_TITLES),
            "mailing_city":        acct["billing_city"],
            "mailing_state":       acct["billing_state"],
            "mailing_country":     "United Kingdom",
            "mailing_postal_code": acct["billing_postal_code"],
            "date_of_birth":       _date_in_window(rng, date(1965, 1, 1), date(2002, 12, 31)).isoformat(),
            "created_date":        _date_in_window(rng, date(2024, 1, 1), GENERATOR_DATE).isoformat(),
        })
    return out


def _generate_leads(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(n):
        first = rng.choice(FIRST_NAMES)
        last  = rng.choice(LAST_NAMES)
        company = _company_name(rng)
        slug = _company_slug(company)
        region, city, postcode = _region_city(rng)
        out.append({
            "lead_id":         f"00Q{i:08d}",
            "first_name":      first,
            "last_name":       last,
            "email":           _email(rng, first, last, slug),
            "phone":           _phone_uk(rng),
            "mobile":          _phone_uk(rng),
            "company":         company,
            "industry":        rng.choice(INDUSTRIES),
            "title":           rng.choice(JOB_TITLES),
            "lead_status":     rng.choice(LEAD_STATUSES),
            "lead_source":     rng.choice(LEAD_SOURCES),
            "lead_score":      rng.randint(1, 100),
            "annual_revenue":  float(rng.randint(50, 50_000)) * 1_000,
            "num_employees":   rng.randint(10, 10_000),
            "city":            city,
            "state":           region,
            "country":         "United Kingdom",
            "postal_code":     postcode,
            "created_date":    _date_in_window(rng, date(2025, 1, 1), GENERATOR_DATE).isoformat(),
        })
    return out


def generate(
    seed: int = DEFAULT_SEED,
    leads: int = DEFAULT_LEADS,
    contacts: int = DEFAULT_CONTACTS,
    accounts: int = DEFAULT_ACCOUNTS,
) -> dict[str, list[dict[str, Any]]]:
    """Return the three SF object lists in dependency order."""
    rng = random.Random(seed)
    acct_rows = _generate_accounts(rng, accounts)
    contact_rows = _generate_contacts(rng, contacts, acct_rows)
    lead_rows = _generate_leads(rng, leads)
    return {"accounts": acct_rows, "contacts": contact_rows, "leads": lead_rows}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--counts", action="store_true", help="just print row counts")
    p.add_argument("--sample", nargs=2, metavar=("OBJECT", "N"),
                   help="dump first N rows of OBJECT (lead|contact|account) as JSON")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = p.parse_args()

    payload = generate(seed=args.seed)

    if args.sample:
        obj, n = args.sample
        key = {"lead": "leads", "contact": "contacts", "account": "accounts"}.get(obj, obj)
        if key not in payload:
            raise SystemExit(f"unknown object: {obj}")
        print(json.dumps(payload[key][: int(n)], indent=2, default=str))
        return 0

    print(f"Generated (seed={args.seed}):")
    for k, rows in payload.items():
        print(f"  {k:10s} {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
