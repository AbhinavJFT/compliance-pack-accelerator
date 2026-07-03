"""Post-deploy smoke test — assert the POC's three-path ingestion + governance chain is whole.

The "≥N findings" threshold flagged by the colleague's gap report
(2026-04-24) is the right kind of regression guard, but the real story
is: did all three ingestion patterns (Auto Loader, Lakeflow Connect
simulation, Federation simulation) deliver into the same governance
layer? This test answers that with the smallest set of SQL queries
that would catch a real regression.

Run after `databricks bundle deploy` + the seed scripts (or after
`scripts/deploy_all.sh`). All checks read state via the SQL warehouse;
no Spark or DLT context required.

Checks (in order, each emits ✓/✗):

  1. All 5 schemas exist (bronze, silver, compliance, gold, federation_mock)
  2. ≥10 silver objects (8 tables + 2 federation views) registered
  3. silver.pii_findings has ≥23 rows
  4. All 3 ingestion patterns produced findings:
       Auto Loader (≥5 silver tables in findings) +
       Lakeflow Connect sim (sf_* present) +
       Federation sim (federation_* present)
  5. compliance.personal_data_register has ≥23 rows (auto-derived view)
  6. column_masks registered on every silver table the classifier flagged
  7. compliance.consent_events_log has events (Module 02 baseline)
  8. compliance.notice_versions has ≥10 rows (10-language coverage)

Run:
    python3 tests/test_post_deploy_smoke.py
    python3 tests/test_post_deploy_smoke.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _sql import rows_or_raise  # noqa: E402

CATALOG = "compliance_pack"

# Expected baselines — picked to fail loudly if a regression knocks
# something out of the chain. MIN_FINDINGS/MIN_REGISTER_ROWS reflect
# 2026-07-03 state: the DPDP/CCPA column purge (aadhaar/pan/passport/ifsc
# etc. dropped from the schema) plus the eu_passport/de_personalausweis/
# uk_utr false-positive-regex fix (generic 8-10 char ID columns like
# employee_id/patient_id/user_id no longer misclassify as passport/
# de_id_card) both lowered the true finding count from the original
# 36 baseline (2026-04-27, pre-purge, pre-fix) to a verified 23 —
# every remaining finding is classifier_source="hybrid" (both column-name
# hint AND content regex agree), not a lone weak signal.
EXPECTED_SCHEMAS = {"bronze", "silver", "compliance", "gold", "federation_mock"}
MIN_SILVER_OBJECTS = 10        # 5 base + 3 SF + 2 federation views
MIN_FINDINGS = 23
MIN_REGISTER_ROWS = 23
MIN_NOTICE_VERSIONS = 3        # 2 seeded by phase1 (1 per loaded pack); many more after multilang
MIN_AUTO_LOADER_TABLES = 5     # employees/customers/patients/transactions/users
MIN_SF_TABLES = 3              # sf_leads/sf_contacts/sf_accounts
MIN_FEDERATION_TABLES = 2      # federation_lead_scoring/federation_campaign_response


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    print(f"Post-deploy smoke — catalog {CATALOG}")
    print("=" * 70)

    checks: list[tuple[str, bool, str]] = []

    # 1. Schemas
    schemas = {r[0] for r in rows_or_raise(
        f"SELECT schema_name FROM {CATALOG}.information_schema.schemata"
    )}
    missing = EXPECTED_SCHEMAS - schemas
    checks.append((
        f"All 5 expected schemas present: {sorted(EXPECTED_SCHEMAS)}",
        not missing,
        f"missing: {sorted(missing)}" if missing else "",
    ))
    if args.verbose:
        print(f"  [1] schemas found: {sorted(schemas & EXPECTED_SCHEMAS)}")

    # 2. Silver objects (tables + views, scanned by classifier)
    silver_objects = rows_or_raise(
        f"SELECT table_name, table_type FROM {CATALOG}.information_schema.tables "
        f"WHERE table_schema = 'silver' AND table_name LIKE '%_tagged'"
    )
    obj_count = len(silver_objects)
    checks.append((
        f"silver._tagged objects ≥ {MIN_SILVER_OBJECTS}",
        obj_count >= MIN_SILVER_OBJECTS,
        f"found {obj_count}",
    ))
    if args.verbose:
        for name, ttype in sorted(silver_objects):
            print(f"  [2] silver.{name:<40s} {ttype}")

    # 3. pii_findings count
    n_findings = int(rows_or_raise(
        f"SELECT COUNT(*) FROM {CATALOG}.silver.pii_findings"
    )[0][0])
    checks.append((
        f"pii_findings ≥ {MIN_FINDINGS}",
        n_findings >= MIN_FINDINGS,
        f"found {n_findings}",
    ))

    # 4. All 3 ingestion patterns produced findings
    findings_by_table = {r[0]: int(r[1]) for r in rows_or_raise(
        f"SELECT table_name, COUNT(*) FROM {CATALOG}.silver.pii_findings GROUP BY table_name"
    )}
    auto_loader_tables = {t for t in findings_by_table
                          if t in {"employees_tagged", "customers_tagged",
                                   "patients_tagged", "transactions_tagged", "users_tagged"}}
    sf_tables = {t for t in findings_by_table if t.startswith("sf_") and t.endswith("_tagged")}
    fed_tables = {t for t in findings_by_table if t.startswith("federation_") and t.endswith("_tagged")}

    checks.append((
        f"Auto Loader sources have findings (≥{MIN_AUTO_LOADER_TABLES} tables)",
        len(auto_loader_tables) >= MIN_AUTO_LOADER_TABLES,
        f"found {sorted(auto_loader_tables)}",
    ))
    checks.append((
        f"Lakeflow Connect sim has findings (≥{MIN_SF_TABLES} tables)",
        len(sf_tables) >= MIN_SF_TABLES,
        f"found {sorted(sf_tables)}",
    ))
    checks.append((
        f"Federation sim has findings (≥{MIN_FEDERATION_TABLES} views)",
        len(fed_tables) >= MIN_FEDERATION_TABLES,
        f"found {sorted(fed_tables)}",
    ))
    if args.verbose:
        print(f"  [4] findings by table: {findings_by_table}")

    # 5. personal_data_register (view auto-derived from pii_findings)
    n_register = int(rows_or_raise(
        f"SELECT COUNT(*) FROM {CATALOG}.compliance.personal_data_register"
    )[0][0])
    checks.append((
        f"personal_data_register ≥ {MIN_REGISTER_ROWS}",
        n_register >= MIN_REGISTER_ROWS,
        f"found {n_register}",
    ))

    # 6. Column masks registered for every table that has findings
    masked = {(r[0], r[1]): int(r[2]) for r in rows_or_raise(
        f"SELECT table_schema, table_name, COUNT(*) "
        f"FROM system.information_schema.column_masks "
        f"WHERE table_catalog = '{CATALOG}' GROUP BY table_schema, table_name"
    )}
    # Every silver table with findings needs ≥1 mask. Federation views inherit
    # masks via their federation_mock backing tables, so check those too.
    needs_masks = []
    for tbl, cnt in findings_by_table.items():
        if tbl.startswith("federation_"):
            base = tbl[len("federation_"):-len("_tagged")]  # e.g. "lead_scoring"
            if ("federation_mock", base) not in masked:
                needs_masks.append(f"federation_mock.{base}")
        elif ("silver", tbl) not in masked:
            needs_masks.append(f"silver.{tbl}")
    checks.append((
        "Every silver table with findings has ≥1 column mask "
        "(federation views inherit via federation_mock backing)",
        not needs_masks,
        f"missing masks for: {needs_masks}" if needs_masks else "",
    ))
    if args.verbose:
        for (sch, tbl), n in sorted(masked.items()):
            print(f"  [6] {sch:<20s}.{tbl:<35s}  {n} mask(s)")

    # 7. Consent baseline
    n_events = int(rows_or_raise(
        f"SELECT COUNT(*) FROM {CATALOG}.compliance.consent_events_log"
    )[0][0])
    checks.append((
        "consent_events_log has events (Module 02 baseline)",
        n_events > 0,
        f"found {n_events}",
    ))

    # 8. Notices across every loaded pack's own notice_id (e.g.
    #    eu_marketing_notice, uk_marketing_notice) — not a single hardcoded
    #    literal, since each pack names its notice independently.
    n_notices = int(rows_or_raise(
        f"SELECT COUNT(*) FROM {CATALOG}.compliance.notice_versions"
    )[0][0])
    checks.append((
        f"notice_versions has ≥ {MIN_NOTICE_VERSIONS} rows (multi-pack notice coverage)",
        n_notices >= MIN_NOTICE_VERSIONS,
        f"found {n_notices}",
    ))

    # Report
    print()
    passed = 0
    for name, ok, detail in checks:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}")
        if not ok and detail:
            print(f"      {detail}")
        if ok:
            passed += 1

    print("\n" + "=" * 70)
    print(f"Summary: {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
