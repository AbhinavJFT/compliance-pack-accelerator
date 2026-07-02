"""Shared SQL-statements-API helper for executable integration tests.

Runs SQL against the workspace's serverless warehouse via the Databricks CLI
`databricks api post /api/2.0/sql/statements`. No Spark session, no PySpark
install — just the CLI, which every teammate already has configured.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from persona_config import get_warehouse_id  # noqa: E402

_WAREHOUSE_ID: str | None = None


def warehouse_id() -> str:
    global _WAREHOUSE_ID
    if _WAREHOUSE_ID is None:
        _WAREHOUSE_ID = get_warehouse_id()
    return _WAREHOUSE_ID


def sql(stmt: str, wait_timeout: str = "30s") -> tuple[str, list, str]:
    """Run a SQL statement. Returns (state, rows, error_message).

    state: "OK" on success, otherwise the API-reported state ("FAILED", "CANCELED", ...)
           or "ERR" if the CLI call itself failed.
    rows:  list of row arrays on success, [] otherwise.
    error_message: truncated error from the API/CLI on failure.
    """
    payload = {"warehouse_id": warehouse_id(), "statement": stmt, "wait_timeout": wait_timeout}
    Path("/tmp/_compliance_sql.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", "@/tmp/_compliance_sql.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ("ERR", [], r.stderr[:300])
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        msg = d.get("status", {}).get("error", {}).get("message", "")[:300]
        return (state, [], msg)
    return ("OK", d.get("result", {}).get("data_array", []) or [], "")


def rows_or_raise(stmt: str) -> list:
    """Run a SQL statement, raise RuntimeError on any non-OK state, return rows."""
    state, rows, err = sql(stmt)
    if state != "OK":
        raise RuntimeError(f"SQL failed [{state}] for `{stmt[:120]}...`: {err}")
    return rows
