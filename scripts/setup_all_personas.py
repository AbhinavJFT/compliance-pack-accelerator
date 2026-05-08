"""One-command orchestrator for the full persona layer.

Runs the six persona-setup scripts in the correct order, aborts on
the first failure, and prints a clear checklist of the manual steps
the deployer still needs to do (Consumer-access toggle + token-login
test).

All six underlying scripts are idempotent, so this orchestrator is
also idempotent — safe to re-run after any failure.

Usage:
    python3 scripts/setup_all_personas.py
    python3 scripts/setup_all_personas.py --dry-run
    python3 scripts/setup_all_personas.py --skip slice --skip genie
    python3 scripts/setup_all_personas.py --from users
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
from persona_config import print_detected, get_deployer_email  # noqa: E402


@dataclass
class Step:
    key: str        # short name for --skip / --from
    title: str      # human description
    argv: list[str] # argv to run (script path + flags)


STEPS: list[Step] = [
    Step("slice",  "Slice master dashboard into 4 persona dashboards + upload",
         [str(SCRIPTS_DIR / "slice_dashboards.py"), "--upload"]),
    Step("genie",  "Create 4 persona Genie spaces (scoped to persona tables)",
         [str(SCRIPTS_DIR / "setup_persona_genie_spaces.py")]),
    Step("instr",  "Apply knowledge-store config to each Genie space (from configs/genie/*.yaml)",
         [str(SCRIPTS_DIR / "configure_persona_genie_instructions.py")]),
    Step("attach", "Add 'Ask the X Agent' link tiles to each dashboard",
         [str(SCRIPTS_DIR / "attach_genie_to_dashboards.py")]),
    Step("users",  "Create 4 plus-addressed persona workspace users",
         [str(SCRIPTS_DIR / "setup_persona_users.py")]),
    Step("grants", "Apply UC SELECT grants per persona",
         [str(SCRIPTS_DIR / "apply_persona_uc_grants.py")]),
    Step("acls",   "Apply warehouse + dashboard + Genie workspace ACLs",
         [str(SCRIPTS_DIR / "apply_persona_workspace_acls.py")]),
]

STEP_KEYS = [s.key for s in STEPS]

BOX = "═" * 72
THIN = "─" * 72


def run_step(step: Step, dry_run: bool) -> bool:
    print(f"\n{BOX}")
    print(f"▶  [{step.key}]  {step.title}")
    print(BOX)
    if dry_run:
        print(f"   (dry-run) would run: python3 {' '.join(step.argv)}")
        return True

    t0 = time.time()
    proc = subprocess.run(
        ["python3", *step.argv],
        cwd=REPO_ROOT,
        # Let the child write directly to our stdout/stderr so the
        # deployer sees the same live output they'd see running
        # scripts individually.
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        print(f"\n✗ [{step.key}] failed (rc={proc.returncode}) after {elapsed:.1f}s")
        return False
    print(f"\n✓ [{step.key}] done in {elapsed:.1f}s")
    return True


def print_manual_steps(deployer_email: str | None) -> None:
    emails_file = REPO_ROOT / "dashboards" / "personas" / ".persona_emails.json"
    emails: dict[str, str] = {}
    if emails_file.exists():
        emails = json.loads(emails_file.read_text())

    inbox = deployer_email or "your inbox"

    print(f"\n{BOX}")
    print("MANUAL STEPS REMAINING (one-time, per persona user)")
    print(BOX)

    print("\n1. ENTITLEMENTS — in the workspace admin UI, for each new user:")
    print("     https://<your-workspace>/settings/workspace/identity-and-access/users")
    if emails:
        for persona, email in emails.items():
            print(f"     • {email}  ({persona.upper()})")
    print("   Toggle:")
    print("     - Consumer access  → ON   (required for dashboards + Genie)")
    print("     - Workspace access → OFF  (optional; cleaner persona semantics)")
    print("     - Admin access: keep Off.  Databricks SQL access: keep On.")

    print("\n2. LOGIN TEST — in an incognito window:")
    print("     - Go to the workspace login page")
    print("     - Enter a persona email (e.g. the CCO one above)")
    print(f"     - Databricks sends a one-time token to {inbox}")
    print("       (plus-addressing routes all four personas' tokens there)")
    print("     - Click the link → you're logged in as that persona")

    print("\n3. VERIFY THE BOUNDARY — while logged in as a persona:")
    print("     - The persona's dashboard should render")
    print("     - Try opening a different persona's dashboard URL → should 403")
    print("     - Click 'Ask the X Agent' banner → lands in the persona Genie")
    print(f"\n{THIN}")
    print("See docs/persona_deploy.md for the full guide + troubleshooting.")
    print(THIN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command sequence without running anything",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=STEP_KEYS,
        help="Skip this step (can be used multiple times)",
    )
    parser.add_argument(
        "--from",
        dest="from_step",
        choices=STEP_KEYS,
        help="Start from this step (skip everything before)",
    )
    args = parser.parse_args()

    skipped = set(args.skip)
    if args.from_step:
        idx = STEP_KEYS.index(args.from_step)
        skipped.update(STEP_KEYS[:idx])

    try:
        print_detected()
        deployer = get_deployer_email()
    except Exception as e:
        print(f"error: cannot detect runtime context: {e}", file=sys.stderr)
        print("       make sure the Databricks CLI is configured and a "
              "SQL warehouse is RUNNING", file=sys.stderr)
        return 1

    total = 0
    t0 = time.time()
    for step in STEPS:
        if step.key in skipped:
            print(f"\n⟳ [{step.key}] skipped")
            continue
        if not run_step(step, args.dry_run):
            print(f"\n{BOX}\nABORTED at step '{step.key}'. "
                  f"Fix the error and re-run (all steps are idempotent, "
                  f"or use --from {step.key} to start here).\n{BOX}")
            return 1
        total += 1

    elapsed = time.time() - t0
    print(f"\n{BOX}")
    print(f"✓ All {total} step(s) completed in {elapsed:.1f}s")
    print(BOX)

    if not args.dry_run:
        print_manual_steps(deployer)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
