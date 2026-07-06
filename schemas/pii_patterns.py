"""PII pattern library — composition shim over governance_core + every loaded pack.

This file is the single import point for consumers. It re-exports the
PIIPattern dataclass, taxonomy constants, confidence calculation, and
threshold tuning constants from `governance_core.pii_patterns.universal`,
and composes the final `PATTERN_LIBRARY` as
`UNIVERSAL_PATTERNS + every loaded pack's pii_patterns()`.

Consumers (`pipelines/classification_dlt.py`, `scripts/apply_pii_masks.py`,
`scripts/apply_uc_tags.py`) import from `pii_patterns` exactly as before —
the module's public API is unchanged. What moved is where the values live:

    Before:    schemas/pii_patterns.py  (monolithic — 16 patterns inline)
    After:     governance_core/pii_patterns/universal.py  (11 universal)
             + regulations/<pack>/pii_patterns.py         (region-specific)
             + this file                                  (composition shim)

ADR-0001 loads every pack under regulations/ simultaneously and routes each
principal to their own pack by jurisdiction — so the classifier must scan
for every loaded pack's region-specific patterns at once, not just the
single REGULATION_PACK-selected "active" one. Using only active_pack()
here meant uk_gdpr's 5 UK-specific patterns (NHS number, National
Insurance number, UK postcode, UK driving licence, UTR) were never even
attempted on a live deploy where REGULATION_PACK defaults to eu_gdpr —
confirmed live: genuinely valid NHS numbers went undetected in
patients_tagged. Adding a new pack to regulations/ now needs zero changes
here, matching ALL_RULES' existing multi-pack loop in phase1_bootstrap.py.

Usage (unchanged for consumers):
    from pii_patterns import PATTERN_LIBRARY, calculate_confidence, redact_sample
    for pattern in PATTERN_LIBRARY:
        ...
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional


# -----------------------------------------------------------------------------
# Path resolution — locate repo root (where governance_core/ lives) on sys.path
# so imports work whether this file is loaded from the repo root locally, from
# /Workspace/.../files/schemas/ under a Databricks bundle, or from a sys-path
# manipulation in classification_dlt.py.
# -----------------------------------------------------------------------------
def _locate_repo_root() -> Optional[str]:
    here = Path(__file__).resolve()
    for parent in (here.parent.parent, here.parent, Path.cwd(), Path.cwd().parent):
        if (parent / "governance_core").is_dir():
            return str(parent)
    return None


_repo_root = _locate_repo_root()
if _repo_root and _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


# -----------------------------------------------------------------------------
# Re-exports from governance_core (backward-compatible public API)
# -----------------------------------------------------------------------------
from governance_core.pii_patterns.universal import (  # noqa: E402
    PIIPattern,
    UNIVERSAL_PATTERNS,
    CATEGORY_DIRECT_GOV,
    CATEGORY_DIRECT_CONTACT,
    CATEGORY_DIRECT_FIN,
    CATEGORY_INDIRECT,
    CATEGORY_BIOMETRIC,
    CATEGORY_HEALTH,
    CATEGORY_SENSITIVE_DEMO,
    CATEGORY_FIN_BEHAVIOR,
    CATEGORY_CHILDREN,
    SENSITIVITY_CRITICAL,
    SENSITIVITY_HIGH,
    SENSITIVITY_MEDIUM,
    SENSITIVITY_LOW,
    AUTO_CLASSIFY_THRESHOLD,
    REVIEW_REQUIRED_THRESHOLD,
    CANDIDATE_THRESHOLD,
    calculate_confidence,
)
from governance_core.pack_loader import loaded_packs  # noqa: E402


# -----------------------------------------------------------------------------
# Composed pattern library — universal + every loaded pack's region-specific
# patterns. Duplicate pattern_ids across packs (shouldn't happen — each pack's
# ids are its own region's names) keep the first-seen pack's definition.
# -----------------------------------------------------------------------------
_packs = loaded_packs()
_region_patterns: list[PIIPattern] = []
_seen_pattern_ids: set[str] = set()
for _p in _packs:
    for _pattern in _p.pii_patterns():
        if _pattern.pattern_id not in _seen_pattern_ids:
            _region_patterns.append(_pattern)
            _seen_pattern_ids.add(_pattern.pattern_id)
PATTERN_LIBRARY: list[PIIPattern] = list(UNIVERSAL_PATTERNS) + _region_patterns


# Back-compat re-exports of individual pattern objects — some callers reference
# these by name. Populated from the composed library so the names resolve
# whichever pack is active.
_by_id: dict[str, PIIPattern] = {p.pattern_id: p for p in PATTERN_LIBRARY}
EMAIL_PATTERN          = _by_id.get("email")
PHONE_INTL_PATTERN     = _by_id.get("phone_intl")
CREDIT_CARD_PATTERN    = _by_id.get("credit_card")
CVV_PATTERN            = _by_id.get("cvv")
BANK_ACCOUNT_PATTERN   = _by_id.get("bank_account")
NAME_PATTERN           = _by_id.get("name")
ADDRESS_PATTERN        = _by_id.get("address")
DOB_PATTERN            = _by_id.get("dob")
IP_ADDRESS_PATTERN     = _by_id.get("ip_address")
MEDICAL_RECORD_PATTERN = _by_id.get("medical_record")
INSURANCE_ID_PATTERN   = _by_id.get("insurance_id")


# =============================================================================
# Sample redaction — keep raw PII out of pii_findings
# =============================================================================
# Redactions for pii_types universally known (email, phone, credit_card, name,
# address, ip_address). When a new region pack adds a pii_type with
# region-specific formatting (NHS, NINO, IBAN), add a case here or have the
# pack provide its own redactor (a future refinement).

def redact_sample(value: str, pii_type: str) -> str:
    """Return a redacted version of a matched sample, safe to store in pii_findings."""
    if value is None:
        return ""
    v = str(value)

    if pii_type == "credit_card":
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 12:
            return f"{digits[:4]}{'X' * (len(digits) - 8)}{digits[-4:]}"
        return "[card redacted]"

    if pii_type == "phone":
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 4:
            return f"{'X' * (len(digits) - 4)}{digits[-4:]}"
        return "[phone redacted]"

    if pii_type == "email":
        if "@" in v:
            local, domain = v.split("@", 1)
            return f"{local[:2]}{'*' * max(0, len(local) - 2)}@{domain}"
        return "[email redacted]"

    if pii_type == "name":
        if v:
            return f"{v[0]}{'X' * max(0, len(v) - 1)}"
        return "[name redacted]"

    if pii_type == "address":
        return (v[:5] + "...") if len(v) > 5 else "[address redacted]"

    if pii_type == "ip_address":
        parts = v.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.X.X"
        return "[ip redacted]"

    return f"[{len(v)} chars]"


# =============================================================================
# Pattern lookup helpers
# =============================================================================

def get_pattern_by_id(pattern_id: str) -> Optional[PIIPattern]:
    """Return the pattern with the given id, or None if not found."""
    for p in PATTERN_LIBRARY:
        if p.pattern_id == pattern_id:
            return p
    return None


def patterns_by_column_name(column_name: str) -> list[PIIPattern]:
    """Return patterns whose column hints match the column name, by priority desc."""
    return sorted(
        [p for p in PATTERN_LIBRARY if p.matches_column_name(column_name)],
        key=lambda p: p.priority,
        reverse=True,
    )
