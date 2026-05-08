"""Validate the shape of configs/genie/*.yaml so typos don't ship silently.

The Genie knowledge-store config (applied by
scripts/configure_persona_genie_instructions.py) is authored as one YAML per
persona. A typo in a field name (e.g. `filter` instead of `filters`) is
accepted by yaml.safe_load but produces an incomplete serialized_space on
the Genie side — the misconfiguration only surfaces later, when a persona's
question fails to match an example query or filter.

This test locks down the shape expected by the configure script. It runs
locally (no Databricks / warehouse required).

Checks:
  1. Every persona in EXPECTED_PERSONAS has a YAML at configs/genie/<name>.yaml
  2. Each YAML is syntactically valid and a top-level mapping
  3. `persona` field matches the filename stem
  4. `text_instructions` is a non-empty string
  5. filters / measures / dimensions are lists of mappings with required keys
  6. example_queries is a list of mappings with `question` + `sql`
  7. sql_functions (optional) each have an `identifier`

Run:
    python3 tests/test_genie_config_schema.py
    python3 tests/test_genie_config_schema.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs" / "genie"
EXPECTED_PERSONAS = ["cco", "cfo", "cmo", "gc"]

# Keys every filter/measure/dimension entry must carry. `instruction` and
# `synonyms` are strongly recommended for Genie match quality but not
# technically required by the API — keep as REQUIRED to catch authoring drift.
NAMED_FIELDS_REQUIRED = {"name", "sql", "synonyms", "instruction"}


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise AssertionError(f"{path.name}: invalid YAML — {e}")
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name}: top level must be a mapping, got {type(data).__name__}")
    return data


def _check_named_list(path: Path, key: str, items, kinds: set[str]) -> list[str]:
    errors = []
    if items is None:
        return errors  # absent is fine; empty-list is fine
    if not isinstance(items, list):
        return [f"{path.name}: `{key}` must be a list, got {type(items).__name__}"]
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{path.name}: `{key}[{i}]` is not a mapping")
            continue
        missing = kinds - item.keys()
        if missing:
            errors.append(f"{path.name}: `{key}[{i}]` (name={item.get('name','?')}) missing fields: {sorted(missing)}")
    return errors


def check_one(path: Path) -> list[str]:
    """Return a list of problem strings (empty = all good)."""
    errors: list[str] = []
    try:
        cfg = _load(path)
    except AssertionError as e:
        return [str(e)]

    stem = path.stem
    if cfg.get("persona") != stem:
        errors.append(f"{path.name}: `persona` field is {cfg.get('persona')!r}, expected {stem!r}")

    ti = cfg.get("text_instructions")
    if not isinstance(ti, str) or not ti.strip():
        errors.append(f"{path.name}: `text_instructions` must be a non-empty string")

    errors += _check_named_list(path, "filters",    cfg.get("filters"),    NAMED_FIELDS_REQUIRED)
    errors += _check_named_list(path, "measures",   cfg.get("measures"),   NAMED_FIELDS_REQUIRED)
    errors += _check_named_list(path, "dimensions", cfg.get("dimensions"), NAMED_FIELDS_REQUIRED)

    eqs = cfg.get("example_queries")
    if eqs is not None:
        if not isinstance(eqs, list):
            errors.append(f"{path.name}: `example_queries` must be a list")
        else:
            for i, eq in enumerate(eqs):
                if not isinstance(eq, dict):
                    errors.append(f"{path.name}: `example_queries[{i}]` is not a mapping")
                    continue
                missing = {"question", "sql"} - eq.keys()
                if missing:
                    errors.append(f"{path.name}: `example_queries[{i}]` missing fields: {sorted(missing)}")

    sfns = cfg.get("sql_functions")
    if sfns is not None:
        if not isinstance(sfns, list):
            errors.append(f"{path.name}: `sql_functions` must be a list")
        else:
            for i, f in enumerate(sfns):
                if not isinstance(f, dict) or "identifier" not in f:
                    errors.append(f"{path.name}: `sql_functions[{i}]` missing `identifier`")

    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    print(f"Genie config schema check — {CONFIGS_DIR}")
    print("=" * 70)

    if not CONFIGS_DIR.exists():
        print(f"✗ configs dir missing: {CONFIGS_DIR}")
        return 1

    all_errors: list[str] = []
    for persona in EXPECTED_PERSONAS:
        path = CONFIGS_DIR / f"{persona}.yaml"
        if not path.exists():
            all_errors.append(f"{persona}.yaml: missing")
            print(f"  ✗ {persona}.yaml MISSING")
            continue
        errs = check_one(path)
        if errs:
            all_errors.extend(errs)
            print(f"  ✗ {persona}.yaml — {len(errs)} issue(s)")
            if args.verbose:
                for e in errs:
                    print(f"      {e}")
        else:
            print(f"  ✓ {persona}.yaml")

    print("\n" + "=" * 70)
    if all_errors:
        print(f"FAILED: {len(all_errors)} issue(s) across {len(EXPECTED_PERSONAS)} configs")
        if not args.verbose:
            print("  (re-run with --verbose for per-issue detail)")
        return 1
    print(f"OK: {len(EXPECTED_PERSONAS)} configs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
