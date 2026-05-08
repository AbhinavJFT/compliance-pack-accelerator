"""Inject a 'Ask the {Persona} Agent' banner on each persona dashboard
that links to the persona's Genie space.

Lakeview dashboards and Genie spaces don't have a native attachment API
(the `genie_space_id` PATCH is silently ignored). The reliable way to
surface the agent from the dashboard is to add a markdown textbox tile
at the top of the first canvas page, with a prominent link to the
Genie space URL.

Idempotent: if the banner widget already exists on a page, it's
updated rather than duplicated. Safe to re-run after regenerating the
dashboard slices.

Usage:
    python scripts/attach_genie_to_dashboards.py           # all personas
    python scripts/attach_genie_to_dashboards.py --persona cco
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONAS_DIR = REPO_ROOT / "dashboards" / "personas"
DASH_IDS_FILE = PERSONAS_DIR / ".dashboard_ids.json"
GENIE_IDS_FILE = PERSONAS_DIR / ".genie_space_ids.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from persona_config import get_workspace_url, get_warehouse_id  # noqa: E402

WORKSPACE_URL = get_workspace_url()
WAREHOUSE_ID = get_warehouse_id()

BANNER_TEXT = {
    "cco": (
        "### Ask the [CCO Agent →]({space_url})\n"
        "Compliance posture, PII register, gap remediation. Natural-language "
        "queries powered by AI/BI Genie, scoped to CCO data only."
    ),
    "gc": (
        "### Ask the [General Counsel Agent →]({space_url})\n"
        "Legal exposure, DSR procedures, consent-withdrawal evidence, notice "
        "versions. AI/BI Genie scoped to GC data only."
    ),
    "cmo": (
        "### Ask the [CMO Agent →]({space_url})\n"
        "Marketing-eligible audience, consent by purpose, campaign-safe "
        "segmentation. AI/BI Genie scoped to CMO data only."
    ),
    "cfo": (
        "### Ask the [CFO Agent →]({space_url})\n"
        "Penalty exposure, gap counts weighted by DPDP ceilings, remediation "
        "cost. AI/BI Genie scoped to CFO data only."
    ),
}

BANNER_WIDGET_NAME_PREFIX = "genie-banner-"


def banner_widget(persona: str, space_id: str) -> dict:
    space_url = f"{WORKSPACE_URL}/genie/rooms/{space_id}"
    return {
        "widget": {
            "name": f"{BANNER_WIDGET_NAME_PREFIX}{persona}",
            "textbox_spec": BANNER_TEXT[persona].format(space_url=space_url),
        },
        "position": {"x": 0, "y": 0, "width": 6, "height": 1},
    }


def first_canvas_page(serialized: dict) -> dict | None:
    for p in serialized.get("pages", []):
        if p.get("pageType") == "PAGE_TYPE_CANVAS":
            return p
    return None


def inject_banner(serialized: dict, persona: str, space_id: str) -> bool:
    """Add or update the banner on the first canvas page. Returns True
    if the serialized dashboard was modified."""
    page = first_canvas_page(serialized)
    if page is None:
        print(f"  [warn] no canvas page in dashboard")
        return False

    new_banner = banner_widget(persona, space_id)
    layout = page.setdefault("layout", [])

    # Remove any existing banner for this persona
    existing_idx = None
    for i, w in enumerate(layout):
        name = w.get("widget", {}).get("name", "")
        if name == new_banner["widget"]["name"]:
            existing_idx = i
            break

    if existing_idx is not None:
        # Update in place; don't shift other widgets (they're already shifted)
        layout[existing_idx] = new_banner
        return True

    # Insert at the top and shift everything else down by 1 row
    for w in layout:
        pos = w.get("position")
        if isinstance(pos, dict) and "y" in pos:
            pos["y"] = pos["y"] + 1
    layout.insert(0, new_banner)
    return True


def patch_dashboard(dashboard_id: str, serialized: dict) -> None:
    payload = {
        "warehouse_id": WAREHOUSE_ID,
        "serialized_dashboard": json.dumps(serialized),
    }
    payload_path = Path(f"/tmp/_patch_{dashboard_id}.json")
    payload_path.write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "patch",
         f"/api/2.0/lakeview/dashboards/{dashboard_id}",
         "--json", f"@{payload_path}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"PATCH failed for {dashboard_id}: {r.stderr}")


def publish_dashboard(dashboard_id: str) -> None:
    pub_payload = {"warehouse_id": WAREHOUSE_ID, "embed_credentials": True}
    r = subprocess.run(
        ["databricks", "api", "post",
         f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
         "--json", json.dumps(pub_payload)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"publish failed for {dashboard_id}: {r.stderr}")


def fetch_serialized(dashboard_id: str) -> dict:
    r = subprocess.run(
        ["databricks", "api", "get",
         f"/api/2.0/lakeview/dashboards/{dashboard_id}"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(r.stdout)
    return json.loads(data["serialized_dashboard"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", help="only attach for this persona")
    args = parser.parse_args()

    if not DASH_IDS_FILE.exists():
        print(f"error: {DASH_IDS_FILE} not found — run slice_dashboards.py --upload first",
              file=sys.stderr)
        return 1
    if not GENIE_IDS_FILE.exists():
        print(f"error: {GENIE_IDS_FILE} not found — run setup_persona_genie_spaces.py first",
              file=sys.stderr)
        return 1

    dash_ids = json.loads(DASH_IDS_FILE.read_text())
    genie_ids = json.loads(GENIE_IDS_FILE.read_text())

    personas = [args.persona] if args.persona else list(dash_ids.keys())
    for persona in personas:
        dash_id = dash_ids.get(persona)
        space_id = genie_ids.get(persona)
        if not dash_id or not space_id:
            print(f"[{persona}] missing dashboard_id or space_id, skipping")
            continue

        print(f"[{persona}] fetching dashboard {dash_id}")
        serialized = fetch_serialized(dash_id)
        changed = inject_banner(serialized, persona, space_id)
        if not changed:
            print(f"[{persona}] no change needed")
            continue

        print(f"[{persona}] patching dashboard with banner → space {space_id}")
        patch_dashboard(dash_id, serialized)
        publish_dashboard(dash_id)
        print(f"[{persona}] done")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
