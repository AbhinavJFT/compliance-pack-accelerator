"""Strict drift detector — fails if any deterministic count moved.

Counterpart to ``test_post_deploy_smoke.py``: where smoke uses ``>=``
thresholds (cheap CI gate, "did the deploy work"), this test asserts
``==`` on every deterministic count we care about. Wiring intent:

  smoke.py            → "deploy is not broken" — loose, robust to legitimate adds
  test_baseline_counts → "nothing silently drifted from documented state"
                         — strict, fires on any rule / pattern / seed change

When this test fails, you have two choices:

  (a) The drift is intentional (you edited rules / patterns / seeds). Run
      ``python3 scripts/regenerate_test_expected.py --write`` to refresh
      tests/_baseline.json and copy the printed doc snippets into
      ``docs/how_to_test.html``.

  (b) The drift is unintentional. Investigate; do NOT update the baseline.

The baseline lives in ``tests/_baseline.json`` so the regenerate script
and this test share one source of truth.

Run:
    python3 tests/test_baseline_counts.py
    python3 tests/test_baseline_counts.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
from regenerate_test_expected import collect_live_state, diff  # noqa: E402

BASELINE_PATH = REPO_ROOT / "tests" / "_baseline.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not BASELINE_PATH.exists():
        print(f"✗ baseline missing: {BASELINE_PATH.relative_to(REPO_ROOT)}")
        print("  Run: python3 scripts/regenerate_test_expected.py --write")
        return 1

    print(f"Baseline drift check — {BASELINE_PATH.relative_to(REPO_ROOT)}")
    print("=" * 70)

    baseline = json.loads(BASELINE_PATH.read_text())
    live = collect_live_state()
    drift = diff(baseline, live)

    if args.verbose:
        print(f"Baseline keys: {len(baseline)} top-level, {sum(1 for _ in iter_leaves(baseline))} leaves")
        print(f"Live keys:     {len(live)} top-level, {sum(1 for _ in iter_leaves(live))} leaves")
        print()

    if not drift:
        print(f"\n✓ No drift — every deterministic count matches the baseline.")
        return 0

    print(f"\n✗ {len(drift)} value(s) drifted from baseline:")
    print()
    print(f"  {'key':<55s} {'baseline':>15s}  →  {'live':<15s}")
    print(f"  {'-'*55} {'-'*15}  →  {'-'*15}")
    for key, old, new in drift:
        old_s = json.dumps(old) if not isinstance(old, (int, str)) else str(old)
        new_s = json.dumps(new) if not isinstance(new, (int, str)) else str(new)
        print(f"  {key:<55s} {old_s:>15s}  →  {new_s:<15s}")
    print()
    print("To resolve:")
    print("  • If the change is intentional (you edited rules/patterns/seeds):")
    print("      python3 scripts/regenerate_test_expected.py --write")
    print("    then copy the printed doc snippets into docs/how_to_test.html")
    print("  • If the change is unintentional: do NOT refresh the baseline; investigate.")
    return 1


def iter_leaves(d):
    """Yield every leaf value in a nested dict (for verbose stats only)."""
    for v in d.values():
        if isinstance(v, dict):
            yield from iter_leaves(v)
        else:
            yield v


if __name__ == "__main__":
    raise SystemExit(main())
