"""Live-workspace smoke test for the multi-jurisdiction routing model (ADR-0001 M4).

This test asserts that the live workspace is actually doing per-data-subject
rule routing — not just that the code compiles. Runs against the active
Databricks workspace via the SQL Statement Execution API; expects
phase1_bootstrap to have been run after the M4 cut-over.

What's asserted:
  - silver.customers_tagged carries the `jurisdiction` column with both
    GB and EU values present (the 60/35/5 GB/EU/unmapped mix).
  - bronze.compliance_rules contains rules from BOTH eu_gdpr and uk_gdpr
    (multi-pack loader).
  - silver.compliance_gaps contains gaps tagged with regulation_pack from
    both packs (multi-pack gap engine).
  - Per-jurisdiction divergence: pack_for('EU') and pack_for('GB') resolve
    to different packs with different penalty models (€20M vs £17.5M
    higher-tier ceiling, different currencies) — loaded via the
    pack_loader, not from the workspace.

Run pre- or post-deploy. If the workspace hasn't been cut over to the
current pack set yet, the test fails clearly identifying which assertion
couldn't be satisfied.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from governance_core.pack_loader import pack_for, reset_cache  # noqa: E402
from persona_config import get_warehouse_id  # noqa: E402

WAREHOUSE_ID = get_warehouse_id()


def _sql(stmt: str, timeout_s: str = "50s") -> list[list]:
    payload = {"warehouse_id": WAREHOUSE_ID, "statement": stmt,
               "wait_timeout": timeout_s}
    path = Path("/tmp/_m4_smoke_sql.json")
    path.write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", f"@{path}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"SQL API failed: {r.stderr[:300]}")
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "?")
    if state != "SUCCEEDED":
        err = d.get("status", {}).get("error", {}).get("message", "")[:300]
        raise RuntimeError(f"SQL state={state}: {err}")
    return d.get("result", {}).get("data_array", []) or []


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _check(label: str, condition: bool, detail: str = "") -> bool:
    icon = "✓" if condition else "✗"
    print(f"  {icon} {label}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    _section(f"M4 smoke — multi-jurisdiction routing (warehouse {WAREHOUSE_ID})")
    reset_cache()

    passed = 0
    failed = 0

    # 1. customers_tagged has both GB and EU jurisdiction values
    rows = _sql(
        "SELECT jurisdiction, COUNT(*) FROM compliance_pack.silver.customers_tagged "
        "GROUP BY jurisdiction ORDER BY 2 DESC"
    )
    jur_mix = {r[0]: int(r[1]) for r in rows}
    gb_count = jur_mix.get("GB", 0)
    eu_count = jur_mix.get("EU", 0)
    if _check(f"silver.customers_tagged has GB principals (count={gb_count})",
              gb_count >= 100):
        passed += 1
    else:
        failed += 1
    if _check(f"silver.customers_tagged has EU principals (count={eu_count})",
              eu_count >= 100):
        passed += 1
    else:
        failed += 1

    # 2. Multi-pack rules loaded into compliance_rules
    rows = _sql(
        "SELECT regulation_pack, COUNT(*) FROM compliance_pack.bronze.compliance_rules "
        "GROUP BY regulation_pack"
    )
    rule_mix = {r[0]: int(r[1]) for r in rows}
    eu_rules = rule_mix.get("eu_gdpr", 0)
    uk_rules = rule_mix.get("uk_gdpr", 0)
    if _check(f"bronze.compliance_rules has EU GDPR rules (count={eu_rules})",
              eu_rules >= 14):
        passed += 1
    else:
        failed += 1
    if _check(f"bronze.compliance_rules has UK GDPR rules (count={uk_rules})",
              uk_rules >= 12):
        passed += 1
    else:
        failed += 1

    # 3. Gaps are tagged with regulation_pack from both packs
    rows = _sql(
        "SELECT regulation_pack, COUNT(*) FROM compliance_pack.silver.compliance_gaps "
        "GROUP BY regulation_pack ORDER BY 2 DESC"
    )
    gap_mix = {r[0]: int(r[1]) for r in rows}
    eu_gaps = gap_mix.get("eu_gdpr", 0)
    uk_gaps = gap_mix.get("uk_gdpr", 0)
    if _check(f"silver.compliance_gaps tagged with eu_gdpr (count={eu_gaps})",
              eu_gaps >= 50):
        passed += 1
    else:
        failed += 1
    if _check(f"silver.compliance_gaps tagged with uk_gdpr (count={uk_gaps})",
              uk_gaps >= 50):
        passed += 1
    else:
        failed += 1

    # 4. Per-jurisdiction divergence — pack-loader-side assertion, proves
    #    the architecture's per-row decision rule. Retention defaults are
    #    identical between eu_gdpr and uk_gdpr in this repo (UK GDPR
    #    retained EU GDPR's provisions closely), so the discriminating
    #    signal is the penalty model instead: different ceiling amounts
    #    AND different currencies.
    eu_pack = pack_for("EU")
    gb_pack = pack_for("GB")
    if _check("pack_for('EU') resolves to eu_gdpr",
              eu_pack is not None and eu_pack.code == "eu_gdpr",
              f"got {eu_pack.code if eu_pack else None!r}"):
        passed += 1
    else:
        failed += 1
    if _check("pack_for('GB') resolves to uk_gdpr",
              gb_pack is not None and gb_pack.code == "uk_gdpr",
              f"got {gb_pack.code if gb_pack else None!r}"):
        passed += 1
    else:
        failed += 1

    eu_penalty = (eu_pack.metadata.get("max_penalty") or [{}])[0] if eu_pack else {}
    gb_penalty = (gb_pack.metadata.get("max_penalty") or [{}])[0] if gb_pack else {}
    if _check(
        f"EU GDPR higher-tier penalty = €20M, got {eu_penalty.get('amount')} {eu_penalty.get('currency')}",
        eu_penalty.get("amount") == 20_000_000 and eu_penalty.get("currency") == "EUR",
    ):
        passed += 1
    else:
        failed += 1
    if _check(
        f"UK GDPR higher-tier penalty = £17.5M, got {gb_penalty.get('amount')} {gb_penalty.get('currency')}",
        gb_penalty.get("amount") == 17_500_000 and gb_penalty.get("currency") == "GBP",
    ):
        passed += 1
    else:
        failed += 1
    if _check(
        f"Per-jurisdiction divergence proven: {eu_penalty.get('currency')} vs {gb_penalty.get('currency')}",
        eu_penalty.get("currency") != gb_penalty.get("currency"),
    ):
        passed += 1
    else:
        failed += 1

    print()
    print("=" * 70)
    if failed:
        print(f"FAIL · {failed}/{passed + failed} checks failed")
        return 1
    print(f"OK · {passed}/{passed + failed} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
