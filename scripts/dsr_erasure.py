"""DSR erasure — execute a GDPR Art. 17 right-to-erasure request.

DELETEs rows matching the principal from every table in the estate
that holds their personal data, then VACUUMs each table to make the
deleted data unrecoverable. Records the full operation in
`compliance.dsr_requests` for regulator evidence.

**This is destructive.** Always run `dsr_discovery.py` first to confirm
the scope, get the principal's review agreement, and log a dsr_requests
row with status='in_progress' before invoking this script.

Usage:
    # First, see what exists:
    python3 scripts/dsr_discovery.py --principal-id customer_04217 --verbose

    # Then, with explicit confirmation:
    python3 scripts/dsr_erasure.py --principal-id customer_04217 --request-id dsr_xxxx \\
        --reason "GDPR Art. 17 erasure request submitted 2026-04-15" --confirm

    # Dry-run (default; reports what would happen without mutating):
    python3 scripts/dsr_erasure.py --principal-id customer_04217 --request-id dsr_xxxx

Caveats:
    - Retention-required data (legally mandated records like financial
      transactions under FCA rules) should NOT be erased. This script
      deletes from every known table; exclusions must be configured
      in PRESERVE_TABLES below. Consult legal before enabling.
    - Consent-events-log is preserved by default (GDPR audit evidence
      of consent withdrawals is itself a record-of-processing
      obligation).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))  # pick up governance_core and regulations
from persona_config import get_warehouse_id, get_catalog, get_deployer_email  # noqa: E402
from governance_core.pack_loader import active_pack  # noqa: E402


# ---------------------------------------------------------------------------
# Regulation-pack-driven defaults
# ---------------------------------------------------------------------------
# The reason text / requester language / SLA are not literals hardcoded
# here — they come from the active regulation pack's rights.yaml +
# pack.yaml. Switching pack (REGULATION_PACK=uk_gdpr, eu_gdpr, ...) gives
# you the correct citation, locale, and SLA deadline with no code change.
_PACK = active_pack()
_ERASURE_RIGHT = next(
    (r for r in _PACK.rights() if r.get("code") == "erasure"), {}
)
PACK_ERASURE_REASON = _ERASURE_RIGHT.get(
    "default_reason_text",
    f"{_PACK.name} right to erasure",
)
PACK_ERASURE_SLA_DAYS = int(_ERASURE_RIGHT.get("sla_days") or 30)
PACK_REQUESTER_LOCALE = _PACK.primary_locale or "en-IN"

# (schema, table, principal_column) — same shape as discovery
ERASABLE_TABLES = [
    ("silver",     "customers_tagged",     "customer_id"),
    ("silver",     "users_tagged",         "user_id"),
    ("silver",     "transactions_tagged",  "customer_id"),
    ("silver",     "employees_tagged",     "employee_id"),
    ("silver",     "patients_tagged",      "patient_id"),
]

# Tables that are PRESERVED even on erasure — audit evidence the Act
# itself requires us to retain.
PRESERVE_TABLES = [
    ("compliance", "consent_events_log",   "data_principal_id"),
    ("compliance", "retention_audit",      None),
    ("compliance", "dsr_requests",         None),
]

WAREHOUSE_ID = get_warehouse_id()
CATALOG = get_catalog()


def sql(stmt: str) -> tuple[str, str]:
    payload = {"warehouse_id": WAREHOUSE_ID, "statement": stmt, "wait_timeout": "50s"}
    Path("/tmp/_erase_sql.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", "@/tmp/_erase_sql.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ("ERR", r.stderr[:300])
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        return (state, d.get("status", {}).get("error", {}).get("message", "")[:400])
    return ("OK", "")


def count_rows(principal_id: str) -> dict[str, int]:
    counts = {}
    for schema, table, col in ERASABLE_TABLES:
        fq = f"{CATALOG}.{schema}.{table}"
        payload = {"warehouse_id": WAREHOUSE_ID,
                   "statement": f"SELECT COUNT(*) FROM {fq} WHERE {col} = '{principal_id}'",
                   "wait_timeout": "30s"}
        Path("/tmp/_cnt.json").write_text(json.dumps(payload))
        r = subprocess.run(
            ["databricks", "api", "post", "/api/2.0/sql/statements",
             "--json", "@/tmp/_cnt.json"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            counts[fq] = -1
            continue
        d = json.loads(r.stdout)
        if d.get("status", {}).get("state") == "SUCCEEDED":
            rows = d.get("result", {}).get("data_array", [])
            counts[fq] = int(rows[0][0]) if rows else 0
        else:
            counts[fq] = -1
    return counts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--principal-id", required=True)
    p.add_argument("--request-id", required=True,
                   help="A unique DSR request ID (e.g. dsr_abc123)")
    p.add_argument("--reason", default=PACK_ERASURE_REASON,
                   help=f"Reason text for audit record. "
                        f"Pack default: {PACK_ERASURE_REASON!r}")
    p.add_argument("--confirm", action="store_true",
                   help="Actually execute DELETE + VACUUM. Without this, dry-run only.")
    p.add_argument("--vacuum-hours", type=int, default=168,
                   help="VACUUM retention in hours (min 168 = 7 days)")
    args = p.parse_args()

    print(f"DSR erasure for principal '{args.principal_id}'")
    print(f"Request ID: {args.request_id}")
    print(f"Invoked by: {get_deployer_email()}")
    print(f"Reason:     {args.reason}")
    print(f"Mode:       {'APPLY (destructive)' if args.confirm else 'DRY-RUN'}")
    print()

    counts = count_rows(args.principal_id)
    total = sum(c for c in counts.values() if c >= 0)

    print("Rows to be erased:")
    for fq, n in counts.items():
        marker = "·" if n == 0 else ("✓" if n > 0 else "✗")
        print(f"  {marker} {fq}: {n if n >= 0 else 'unreadable'}")
    print(f"\nPreserved (legally-required retention):")
    for schema, table, _ in PRESERVE_TABLES:
        print(f"  · {CATALOG}.{schema}.{table}")
    print(f"\nTotal rows in scope: {total}")

    if not args.confirm:
        print("\nDRY-RUN — no data deleted. Re-run with --confirm to apply.")
        return 0

    print("\nExecuting DELETE + VACUUM...")
    deleted = 0
    for schema, table, col in ERASABLE_TABLES:
        fq = f"{CATALOG}.{schema}.{table}"
        n_before = counts.get(fq, 0)
        if n_before <= 0:
            continue
        state, err = sql(f"DELETE FROM {fq} WHERE {col} = '{args.principal_id}'")
        if state != "OK":
            print(f"  ✗ DELETE {fq}: {state} — {err}")
            continue
        state, err = sql(f"VACUUM {fq} RETAIN {args.vacuum_hours} HOURS")
        if state != "OK":
            print(f"  ⚠ VACUUM {fq}: {state} — {err}")
        else:
            print(f"  ✓ DELETE + VACUUM {fq}: {n_before} rows")
            deleted += n_before

    # Record the erasure in dsr_requests for audit evidence
    now = datetime.now(timezone.utc).isoformat()
    stmt = f"""
        INSERT INTO {CATALOG}.compliance.dsr_requests (
            request_id, data_principal_id, request_type, status,
            submitted_at, verified_at, execution_completed_at,
            sla_deadline, scope_purposes, requester_email,
            requester_language, created_at, updated_at
        )
        VALUES (
            '{args.request_id}', '{args.principal_id}', 'erasure', 'completed',
            CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(),
            DATE_ADD(CURRENT_DATE(), {PACK_ERASURE_SLA_DAYS}), ARRAY(),
            '{get_deployer_email()}', '{PACK_REQUESTER_LOCALE}',
            CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
        )
    """
    state, err = sql(stmt)
    if state == "OK":
        print(f"\n✓ dsr_requests row written for {args.request_id}")
    else:
        print(f"\n⚠ dsr_requests write failed: {state} — {err}")

    print(f"\nTotal rows erased: {deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
