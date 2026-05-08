"""DSR discovery — find every row about a data principal across the estate.

Implements Phase 1 of a DPDP §11/§12 Data Subject Request (access /
correction / erasure). Given a principal identifier, walks the PII
register to find tables/columns that hold personal data, then searches
each for rows matching the principal.

Emits a JSON bundle with:
    - requested principal identifier
    - per-table row counts
    - per-table matched rows (with column masks applied if caller
      isn't an admin — DSR fulfilment must respect data minimisation)
    - timestamp + UC scan metadata

Subject to DPDP §12 — the bundle itself IS the access response for
access requests. For erasure requests, run `dsr_erasure.py` after
discovery confirms the scope.

Usage:
    python3 scripts/dsr_discovery.py --principal-id customer_04217
    python3 scripts/dsr_discovery.py --principal-id customer_04217 --output /tmp/bundle.json

Notes:
    - Discovery queries run as the invoking user. If the caller is a
      persona, UC column masks apply — the discovery bundle reflects
      what THAT persona would see, not the raw values. Run as admin
      for an access-response bundle with raw PII.
    - For real production DSR hubs, this would be triggered by the
      DSR portal and run as a service principal with broader grants.
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
from persona_config import get_warehouse_id, get_catalog  # noqa: E402

# Tables to search and the column holding the principal's ID.
# The synthetic POC uses customer_id / user_id / patient_id /
# employee_id / data_principal_id depending on table. Real DPDP
# deployments extend this map as new sources onboard.
DEFAULT_PRINCIPAL_TABLES = [
    ("silver",     "customers_tagged",     "customer_id"),
    ("silver",     "users_tagged",         "user_id"),
    ("silver",     "transactions_tagged",  "customer_id"),
    ("silver",     "employees_tagged",     "employee_id"),
    ("silver",     "patients_tagged",      "patient_id"),
    ("compliance", "consent_events_log",   "data_principal_id"),
]

WAREHOUSE_ID = get_warehouse_id()
CATALOG = get_catalog()


def sql(stmt: str) -> tuple[str, list, list]:
    """Return (state, columns, rows)."""
    payload = {"warehouse_id": WAREHOUSE_ID, "statement": stmt, "wait_timeout": "30s"}
    Path("/tmp/_dsr_sql.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", "@/tmp/_dsr_sql.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ("ERR", [], [r.stderr[:200]])
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        return (state, [], [d.get("status", {}).get("error", {}).get("message", "")[:300]])
    cols = [c["name"] for c in d.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = d.get("result", {}).get("data_array", []) or []
    return ("OK", cols, rows)


def discover_principal(principal_id: str, verbose: bool = False) -> dict:
    bundle = {
        "principal_id": principal_id,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "catalog": CATALOG,
        "scan_results": [],
        "total_matching_rows": 0,
    }

    for schema, table, id_col in DEFAULT_PRINCIPAL_TABLES:
        fq = f"{CATALOG}.{schema}.{table}"
        stmt = (
            f"SELECT * FROM {fq} "
            f"WHERE {id_col} = '{principal_id}' LIMIT 100"
        )
        state, cols, rows = sql(stmt)

        entry = {"table": fq, "id_column": id_col, "state": state}
        if state == "OK":
            entry["row_count"] = len(rows)
            entry["columns"] = cols
            entry["rows"] = [dict(zip(cols, r)) for r in rows]
            bundle["total_matching_rows"] += len(rows)
            marker = "✓" if rows else "·"
            if verbose:
                print(f"  {marker} {fq}: {len(rows)} rows")
        else:
            entry["error"] = rows[0] if rows else ""
            if verbose:
                print(f"  ✗ {fq}: {state} — {entry['error']}")

        bundle["scan_results"].append(entry)

    return bundle


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--principal-id", required=True,
                   help="Principal identifier (e.g. customer_04217)")
    p.add_argument("--output", default=None,
                   help="Write JSON bundle to this path (default: stdout)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.verbose:
        print(f"Discovering personal data for principal '{args.principal_id}'...")
        print(f"Scanning {len(DEFAULT_PRINCIPAL_TABLES)} tables in {CATALOG}:")

    bundle = discover_principal(args.principal_id, verbose=args.verbose)

    summary = (
        f"\nDSR discovery summary: {bundle['total_matching_rows']} rows "
        f"found across {len([e for e in bundle['scan_results'] if e.get('row_count', 0) > 0])} "
        f"tables."
    )
    if args.verbose:
        print(summary)

    output = json.dumps(bundle, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Bundle written to {args.output} ({len(output)} bytes)")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
