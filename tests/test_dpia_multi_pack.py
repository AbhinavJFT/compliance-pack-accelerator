"""Unit tests for the DPIA core's multi-pack wiring (ADR-0001 follow-up).

Validates ``governance_core.dpia._resolve_dpia_packs`` — the pure helper
that picks the DPIATemplate + contributing pack codes for one DPIA run.

This is what closes the "merger exists but isn't wired into the
productionised pipeline" gap: the helper is the single point where
``run_dpia_generation`` decides whether to call ``template_for_activity``
or fall back to a single pack, so tests against this surface protect the
quarterly cron from regressing into single-pack-by-default behaviour.

Runs without Databricks. No serializer overhead. Stays under 1 second.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from governance_core.dpia import _resolve_dpia_packs  # noqa: E402
from governance_core.pack_loader import loaded_packs, reset_cache  # noqa: E402


def setup_function(_fn) -> None:
    reset_cache()


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------------
# Default path: jurisdiction-derived multi-pack
# ---------------------------------------------------------------------------

def test_resolve_in_only_single_pack() -> None:
    """IN-only data → single pack, dpdp_2023, no merger."""
    template, packs = _resolve_dpia_packs(
        jurisdiction_breakdown=[{"jurisdiction": "IN", "principal_count": 3500}]
    )
    assert packs == ["dpdp_2023"], packs
    assert "+" not in template.legal_framework_name, (
        "single-pack template should not have merged framework name"
    )
    print(f"  ✓ IN-only data → packs={packs}, framework={template.legal_framework_name!r}")


def test_resolve_in_gb_eu_merged() -> None:
    """Mixed IN/GB/EU → 3 contributing packs, merged template emits the ADR-0001 marker."""
    template, packs = _resolve_dpia_packs(
        jurisdiction_breakdown=[
            {"jurisdiction": "IN", "principal_count": 3500},
            {"jurisdiction": "GB", "principal_count": 1250},
            {"jurisdiction": "EU", "principal_count": 800},
        ]
    )
    assert set(packs) == {"dpdp_2023", "uk_gdpr", "eu_gdpr"}, packs
    assert packs[0] == "dpdp_2023", f"DPDP should be primary (hoisted), got {packs[0]}"
    # The merger injects a "Multi-regulation scope (ADR-0001)" paragraph
    # into the system_prompt — that's a reliable single-vs-merged signal.
    # (Checking framework_name for "+" is unreliable: UK GDPR's name is
    # natively "UK GDPR + DPA 2018".)
    assert "Multi-regulation scope" in template.system_prompt, (
        "merged template's system_prompt should carry the ADR-0001 marker"
    )
    print(f"  ✓ IN+GB+EU → packs={packs}, merged-marker present")


def test_resolve_null_jurisdictions_ignored() -> None:
    """NULL jurisdictions don't pollute pack selection — IN+NULL collapses to IN."""
    template, packs = _resolve_dpia_packs(
        jurisdiction_breakdown=[
            {"jurisdiction": "IN", "principal_count": 3500},
            {"jurisdiction": None, "principal_count": 239},
        ]
    )
    assert packs == ["dpdp_2023"], packs
    print(f"  ✓ IN + NULL → packs={packs} (NULL filtered)")


def test_resolve_fully_unmapped_falls_back_to_primary() -> None:
    """All-NULL data → fallback to primary loaded pack (dpdp_2023), not crash."""
    template, packs = _resolve_dpia_packs(
        jurisdiction_breakdown=[{"jurisdiction": None, "principal_count": 100}]
    )
    expected_primary = loaded_packs()[0].code
    assert packs == [expected_primary], packs
    print(f"  ✓ all-NULL → fallback packs={packs} (primary={expected_primary})")


def test_resolve_empty_breakdown_falls_back_to_primary() -> None:
    """Empty breakdown (no rows) also falls back, doesn't IndexError."""
    template, packs = _resolve_dpia_packs(jurisdiction_breakdown=[])
    expected_primary = loaded_packs()[0].code
    assert packs == [expected_primary], packs
    print(f"  ✓ empty breakdown → fallback packs={packs}")


# ---------------------------------------------------------------------------
# Single-pack escape hatches
# ---------------------------------------------------------------------------

def test_resolve_regulation_pack_override_forces_single_pack() -> None:
    """regulation_pack='uk_gdpr' override → that pack only, ignoring data."""
    template, packs = _resolve_dpia_packs(
        regulation_pack="uk_gdpr",
        jurisdiction_breakdown=[
            {"jurisdiction": "IN", "principal_count": 3500},
            {"jurisdiction": "GB", "principal_count": 1250},
        ],
    )
    assert packs == ["uk_gdpr"], packs
    # Single-pack mode → no merger marker in the prompt (see note in
    # test_resolve_in_gb_eu_merged for why this is the right signal).
    assert "Multi-regulation scope" not in template.system_prompt, (
        "single-pack override should not emit the merger marker"
    )
    print(f"  ✓ regulation_pack='uk_gdpr' override → packs={packs} (data ignored, no merger)")


def test_resolve_unknown_regulation_pack_raises() -> None:
    """regulation_pack='bogus' → ValueError listing loaded packs (no silent fallback)."""
    try:
        _resolve_dpia_packs(regulation_pack="bogus_pack")
    except ValueError as e:
        assert "bogus_pack" in str(e), str(e)
        assert "loaded packs" in str(e), str(e)
        print(f"  ✓ unknown override → ValueError: {str(e)[:80]}...")
        return
    raise AssertionError("Expected ValueError, got no exception")


def test_resolve_explicit_pack_wins() -> None:
    """pack= explicit takes precedence over both regulation_pack and breakdown."""
    primary = loaded_packs()[0]
    template, packs = _resolve_dpia_packs(
        pack=primary,
        regulation_pack="uk_gdpr",  # should be ignored
        jurisdiction_breakdown=[{"jurisdiction": "GB", "principal_count": 1000}],
    )
    assert packs == [primary.code], packs
    print(f"  ✓ pack= explicit beats regulation_pack and breakdown → packs={packs}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [
        test_resolve_in_only_single_pack,
        test_resolve_in_gb_eu_merged,
        test_resolve_null_jurisdictions_ignored,
        test_resolve_fully_unmapped_falls_back_to_primary,
        test_resolve_empty_breakdown_falls_back_to_primary,
        test_resolve_regulation_pack_override_forces_single_pack,
        test_resolve_unknown_regulation_pack_raises,
        test_resolve_explicit_pack_wins,
    ]
    _section("DPIA core — multi-pack wiring (ADR-0001 follow-up)")
    failures = []
    for t in tests:
        setup_function(t)
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, e))
            print(f"  ✗ {t.__name__}: {e}")
    print()
    print("=" * 70)
    if failures:
        print(f"FAIL · {len(failures)}/{len(tests)} test(s) failed")
        for name, err in failures:
            print(f"  - {name}: {err}")
        return 1
    print(f"OK · {len(tests)}/{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
