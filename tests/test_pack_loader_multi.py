"""Local unit tests for the multi-pack loader (ADR-0001 M1).

Runs without Databricks. Validates the new accessors that ADR-0001 added:
- derive_jurisdiction(country) — country → pack code
- loaded_packs() — every pack under regulations/
- pack_for(jurisdiction) — pack lookup by jurisdiction
- active_pack() — backward-compat primary-pack accessor

These tests pin the contract that downstream pipelines, scripts, and the
DLT silver materialiser depend on. If you change the loader's public
surface, change these tests in the same commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from governance_core.pack_loader import (  # noqa: E402
    DEFAULT_PACK_CODE,
    Pack,
    active_pack,
    derive_jurisdiction,
    loaded_packs,
    pack_for,
    reset_cache,
)


def setup_function(_fn) -> None:
    """Clear the loader cache before each test so loaded_packs() actually
    re-reads the filesystem."""
    reset_cache()


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------------
# derive_jurisdiction
# ---------------------------------------------------------------------------

def test_derive_jurisdiction_india_variants() -> None:
    for ci in ("IN", "in", "India", "INDIA", "ind", " India "):
        got = derive_jurisdiction(ci)
        assert got == "IN", f"derive_jurisdiction({ci!r}) → {got!r}, expected 'IN'"
    print("  ✓ derive_jurisdiction maps every India variant to 'IN'")


def test_derive_jurisdiction_uk_variants() -> None:
    for ci in ("GB", "UK", "United Kingdom", "england", "Scotland", "wales"):
        got = derive_jurisdiction(ci)
        assert got == "GB", f"derive_jurisdiction({ci!r}) → {got!r}, expected 'GB'"
    print("  ✓ derive_jurisdiction maps every UK variant to 'GB'")


def test_derive_jurisdiction_us_variants() -> None:
    for ci in ("US", "usa", "United States", "america"):
        got = derive_jurisdiction(ci)
        assert got == "US", f"derive_jurisdiction({ci!r}) → {got!r}, expected 'US'"
    print("  ✓ derive_jurisdiction maps every US variant to 'US'")


def test_derive_jurisdiction_eu_member_states() -> None:
    samples = ("Germany", "FR", "italy", "Spain", "Sweden", "Iceland", "Norway")
    for ci in samples:
        got = derive_jurisdiction(ci)
        assert got == "EU", f"derive_jurisdiction({ci!r}) → {got!r}, expected 'EU'"
    print(f"  ✓ derive_jurisdiction maps {len(samples)} EU/EEA members to 'EU'")


def test_derive_jurisdiction_null_and_blank_and_unmapped() -> None:
    for ci in (None, "", "  ", "Atlantis", "Wakanda"):
        got = derive_jurisdiction(ci)
        assert got is None, f"derive_jurisdiction({ci!r}) → {got!r}, expected None"
    print("  ✓ derive_jurisdiction returns None for NULL/blank/unmapped")


# ---------------------------------------------------------------------------
# loaded_packs / pack_for / active_pack
# ---------------------------------------------------------------------------

def test_loaded_packs_finds_dpdp() -> None:
    packs = loaded_packs()
    codes = [p.code for p in packs]
    assert DEFAULT_PACK_CODE in codes, (
        f"loaded_packs() returned {codes}, expected to include '{DEFAULT_PACK_CODE}'"
    )
    print(f"  ✓ loaded_packs() finds {len(packs)} pack(s): {codes}")


def test_loaded_packs_hoists_default_to_position_zero() -> None:
    packs = loaded_packs()
    assert packs, "loaded_packs() returned empty"
    assert packs[0].code == DEFAULT_PACK_CODE, (
        f"primary pack should be {DEFAULT_PACK_CODE}, got {packs[0].code}"
    )
    print(f"  ✓ {DEFAULT_PACK_CODE} is hoisted to position 0 (primary pack)")


def test_loaded_packs_each_has_metadata() -> None:
    for p in loaded_packs():
        assert isinstance(p, Pack)
        assert p.code, f"pack at {p.path} has empty code"
        assert p.metadata, f"pack {p.code} has empty metadata"
        assert p.jurisdiction, f"pack {p.code} has no jurisdiction declared"
    print(f"  ✓ every loaded pack has code + metadata + jurisdiction populated")


def test_pack_for_routes_in_to_dpdp() -> None:
    p = pack_for("IN")
    assert p is not None, "pack_for('IN') returned None — DPDP pack not loaded?"
    assert p.code == "dpdp_2023", f"pack_for('IN') → {p.code}, expected 'dpdp_2023'"
    print("  ✓ pack_for('IN') routes to dpdp_2023")


def test_pack_for_returns_none_for_unmapped() -> None:
    for jur in ("ZZ", "ATLANTIS", "", None):
        got = pack_for(jur)
        assert got is None, f"pack_for({jur!r}) → {got!r}, expected None"
    print("  ✓ pack_for returns None for unmapped/blank/NULL jurisdictions")


def test_pack_for_returns_none_when_only_dpdp_loaded() -> None:
    """UK GDPR pack lands in M2; until then pack_for('GB') is None."""
    if pack_for("GB") is None:
        print("  ✓ pack_for('GB') is None — uk_gdpr pack not yet loaded (expected pre-M2)")
    else:
        print("  ✓ pack_for('GB') resolves — uk_gdpr pack is loaded")


def test_active_pack_backward_compat() -> None:
    p = active_pack()
    assert p is not None
    assert p.code == DEFAULT_PACK_CODE, (
        f"active_pack() → {p.code}, expected primary pack {DEFAULT_PACK_CODE}"
    )
    print(f"  ✓ active_pack() returns the primary pack ({DEFAULT_PACK_CODE})")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    _section("M1 unit — pack_loader multi-pack accessors (ADR-0001)")

    failures = 0
    tests = [
        test_derive_jurisdiction_india_variants,
        test_derive_jurisdiction_uk_variants,
        test_derive_jurisdiction_us_variants,
        test_derive_jurisdiction_eu_member_states,
        test_derive_jurisdiction_null_and_blank_and_unmapped,
        test_loaded_packs_finds_dpdp,
        test_loaded_packs_hoists_default_to_position_zero,
        test_loaded_packs_each_has_metadata,
        test_pack_for_routes_in_to_dpdp,
        test_pack_for_returns_none_for_unmapped,
        test_pack_for_returns_none_when_only_dpdp_loaded,
        test_active_pack_backward_compat,
    ]
    for t in tests:
        setup_function(t)
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failures += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {t.__name__}: unexpected {type(e).__name__}: {e}")
            failures += 1

    print()
    print("=" * 70)
    if failures:
        print(f"FAIL · {failures}/{len(tests)} tests failed")
        return 1
    print(f"OK · {len(tests)}/{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
