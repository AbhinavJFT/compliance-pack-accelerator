"""India-specific PII patterns for the DPDP 2023 pack.

Patterns that are meaningful under DPDP but not universal. Universal patterns
(email, phone-international, credit card, name, address, DOB, IP, medical,
insurance) live in `governance_core/pii_patterns/universal.py` and are
composed with `IN_SPECIFIC_PATTERNS` below at load time by
`schemas/pii_patterns.py`.

Five entries:
  AADHAAR         — 12-digit identity number, DPDP §4 sensitive ID
  PAN             — Permanent Account Number (tax)
  PASSPORT_INDIA  — Indian passport format (A-PRWY + digit 1-9 + 6 digits)
  IFSC            — Indian bank routing code (4 letters + 0 + 6 alphanumeric)
  PHONE_INDIA     — Indian mobile (+91 prefix optional, leading 6-9)

Each pattern uses the universal PIIPattern dataclass + category/sensitivity
constants. Adding a new regulation pack (UK GDPR, CCPA) follows the same
template — copy this file, replace the 5 entries with region-specific
patterns (NHS, NINO, UK-postcode, UTR for UK; SSN, ITIN, US driver's licence
for US; SIN, postal code for Canada; etc.).
"""

from __future__ import annotations

from governance_core.pii_patterns.universal import (
    PIIPattern,
    CATEGORY_DIRECT_CONTACT,
    CATEGORY_DIRECT_FIN,
    CATEGORY_DIRECT_GOV,
    SENSITIVITY_CRITICAL,
    SENSITIVITY_HIGH,
    SENSITIVITY_MEDIUM,
)


AADHAAR_PATTERN = PIIPattern(
    pattern_id="aadhaar",
    pii_type="aadhaar",
    category=CATEGORY_DIRECT_GOV,
    sensitivity=SENSITIVITY_CRITICAL,
    # First digit 2-9 (0 and 1 not issued); 12 digits total with optional space/hyphen
    regex_pattern=r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b",
    column_hints=["aadhaar", "aadhar", "uid_number"],
    regulations=["DPDP"],
    description="Aadhaar Number (India)",
    priority=100,
)

PAN_PATTERN = PIIPattern(
    pattern_id="pan",
    pii_type="pan",
    category=CATEGORY_DIRECT_GOV,
    sensitivity=SENSITIVITY_CRITICAL,
    regex_pattern=r"\b[A-Z]{5}\d{4}[A-Z]\b",
    column_hints=["pan", "pan_number", "pan_card"],
    regulations=["DPDP"],
    description="PAN Card (India)",
    priority=99,
)

PASSPORT_INDIA_PATTERN = PIIPattern(
    pattern_id="passport_india",
    pii_type="passport",
    category=CATEGORY_DIRECT_GOV,
    sensitivity=SENSITIVITY_CRITICAL,
    regex_pattern=r"\b[A-PR-WY][1-9]\d{6}\b",
    column_hints=["passport", "passport_number", "passport_no"],
    regulations=["DPDP"],
    description="Indian Passport Number",
    priority=98,
)

IFSC_PATTERN = PIIPattern(
    pattern_id="ifsc",
    pii_type="ifsc_code",
    category=CATEGORY_DIRECT_FIN,
    sensitivity=SENSITIVITY_HIGH,
    regex_pattern=r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    column_hints=["ifsc", "ifsc_code", "routing_code"],
    regulations=["DPDP"],
    description="IFSC Code (India)",
    priority=90,
)

PHONE_INDIA_PATTERN = PIIPattern(
    pattern_id="phone_india",
    pii_type="phone",
    category=CATEGORY_DIRECT_CONTACT,
    sensitivity=SENSITIVITY_MEDIUM,
    regex_pattern=r"(?:\+91[-.\s]?)?[6-9]\d{9}\b",
    column_hints=["phone", "mobile", "cell", "contact_number", "msisdn", "contact_phone"],
    regulations=["DPDP", "GDPR", "CCPA"],
    description="Indian Mobile Number",
    priority=85,
)


IN_SPECIFIC_PATTERNS: list[PIIPattern] = [
    AADHAAR_PATTERN,
    PAN_PATTERN,
    PASSPORT_INDIA_PATTERN,
    IFSC_PATTERN,
    PHONE_INDIA_PATTERN,
]
