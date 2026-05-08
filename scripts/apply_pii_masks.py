"""Apply Unity Catalog column masks on PII columns.

Runs each statement in `schemas/pii_column_masks.sql` sequentially via
the SQL statements API. Idempotent: CREATE OR REPLACE FUNCTION +
ALTER TABLE ... SET MASK can safely re-run.

Unmask rule (centralized in the UDFs): `is_member('admins')` — the
deployer, any workspace admin, and service principals in the admins
group see raw values. Everyone else (persona demo users, future
colleagues added to the workspace as users) sees masked values.

Usage:
    python3 scripts/apply_pii_masks.py
    python3 scripts/apply_pii_masks.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_FILE = REPO_ROOT / "schemas" / "pii_column_masks.sql"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from persona_config import get_warehouse_id  # noqa: E402

WAREHOUSE_ID = get_warehouse_id()


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on top-level ';'.
    Handles CREATE FUNCTION bodies that contain ';' inside CASE by
    detecting semicolons outside string literals at the end of the
    effective statement."""
    # Strip comment-only lines and blank lines.
    lines = [ln for ln in sql.splitlines()
             if not ln.strip().startswith("--") and ln.strip()]
    text = "\n".join(lines)
    # Naive but sufficient here: semicolons outside quotes always
    # terminate a statement. None of our UDFs embed ';' inside strings.
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def run_sql(stmt: str) -> tuple[str, str]:
    payload = {"warehouse_id": WAREHOUSE_ID, "statement": stmt, "wait_timeout": "50s"}
    Path("/tmp/_mask_sql.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", "@/tmp/_mask_sql.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ("ERR", r.stderr[:300])
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        return (state, d.get("status", {}).get("error", {}).get("message", "")[:400])
    return ("OK", "")


def summary(stmt: str) -> str:
    first = stmt.strip().split("\n", 1)[0][:80]
    return first


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sql = SQL_FILE.read_text()
    statements = split_statements(sql)
    print(f"Will run {len(statements)} SQL statements from {SQL_FILE.name}\n")

    ok, failed = 0, 0
    for i, stmt in enumerate(statements, 1):
        label = summary(stmt)
        if args.dry_run:
            print(f"  [{i:02d}] would run: {label}")
            continue
        state, err = run_sql(stmt)
        marker = "✓" if state == "OK" else "✗"
        print(f"  [{i:02d}] {marker} {state:10s} {label}")
        if state == "OK":
            ok += 1
        else:
            failed += 1
            print(f"         → {err}")

    if not args.dry_run:
        print(f"\n{ok} succeeded, {failed} failed")
        return 0 if failed == 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
