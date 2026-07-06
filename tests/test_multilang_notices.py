"""Check that compliance.notice_versions has every language every pack lists.

Each loaded pack's languages.yaml declares every language the POC is
expected to cover. After running `scripts/generate_multilang_notices.py`,
each entry should produce a row in compliance.notice_versions for that
pack's own canonical notice (e.g. eu_marketing_notice, uk_marketing_notice)
v1. Machine-translated rows must carry the watermark preamble so consumers
can distinguish legal-reviewed copy from demo copy.

Runs the checks below once per loaded pack, against that pack's own
notice_id(s) and language list — a pack's notice_id is never assumed to be
a shared literal across packs.

Checks (per pack):
  1. Each language code in the pack's languages.yaml has a notice row
  2. Hand-authored (seeded_by_poc=true) rows DO NOT carry the watermark
  3. Generated (seeded_by_poc=false) rows DO carry the watermark
  4. Every body is non-empty (>100 chars — catches truncated generations)

Run:
    python3 tests/test_multilang_notices.py
    python3 tests/test_multilang_notices.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _sql import rows_or_raise  # noqa: E402
from governance_core.pack_loader import loaded_packs  # noqa: E402

WATERMARK_PREFIX = "[MACHINE-TRANSLATED"
MIN_BODY_CHARS = 100

# Content-quality signals every notice body must carry, regardless of language.
# The numbered list (items 1-6) + the regulation's citation year must survive
# any translation — if they don't, something truncated or drifted.
REQUIRED_LIST_MARKERS = ["1.", "2.", "3.", "4.", "5.", "6."]


def check_notice(pack, notice_id: str, version: int, verbose: bool) -> list[tuple[str, bool, str]]:
    """Run all notice-completeness checks for one (pack, notice_id, version)."""
    expected = {l["code"]: l.get("seeded_by_poc", False) for l in pack.languages()}
    # Derived from the pack's own effective_date rather than hardcoded, so
    # this check stays correct regardless of which pack is active.
    required_citation_year = pack.metadata.get("effective_date", "")[:4] or "2018"

    print(f"Multilang notices — pack {pack.code}, {notice_id} v{version}")
    print("=" * 70)

    # Fetch all rows for this notice+version, including the full body so we
    # can assert content-quality signals per language.
    rows = rows_or_raise(
        f"SELECT language, LENGTH(notice_text) AS chars, notice_text "
        f"FROM compliance_pack.compliance.notice_versions "
        f"WHERE notice_id = '{notice_id}' AND version_number = {version}"
    )
    by_lang: dict[str, tuple[int, str]] = {
        r[0]: (int(r[1]), r[2]) for r in rows
    }

    if verbose:
        print(f"\nPack expects {len(expected)} languages: {sorted(expected.keys())}")
        print(f"DB has {len(by_lang)} rows for this notice:")
        for lang in sorted(by_lang):
            chars, body = by_lang[lang]
            origin = "machine" if WATERMARK_PREFIX in body else "human"
            print(f"  {lang:6s}  {origin:8s}  {chars} chars")
        print()

    checks: list[tuple[str, bool, str]] = []

    # 1. Every pack language has a row.
    missing = [lang for lang in expected if lang not in by_lang]
    checks.append((
        f"Every pack-declared language ({len(expected)}) has a notice row",
        not missing,
        f"missing: {missing}" if missing else "",
    ))

    # 2. Seeded languages don't carry the machine-translation preamble.
    # Checked against the full body (not just a fixed-length prefix) since
    # the "[human-review required...]" banner for low-resource languages is
    # itself prepended before the watermark, pushing it well past any short
    # fixed-length window.
    seeded_with_wm = [
        lang for lang, seeded in expected.items()
        if seeded and lang in by_lang and WATERMARK_PREFIX in by_lang[lang][1]
    ]
    checks.append((
        "Seeded (human-authored) notices do NOT carry the machine-translation preamble",
        not seeded_with_wm,
        f"offenders: {seeded_with_wm}" if seeded_with_wm else "",
    ))

    # 3. Non-seeded languages DO carry the preamble.
    non_seeded_without_wm = [
        lang for lang, seeded in expected.items()
        if not seeded and lang in by_lang and WATERMARK_PREFIX not in by_lang[lang][1]
    ]
    checks.append((
        "Generated notices DO carry the machine-translation preamble",
        not non_seeded_without_wm,
        f"offenders: {non_seeded_without_wm}" if non_seeded_without_wm else "",
    ))

    # 4. Every body is non-trivially long (sanity check against truncated output).
    short = [lang for lang in by_lang if by_lang[lang][0] < MIN_BODY_CHARS]
    checks.append((
        f"Every notice body is at least {MIN_BODY_CHARS} characters",
        not short,
        f"short: {short}" if short else "",
    ))

    # 5. Numbered-list structure (1. through 6.) survives every translation.
    #    If a translation dropped a purpose, we want a loud signal.
    lang_missing_list = []
    for lang, (_, body) in by_lang.items():
        if not all(marker in body for marker in REQUIRED_LIST_MARKERS):
            missing_markers = [m for m in REQUIRED_LIST_MARKERS if m not in body]
            lang_missing_list.append(f"{lang}(missing={missing_markers})")
    checks.append((
        f"Every notice body contains the numbered list 1.-6.",
        not lang_missing_list,
        ", ".join(lang_missing_list) if lang_missing_list else "",
    ))

    # 6. The regulation's citation year must appear in every body — the
    #    one non-translatable anchor a regulator would look for as proof
    #    of statute reference. Script-transliterated forms (e.g. Greek,
    #    Bulgarian Cyrillic) still use Arabic digits for the year in
    #    practice. If the model localised the year into another numeral
    #    system this check would flag it for review.
    lang_missing_year = [
        lang for lang, (_, body) in by_lang.items()
        if required_citation_year not in body
    ]
    checks.append((
        f"Every notice body cites the pack's citation year '{required_citation_year}'",
        not lang_missing_year,
        f"missing: {lang_missing_year}" if lang_missing_year else "",
    ))

    return checks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    all_checks: list[tuple[str, bool, str]] = []
    for pack in loaded_packs():
        notice_keys = sorted({(n["notice_id"], int(n["version_number"])) for n in pack.notices()})
        for notice_id, version in notice_keys:
            checks = check_notice(pack, notice_id, version, args.verbose)
            all_checks.extend((f"[{pack.code}] {name}", ok, detail) for name, ok, detail in checks)
            print()

    # Report
    passed = 0
    for name, ok, detail in all_checks:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}")
        if not ok and detail:
            print(f"      {detail}")
        if ok:
            passed += 1

    print("=" * 70)
    print(f"Summary: {passed}/{len(all_checks)} checks passed")
    return 0 if passed == len(all_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
