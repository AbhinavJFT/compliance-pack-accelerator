"""Headless setup + health-check for the Agent Bricks layer.

Today the AI agents (DPIA generator, Compliance Q&A, ai_classify) are
configured inside `notebooks/03_agent_bricks.py`. That notebook is the
demo UX, but the *infrastructure it depends on* — a foundation-model
serving endpoint and an MLflow experiment — should be set up and
health-checked outside the notebook so a fresh deploy can be validated
in seconds.

What this script does (idempotent, fast, no LLM tokens spent unless
``--smoke``):

  1. Verify the configured foundation-model serving endpoint exists +
     reports a READY state.
  2. Idempotently create the MLflow experiment used for traces.
  3. Sanity-check that ``governance_core/agent_prompts.py`` loads and
     print the prompt-version hashes (so a prompt drift shows up at
     deploy time, not only when MLflow traces look different later).
  4. Optional ``--smoke``: send one tiny chat-completions request to
     verify the endpoint accepts the same payload shape the notebook
     uses. Costs a few tokens.

This is intentionally NOT a wrapper that replaces the notebook — the
notebook is the demo. This is the orchestrator-friendly equivalent
the colleague's gap-3.4 asked for: ``setup_agent_bricks.py`` runnable
from `setup_all_personas.py` or `deploy_all.sh`, fails loudly if the
infra isn't ready.

Usage:
    python3 scripts/setup_agent_bricks.py
    python3 scripts/setup_agent_bricks.py --smoke
    python3 scripts/setup_agent_bricks.py --experiment-path /Shared/my_experiment
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from persona_config import get_model_endpoint, get_workspace_url  # noqa: E402

DEFAULT_EXPERIMENT_PATH = "/Shared/dpdp_agent_bricks"


def _api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Call the Databricks REST API via the CLI. Returns (rc, parsed_json)."""
    cmd = ["databricks", "api", method, path]
    if body is not None:
        Path("/tmp/_agent_bricks_body.json").write_text(json.dumps(body))
        cmd += ["--json", "@/tmp/_agent_bricks_body.json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return (r.returncode, {"_stderr": r.stderr[:300]})
    try:
        return (0, json.loads(r.stdout) if r.stdout else {})
    except json.JSONDecodeError:
        return (0, {"_stdout": r.stdout[:300]})


def check_endpoint(name: str) -> tuple[bool, str]:
    """Return (ok, detail). The CLI exposes serving endpoints at
    /api/2.0/serving-endpoints/<name>; pay-as-you-go foundation-model
    endpoints (databricks-gpt-oss-120b etc.) report state.ready."""
    rc, body = _api("get", f"/api/2.0/serving-endpoints/{name}")
    if rc != 0:
        return (False, f"CLI rc={rc} stderr={body.get('_stderr','')}")
    state = body.get("state", {})
    ready = state.get("ready", "") == "READY"
    return (ready, f"ready={state.get('ready')} config_update={state.get('config_update')}")


def ensure_mlflow_experiment(path: str) -> tuple[bool, str]:
    """Create the MLflow experiment if it doesn't exist. Idempotent."""
    rc, body = _api("get", f"/api/2.0/mlflow/experiments/get-by-name?experiment_name={path}")
    if rc == 0 and "experiment" in body:
        eid = body["experiment"].get("experiment_id", "?")
        return (True, f"exists (experiment_id={eid})")
    rc, body = _api("post", "/api/2.0/mlflow/experiments/create", {"name": path})
    if rc != 0:
        return (False, f"create rc={rc} stderr={body.get('_stderr','')}")
    return (True, f"created (experiment_id={body.get('experiment_id','?')})")


def check_prompts() -> tuple[bool, str]:
    """Verify governance_core.agent_prompts + dpia + pack_loader load
    cleanly and the pack-aware DPIA render path works end-to-end.

    Catches prompt drift, import errors, missing-pack-file errors, and
    schema-shape mismatches at deploy time rather than at the first
    LLM call.

    Phase-3 refactor note: ``DPIA_SYSTEM`` and ``DPIA_PROMPT_VERSION``
    became pack-aware functions (``render_dpia_system(template)``,
    ``dpia_prompt_version(template)``); this check exercises those new
    signatures. The DPIA section schema lives in
    ``governance_core.dpia.DPIASections`` (Pydantic).
    """
    try:
        from governance_core.agent_prompts import (
            render_dpia_system, render_dpia_user, dpia_prompt_version,
            COMPLIANCE_QA_SYSTEM, COMPLIANCE_QA_PROMPT_VERSION,
            render_compliance_qa_user,
        )
        from governance_core.dpia import DPIASections
        from governance_core.pack_loader import load as load_pack
    except Exception as exc:
        return (False, f"import failed: {exc}")
    # Smoke: load the active regulation pack's DPIA template, then
    # render once with empty context to catch template / schema errors.
    try:
        pack = load_pack()
        template = pack.dpia_template()
        schema = DPIASections.model_json_schema()
        render_dpia_system(template)
        render_dpia_user(
            {k: [] for k in [
                "pii_summary", "critical_pii", "gaps_summary",
                "consent_coverage", "compliance_rules",
                "data_sources", "tables_scanned",
            ]},
            template,
            schema,
        )
        render_compliance_qa_user("ctx", "q?")
    except Exception as exc:
        return (False, f"render failed: {exc}")
    return (True, f"DPIA_PROMPT_VERSION={dpia_prompt_version(template)} "
                  f"COMPLIANCE_QA_PROMPT_VERSION={COMPLIANCE_QA_PROMPT_VERSION}")


def smoke_invoke(endpoint: str) -> tuple[bool, str]:
    """One small chat-completions request to confirm the endpoint accepts
    the same payload shape the notebook uses. Costs a few tokens."""
    body = {
        "messages": [
            {"role": "system", "content": "Reply with the single word OK."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 10,
        "temperature": 0,
    }
    rc, resp = _api("post", f"/serving-endpoints/{endpoint}/invocations", body)
    if rc != 0:
        return (False, f"CLI rc={rc} stderr={resp.get('_stderr','')[:200]}")
    # Foundation-model responses come back as either choices[].message.content
    # (chat) or content[].text (typed-blocks). Either is fine — we just want
    # a non-empty response.
    choices = resp.get("choices") or []
    content = (choices[0].get("message", {}).get("content") if choices else None) \
              or resp.get("content") \
              or ""
    if not content:
        return (False, f"empty response (keys={list(resp.keys())[:5]})")
    snippet = (content if isinstance(content, str) else json.dumps(content))[:60]
    return (True, f"got: {snippet!r}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", default=None,
                   help="Serving endpoint name. Defaults to persona_config.get_model_endpoint().")
    p.add_argument("--experiment-path", default=DEFAULT_EXPERIMENT_PATH,
                   help=f"MLflow experiment path (default: {DEFAULT_EXPERIMENT_PATH})")
    p.add_argument("--smoke", action="store_true",
                   help="Make one small LLM call to verify the endpoint accepts our payload shape.")
    args = p.parse_args()

    endpoint = args.endpoint or get_model_endpoint()
    print(f"Agent Bricks setup — workspace {get_workspace_url()}")
    print(f"  endpoint:        {endpoint}")
    print(f"  experiment path: {args.experiment_path}")
    print(f"  smoke invoke:    {'YES' if args.smoke else 'no (use --smoke)'}")
    print("=" * 70)

    checks: list[tuple[str, bool, str]] = []

    ok, detail = check_endpoint(endpoint)
    checks.append((f"Foundation-model endpoint `{endpoint}` is READY", ok, detail))

    ok, detail = ensure_mlflow_experiment(args.experiment_path)
    checks.append((f"MLflow experiment `{args.experiment_path}` available", ok, detail))

    ok, detail = check_prompts()
    checks.append(("governance_core.agent_prompts loads + renders cleanly", ok, detail))

    if args.smoke:
        ok, detail = smoke_invoke(endpoint)
        checks.append((f"Endpoint `{endpoint}` accepts the notebook's payload shape", ok, detail))

    print()
    passed = 0
    for name, ok, detail in checks:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}")
        if detail:
            print(f"      {detail}")
        if ok:
            passed += 1

    print("\n" + "=" * 70)
    print(f"Summary: {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
