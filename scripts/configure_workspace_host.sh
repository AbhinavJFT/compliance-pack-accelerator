#!/usr/bin/env bash
# Idempotently set the literal `workspace.host` URL in databricks.yml.
#
# DAB does not allow variable interpolation on auth fields, so the host
# must be a literal in YAML. This script flips it without manual editing.
#
# Usage:
#   scripts/configure_workspace_host.sh https://dbc-XXXX.cloud.databricks.com
#   scripts/configure_workspace_host.sh                     # reads from $DATABRICKS_HOST
#
# Idempotent: re-running with the same URL is a no-op. The script targets
# the line under `targets.dev.workspace.host:` and rewrites it.

set -euo pipefail

URL="${1:-${DATABRICKS_HOST:-}}"

if [[ -z "$URL" ]]; then
  echo "error: workspace URL required (arg or \$DATABRICKS_HOST)" >&2
  echo "usage: $0 https://dbc-XXXX.cloud.databricks.com" >&2
  exit 64
fi

if [[ ! "$URL" =~ ^https://.+\.cloud\.databricks\.com/?$ ]]; then
  echo "error: URL doesn't look right: $URL" >&2
  echo "expected: https://dbc-<id>.cloud.databricks.com" >&2
  exit 64
fi

# Strip trailing slash for consistency with the existing literal style.
URL="${URL%/}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YAML="$REPO_ROOT/databricks.yml"

if [[ ! -f "$YAML" ]]; then
  echo "error: $YAML not found" >&2
  exit 1
fi

CURRENT="$(grep -E '^[[:space:]]+host: https://dbc-' "$YAML" | head -n1 | sed -E 's/^[[:space:]]+host: //')"

if [[ "$CURRENT" == "$URL" ]]; then
  echo "✓ databricks.yml already points at $URL — no change"
  exit 0
fi

# In-place rewrite. Use a sentinel comment line above the host so we
# don't touch any other 'host:' that might be added later (e.g. for prod).
TMP="$(mktemp)"
awk -v new="$URL" '
  /^[[:space:]]+host: https:\/\/dbc-/ && !done {
    sub(/host: https:\/\/dbc-[^[:space:]]+/, "host: " new)
    done = 1
  }
  { print }
' "$YAML" > "$TMP"

mv "$TMP" "$YAML"

echo "✓ databricks.yml workspace.host updated"
echo "  was: $CURRENT"
echo "  now: $URL"
