"""Apply workspace-level ACLs that complete the persona boundary.

Three surfaces, applied per persona:

  1. SQL warehouse CAN_USE — so the persona user can execute the
     dashboard's queries once the dashboard runs as the viewer
     (i.e. embed_credentials=false, see step 2).

  2. Lakeview dashboard:
     - Re-publish with embed_credentials=false so queries run as the
       viewer and UC enforces (rather than running as the dashboard
       owner with their grants).
     - ACL: CAN_READ for the matching persona user. The deployer
       (owner) keeps CAN_MANAGE so they can edit/publish later.

  3. Genie space CAN_RUN — so the persona user can open the space
     and ask questions, but not edit it.

Reads:
    dashboards/personas/.persona_emails.json   ← from setup_persona_users.py
    dashboards/personas/.dashboard_ids.json    ← from slice_dashboards.py --upload
    dashboards/personas/.genie_space_ids.json  ← from setup_persona_genie_spaces.py

Idempotent: Databricks' permission-PATCH merges, PUT replaces. Safe to
re-run after any of the three surfaces is regenerated.

Usage:
    python scripts/apply_persona_workspace_acls.py
    python scripts/apply_persona_workspace_acls.py --persona cco
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONAS_DIR = REPO_ROOT / "dashboards" / "personas"
EMAILS_FILE = PERSONAS_DIR / ".persona_emails.json"
DASH_IDS_FILE = PERSONAS_DIR / ".dashboard_ids.json"
GENIE_IDS_FILE = PERSONAS_DIR / ".genie_space_ids.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from persona_config import get_warehouse_id, get_deployer_email  # noqa: E402

WAREHOUSE_ID = get_warehouse_id()


def api(method: str, path: str, body: dict | None = None) -> dict | None:
    """Call databricks api subcommand. Returns parsed JSON or raises."""
    cmd = ["databricks", "api", method, path]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{method.upper()} {path} failed: {r.stderr[:400]}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def patch_warehouse_can_use(email: str) -> None:
    """Grant CAN_USE on the warehouse. PATCH is additive — existing
    entries (including the deployer's CAN_MANAGE) are preserved."""
    body = {"access_control_list": [{"user_name": email, "permission_level": "CAN_USE"}]}
    api("patch", f"/api/2.0/permissions/warehouses/{WAREHOUSE_ID}", body)


def republish_dashboard(dashboard_id: str) -> None:
    """Re-publish with embed_credentials=false (UC enforces at query time)."""
    api("post",
        f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
        {"warehouse_id": WAREHOUSE_ID, "embed_credentials": False})


def set_dashboard_acl(dashboard_id: str, persona_email: str, deployer_email: str) -> None:
    """PUT: replace the full ACL with CAN_READ for persona + CAN_MANAGE for deployer.

    PUT is a full replace on dashboard perms. Anyone else previously on
    the ACL is removed — which is the point: we're enforcing the
    boundary."""
    body = {"access_control_list": [
        {"user_name": persona_email,  "permission_level": "CAN_READ"},
        {"user_name": deployer_email, "permission_level": "CAN_MANAGE"},
    ]}
    api("put", f"/api/2.0/permissions/dashboards/{dashboard_id}", body)


def patch_genie_can_run(space_id: str, email: str) -> None:
    """PATCH: add CAN_RUN for the persona user. Admin CAN_MANAGE is
    inherited from the parent directory and stays."""
    body = {"access_control_list": [{"user_name": email, "permission_level": "CAN_RUN"}]}
    api("patch", f"/api/2.0/permissions/genie/{space_id}", body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", choices=["cco", "gc", "cmo", "cfo"],
                        help="only apply ACLs for this persona (default: all)")
    args = parser.parse_args()

    for f in (EMAILS_FILE, DASH_IDS_FILE, GENIE_IDS_FILE):
        if not f.exists():
            print(f"error: {f} not found — run the prerequisite scripts first",
                  file=sys.stderr)
            return 1

    emails = json.loads(EMAILS_FILE.read_text())
    dashboards = json.loads(DASH_IDS_FILE.read_text())
    spaces = json.loads(GENIE_IDS_FILE.read_text())
    deployer = get_deployer_email()
    print(f"deployer (owner, CAN_MANAGE on all dashboards): {deployer}")

    personas = [args.persona] if args.persona else list(emails.keys())
    for persona in personas:
        email = emails.get(persona)
        dashboard_id = dashboards.get(persona)
        space_id = spaces.get(persona)

        if not all([email, dashboard_id, space_id]):
            print(f"[{persona}] missing mapping (email/dashboard/space), skipping")
            continue

        print(f"\n=== {persona} → {email} ===")

        patch_warehouse_can_use(email)
        print(f"  [1/4] warehouse CAN_USE")

        republish_dashboard(dashboard_id)
        print(f"  [2/4] dashboard republished (embed_credentials=false)")

        set_dashboard_acl(dashboard_id, email, deployer)
        print(f"  [3/4] dashboard ACL: persona=CAN_READ, deployer=CAN_MANAGE")

        patch_genie_can_run(space_id, email)
        print(f"  [4/4] Genie space CAN_RUN")

    print("\nDone. Verify via:")
    print("  databricks api get /api/2.0/permissions/dashboards/<id>")
    print("  databricks api get /api/2.0/permissions/genie/<id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
