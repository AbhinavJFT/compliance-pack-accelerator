"""DPIA Auto-Generator — pure-Python orchestration for the DPIA flow.

Used by:
  - notebooks/03_agent_bricks.py (Agent 1, demo path)
  - pipelines/dpia_generator.py  (scheduled job, production path)

Both call ``run_dpia_generation`` so the demo and the job produce
identical artifacts. The caller injects spark, the LLM-invoker callable,
and (optionally) mlflow + dbutils — this module is otherwise free of
Databricks runtime imports and unit-testable with stubs.

Phase 3 changes:
  - DPIA output is now structured (8 named sections via Pydantic), not
    one prose blob. Validated post-LLM with ``DPIASections.model_validate_json``;
    parse failures fall back to raw text in ``dpia_text`` + the
    Pydantic ``ValidationError`` in ``parse_error``.
  - Prompts are pack-aware via ``governance_core.pack_loader.DPIATemplate``
    (loaded from ``regulations/<pack>/dpia_template.yaml``).
  - ``compliance_rules`` is added to the context so the model can cite
    rule_id values + section numbers in its gap analysis.

Side effects of one run:
  1. JSON artifact written to ``/Volumes/<catalog>/compliance/dpia_artifacts/dpia_<run_id>.json``
  2. One row appended to ``<catalog>.compliance.dpia_runs`` (created on first call)
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from governance_core.agent_prompts import (
    dpia_prompt_version,
    render_dpia_system,
    render_dpia_user,
)


PROMPT_MODULE = "governance_core.agent_prompts:render_dpia_user"
PARSE_ERROR_MAX_CHARS = 1000


# ---------------------------------------------------------------------
# Structured-output schema (Phase 3)
# ---------------------------------------------------------------------


class DPIASections(BaseModel):
    """Structured output for the DPIA agent.

    The 8 section *keys* are regulation-agnostic — DPDP §10, GDPR Art. 35,
    and CCPA all expect roughly this structure, so dashboard tiles render
    consistently regardless of which regulation pack is active. The
    section *content* differs per pack via ``regulations/<pack>/dpia_template.yaml``.

    ``extra='forbid'`` rejects unknown keys so we catch the
    "model invented a 9th section" case rather than silently dropping it.

    ``min_length=50`` is a soft tripwire: if the model returns "TBD" or
    a one-line stub for any section, validation fails and the row lands
    with ``dpia_sections=NULL`` + ``parse_error`` populated, which the
    reviewer sees and can re-trigger.
    """

    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(
        min_length=50,
        description=(
            "2-3 paragraph overview of the data fiduciary's personal-data "
            "processing footprint. Reference total PII column count, table "
            "count, and the most material findings from the metadata. "
            "Plain prose; avoid bullet lists in this section."
        ),
    )
    data_inventory: str = Field(
        min_length=50,
        description=(
            "What personal data is held, in which systems, at what sensitivity "
            "tier. Cite specific table and column names from the provided "
            "metadata. A markdown table works well here."
        ),
    )
    processing_activities: str = Field(
        min_length=50,
        description=(
            "What the data is used for, with the legal basis under the active "
            "regulation. Reference specific compliance rules from the provided "
            "compliance_rules metadata where the rule wording bears on the activity."
        ),
    )
    risk_assessment: str = Field(
        min_length=50,
        description=(
            "Critical and high-risk findings with severity ratings. Quote "
            "specific gap counts and per-rule numbers from the provided "
            "metadata. Group by severity (critical → high → medium)."
        ),
    )
    compliance_gap_analysis: str = Field(
        min_length=50,
        description=(
            "Gaps against the active regulation's obligations. Cite specific "
            "rule_id values from the provided compliance_rules metadata."
        ),
    )
    consent_status: str = Field(
        min_length=50,
        description=(
            "Coverage of consent across purposes, using the provided "
            "consent_coverage metadata. Note any purposes with low grant "
            "rates or high withdrawal rates."
        ),
    )
    remediation_plan: str = Field(
        min_length=50,
        description=(
            "Prioritised actions to close gaps. Each action references a "
            "specific rule_id and the table/column from the metadata where "
            "the gap manifests. Order critical → high → medium."
        ),
    )
    residual_risk: str = Field(
        min_length=50,
        description=(
            "What risk remains after the remediation plan executes. Honest "
            "and specific, tied to the metadata — not boilerplate."
        ),
    )


def _schema_with_pack_overrides(overrides: dict[str, str]) -> dict[str, Any]:
    """Build the JSON schema given to the LLM, merging in any pack-specific
    section description overrides from ``DPIATemplate.section_descriptions``.

    The default Field descriptions in DPIASections are the regulation-agnostic
    baseline; the pack can replace any of them with regulation-specific
    guidance (e.g. "cite DPDP section numbers"). The Pydantic model itself is
    not mutated — we only customise the schema dict that goes into the prompt.
    """
    schema = DPIASections.model_json_schema()
    properties = schema.get("properties", {})
    for section_key, override_desc in overrides.items():
        if section_key in properties:
            properties[section_key]["description"] = override_desc
    return schema


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def convert_decimals(obj: Any) -> Any:
    """Recursively coerce non-JSON-native Spark/pandas values for ``json.dumps``.

    Two types surface from Spark + ``.toPandas().to_dict('records')`` and
    blow up json.dumps:

      - ``decimal.Decimal`` from numeric columns → coerce to ``float``.
      - ``numpy.ndarray`` from ``array<...>`` columns (e.g. compliance_rules.regulations,
        applicable_categories) → coerce to a plain ``list`` and recurse.

    Public so the Compliance Q&A agent (which also serializes Spark
    output) can reuse it.
    """
    if isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    if isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    # Duck-type for numpy ndarrays without importing numpy at module top.
    # str/bytes also have a tolist-shaped misuse risk, so explicitly exclude.
    if hasattr(obj, "tolist") and not isinstance(obj, (str, bytes, bytearray)):
        return convert_decimals(obj.tolist())
    return obj


_PRINCIPAL_TABLES = ("customers_tagged", "users_tagged", "employees_tagged", "patients_tagged")


def gather_dpia_context(spark, catalog: str) -> dict[str, list]:
    """Run the SQL queries that feed the DPIA prompt.

    Returns a dict whose keys match the placeholder names in
    ``governance_core.agent_prompts._DPIA_USER_TEMPLATE``. Each value is
    a list of records (one per row) so the prompt template can json.dumps
    them in deterministic order.

    Phase 3 added ``compliance_rules`` so the model can cite rule_id +
    rule_text directly in its compliance_gap_analysis section instead of
    summarising gap counts only.

    ADR-0001 multi-pack: also includes ``jurisdiction_breakdown`` so the
    merger has a basis for per-jurisdiction reasoning. Union of the four
    silver tables that carry a ``jurisdiction`` column.
    """
    jurisdiction_union = " UNION ALL ".join(
        f"SELECT jurisdiction FROM {catalog}.silver.{t}" for t in _PRINCIPAL_TABLES
    )
    return {
        "pii_summary": spark.sql(f"""
            SELECT sensitivity_tier,
                   COUNT(*) AS columns,
                   COUNT(DISTINCT source_table) AS tables
            FROM {catalog}.compliance.personal_data_register
            GROUP BY sensitivity_tier
            ORDER BY CASE sensitivity_tier
                WHEN 'critical' THEN 1
                WHEN 'high'     THEN 2
                WHEN 'medium'   THEN 3
                ELSE 4
            END
        """).toPandas().to_dict("records"),
        "critical_pii": spark.sql(f"""
            SELECT source_table, source_column, pii_type, pii_category
            FROM {catalog}.compliance.personal_data_register
            WHERE sensitivity_tier = 'critical'
        """).toPandas().to_dict("records"),
        "gaps_summary": spark.sql(f"""
            SELECT rule_type, severity,
                   COUNT(*) AS gap_count,
                   COUNT(DISTINCT table_name) AS tables
            FROM {catalog}.silver.compliance_gaps
            GROUP BY rule_type, severity
            ORDER BY CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high'     THEN 2
                ELSE 3
            END
        """).toPandas().to_dict("records"),
        # Phase 3: feed the rule definitions so the model can cite
        # specific rule_id, description, and remediation text in gap
        # analysis. Schema mirrors phase1_bootstrap's CREATE TABLE for
        # bronze.compliance_rules — the table has no separate `citation`
        # column; the regulation context comes from the `regulations`
        # array column instead.
        "compliance_rules": spark.sql(f"""
            SELECT rule_id, rule_type, severity, regulations,
                   description, remediation
            FROM {catalog}.bronze.compliance_rules
            WHERE is_active = true
            ORDER BY rule_id
        """).toPandas().to_dict("records"),
        "consent_coverage": spark.sql(f"""
            SELECT * FROM {catalog}.gold.consent_coverage_summary
        """).toPandas().to_dict("records"),
        "data_sources": spark.sql(f"""
            SELECT source_name, source_type, ingestion_pattern
            FROM {catalog}.bronze.data_sources
            WHERE is_active = true
        """).toPandas().to_dict("records"),
        # silver.discovered_tables has no pii_column_count column of its own —
        # join the pre-aggregated table_pii_column_count from the personal data
        # register so the DPIA can quote a per-table PII count.
        "tables_scanned": spark.sql(f"""
            SELECT
                d.table_name,
                d.row_count,
                d.column_count,
                COALESCE(p.table_pii_column_count, 0) AS pii_column_count
            FROM {catalog}.silver.discovered_tables d
            LEFT JOIN (
                SELECT DISTINCT source_table, table_pii_column_count
                FROM {catalog}.compliance.personal_data_register
            ) p ON d.table_name = p.source_table
        """).toPandas().to_dict("records"),
        # ADR-0001: per-jurisdiction principal counts feed the merger
        # (template_for_activity selects packs from these codes) and give
        # the LLM a basis for per-pack section reasoning. NULL jurisdiction
        # rows surface in the "unmapped principals" tile, not here.
        "jurisdiction_breakdown": spark.sql(f"""
            SELECT jurisdiction, COUNT(*) AS principal_count
            FROM ({jurisdiction_union})
            GROUP BY jurisdiction
            ORDER BY principal_count DESC
        """).toPandas().to_dict("records"),
    }


# ---------------------------------------------------------------------
# Audit table
# ---------------------------------------------------------------------


_AUDIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.compliance.dpia_runs (
    run_id              STRING    NOT NULL,
    generated_at        TIMESTAMP NOT NULL,
    generated_by        STRING    NOT NULL,
    catalog_name        STRING    NOT NULL,
    model_endpoint      STRING    NOT NULL,
    prompt_module       STRING    NOT NULL,
    prompt_version      STRING    NOT NULL,
    regulation_pack     STRING,
    regulation_packs    ARRAY<STRING>,
    context_snapshot    STRING    NOT NULL,
    dpia_text           STRING    NOT NULL,
    dpia_sections       MAP<STRING, STRING>,
    parse_error         STRING,
    artifact_path       STRING    NOT NULL,
    latency_seconds     DOUBLE,
    status              STRING    NOT NULL,
    reviewed_by         STRING,
    reviewed_at         TIMESTAMP,
    notes               STRING
) USING DELTA
  TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.logRetentionDuration' = 'interval 730 days'
  )
"""

_AUDIT_ROW_SCHEMA = (
    "run_id string, generated_at timestamp, generated_by string, "
    "catalog_name string, model_endpoint string, prompt_module string, "
    "prompt_version string, regulation_pack string, regulation_packs array<string>, "
    "context_snapshot string, "
    "dpia_text string, dpia_sections map<string,string>, parse_error string, "
    "artifact_path string, latency_seconds double, "
    "status string, reviewed_by string, reviewed_at timestamp, notes string"
)


def _ensure_audit_table(spark, catalog: str) -> None:
    """Idempotently create / upgrade the audit table.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op on already-deployed tables,
    so existing workspaces also need an idempotent ``ALTER TABLE ADD COLUMNS``
    for any column added after first deploy. The ADR-0001 multi-pack
    rollout added ``regulation_packs ARRAY<STRING>``; check info_schema
    before ALTER so this is safe on every Delta version (the bare
    ``IF NOT EXISTS`` clause on ADD COLUMNS isn't universally supported).
    """
    spark.sql(_AUDIT_TABLE_DDL.format(catalog=catalog))
    existing = {
        row[0]
        for row in spark.sql(
            f"SELECT column_name FROM {catalog}.information_schema.columns "
            f"WHERE table_schema='compliance' AND table_name='dpia_runs'"
        ).collect()
    }
    if "regulation_packs" not in existing:
        spark.sql(
            f"ALTER TABLE {catalog}.compliance.dpia_runs "
            f"ADD COLUMNS (regulation_packs ARRAY<STRING>)"
        )


# ---------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------


def _resolve_dpia_packs(
    *,
    pack=None,
    regulation_pack: str | None = None,
    jurisdiction_breakdown: list[dict] | None = None,
):
    """Pick the DPIATemplate + contributing pack codes for one DPIA run.

    Three precedence-ordered paths (ADR-0001 multi-pack):
      (a) ``pack=`` explicit → single-pack, that pack's template (test stub).
      (b) ``regulation_pack=<code>`` explicit → single-pack, looked up in
          ``loaded_packs()`` (re-run override path).
      (c) Default → ``jurisdiction_breakdown`` drives selection via
          ``packs_for_activity`` + ``template_for_activity``. When fully
          unmapped, falls back to the primary loaded pack so the DPIA
          narrative still generates — the unmapped-principals tile is
          the proper surface for that gap, not a silent crash.

    Returns ``(template, [pack_code, ...])`` where pack codes are in
    primary-first order (matches ``packs_for_activity`` ordering).

    Pure function — no spark, no I/O, no MLflow — so unit-testable
    without Databricks. Existence is what makes the multi-pack wiring
    auditable in isolation.
    """
    from governance_core.dpia_template_merge import (
        packs_for_activity,
        template_for_activity,
    )
    from governance_core.pack_loader import loaded_packs

    if pack is not None:
        return pack.dpia_template(), [pack.code]
    if regulation_pack is not None:
        matching = [p for p in loaded_packs() if p.code == regulation_pack]
        if not matching:
            raise ValueError(
                f"regulation_pack={regulation_pack!r} not found in loaded packs "
                f"({[p.code for p in loaded_packs()]}). "
                f"Check regulations/ has a matching directory."
            )
        return matching[0].dpia_template(), [matching[0].code]

    jurisdictions = [row["jurisdiction"] for row in (jurisdiction_breakdown or [])]
    applicable = packs_for_activity(jurisdictions)
    if applicable:
        return template_for_activity(jurisdictions), [p.code for p in applicable]
    fallback = loaded_packs()[0]
    return fallback.dpia_template(), [fallback.code]


def _parse_dpia_output(raw: str) -> tuple[dict[str, str] | None, str | None]:
    """Parse + validate the LLM's JSON response against ``DPIASections``.

    Returns ``(sections_dict, parse_error)``. On success, ``sections_dict``
    is populated and ``parse_error`` is None. On failure, ``sections_dict``
    is None and ``parse_error`` is the validation/decode error message
    capped at PARSE_ERROR_MAX_CHARS so it fits in the audit column.

    Two failure modes are caught:
      - ValidationError: shape didn't match (missing field, too short, extra key)
      - JSONDecodeError / ValueError: response wasn't valid JSON at all
    """
    try:
        sections = DPIASections.model_validate_json(raw)
        return sections.model_dump(), None
    except ValidationError as e:
        return None, f"ValidationError: {e}"[:PARSE_ERROR_MAX_CHARS]
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"JSONDecodeError: {e}"[:PARSE_ERROR_MAX_CHARS]


def run_dpia_generation(
    *,
    spark,
    catalog: str,
    invoke_llm: Callable[..., str],
    model_endpoint: str,
    artifact_volume: str | None = None,
    regulation_pack: str | None = None,
    pack=None,
    mlflow=None,
    dbutils=None,
) -> dict:
    """Generate one DPIA artifact and persist evidence.

    Steps:
      1. Gather metadata from UC (SQL queries → ``dpia_context``).
      2. Resolve the regulation pack(s) for the activity. Default path:
         derive jurisdictions from the gathered context's
         ``jurisdiction_breakdown`` and call
         ``dpia_template_merge.template_for_activity()`` so multi-jurisdiction
         deploys get a merged DPIA citing every applicable regulation
         (ADR-0001). Single-pack escape hatches: caller passes ``pack=``
         directly (tests) or ``regulation_pack=<code>`` (re-run override).
      3. Build prompt + JSON schema from the (possibly merged) DPIA
         template, then call the LLM.
      4. Parse + validate the LLM response with ``DPIASections``;
         fall back gracefully if parsing fails.
      5. Write JSON artifact to ``<artifact_volume>/dpia_<run_id>.json``.
      6. Append one row to ``<catalog>.compliance.dpia_runs``.

    Args:
      spark: SparkSession.
      catalog: Unity Catalog name (e.g. ``compliance_pack``).
      invoke_llm: Callable accepting ``(messages, *, max_tokens, temperature)``
        and returning the assistant's text. Caller owns retries, timeouts,
        and auth.
      model_endpoint: Endpoint name. Logged into the audit row.
      artifact_volume: Volume path for the JSON output. Defaults to
        ``/Volumes/<catalog>/compliance/dpia_artifacts``.
      regulation_pack: Override that forces single-pack mode. When set,
        skips jurisdiction-derived multi-pack resolution and uses this
        pack code's template. Useful for re-running a regulation-locked
        DPIA without changing data. Logged into the audit row's scalar
        ``regulation_pack`` column for backward compat.
      pack: Optional pre-loaded ``governance_core.pack_loader.Pack``. When
        passed, forces single-pack mode against that pack. Tests use this
        to inject a stubbed pack.
      mlflow: Optional ``mlflow`` module. When provided, prompt module,
        prompt version, model endpoint, and latency are logged.
      dbutils: Optional ``dbutils``. Used for ``dbutils.fs.put`` so
        ``/Volumes/`` paths resolve. Falls back to plain filesystem
        writes when not provided (unit tests).

    Returns:
      dict with keys: run_id, artifact_path, dpia_text, dpia_sections
      (parsed dict or None), parse_error (str or None), latency_seconds,
      context_snapshot, regulation_packs (list[str] — contributing pack
      codes; single-element in single-pack mode).
    """
    # 1. Gather context first — multi-pack resolution reads the
    # jurisdiction_breakdown that gather_dpia_context produces.
    context = gather_dpia_context(spark, catalog)
    context = convert_decimals(context)

    # 2. Resolve template + contributing packs (pure, spark-free).
    template, contributing_packs = _resolve_dpia_packs(
        pack=pack,
        regulation_pack=regulation_pack,
        jurisdiction_breakdown=context.get("jurisdiction_breakdown", []),
    )
    prompt_version = dpia_prompt_version(template)

    # 3. Build prompt + schema, call LLM
    json_schema = _schema_with_pack_overrides(template.section_descriptions)
    system_prompt = render_dpia_system(template)
    user_prompt = render_dpia_user(context, template, json_schema)

    if mlflow is not None:
        tags = {
            "model_endpoint": model_endpoint,
            "prompt_module": PROMPT_MODULE,
            "prompt_version": prompt_version,
            "catalog": catalog,
            "regulation_packs": ",".join(contributing_packs),
        }
        if regulation_pack:
            tags["regulation_pack"] = regulation_pack
        mlflow.update_current_trace(tags=tags)

    t0 = time.monotonic()
    dpia_text = invoke_llm(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4000,
        temperature=0.3,
    )
    latency_seconds = time.monotonic() - t0
    if mlflow is not None:
        mlflow.log_metric("latency_seconds", round(latency_seconds, 3))

    # 3. Parse + validate against DPIASections
    sections_dict, parse_error = _parse_dpia_output(dpia_text)
    if mlflow is not None:
        mlflow.log_metric("parse_succeeded", 0 if parse_error else 1)

    # 4. Write artifact (uuid filename — never overwrite previous runs)
    run_id = uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc)
    if artifact_volume is None:
        artifact_volume = f"/Volumes/{catalog}/compliance/dpia_artifacts"
    artifact_path = f"{artifact_volume}/dpia_{run_id}.json"

    # Scalar regulation_pack: primary pack code (first contributor) when the
    # caller didn't force one. Backward-compat for readers that index a single
    # pack code (Streamlit Review App, Lakeview tile).
    primary_pack = contributing_packs[0]
    artifact = {
        "run_id": run_id,
        "generated_at": generated_at.isoformat(),
        "model_endpoint": model_endpoint,
        "prompt_module": PROMPT_MODULE,
        "prompt_version": prompt_version,
        "regulation_pack": regulation_pack or primary_pack,
        "regulation_packs": contributing_packs,
        "catalog": catalog,
        "context_snapshot": context,
        "dpia_text": dpia_text,
        "dpia_sections": sections_dict,
        "parse_error": parse_error,
    }
    artifact_json = json.dumps(artifact, indent=2)
    if dbutils is not None:
        dbutils.fs.put(artifact_path, artifact_json, overwrite=True)
    else:
        # Local/test fallback — works on plain filesystem paths.
        from pathlib import Path
        Path(artifact_path).parent.mkdir(parents=True, exist_ok=True)
        Path(artifact_path).write_text(artifact_json)

    # 6. Append audit row
    _ensure_audit_table(spark, catalog)
    generated_by = spark.sql("SELECT current_user()").first()[0]
    audit_row = spark.createDataFrame(
        [(
            run_id,
            generated_at,
            generated_by,
            catalog,
            model_endpoint,
            PROMPT_MODULE,
            prompt_version,
            regulation_pack or primary_pack,
            contributing_packs,
            json.dumps(context),
            dpia_text,
            sections_dict,
            parse_error,
            artifact_path,
            float(latency_seconds),
            "draft",
            None,
            None,
            None,
        )],
        schema=_AUDIT_ROW_SCHEMA,
    )
    audit_row.write.mode("append").saveAsTable(f"{catalog}.compliance.dpia_runs")

    return {
        "run_id": run_id,
        "artifact_path": artifact_path,
        "dpia_text": dpia_text,
        "dpia_sections": sections_dict,
        "parse_error": parse_error,
        "latency_seconds": latency_seconds,
        "context_snapshot": context,
        "regulation_packs": contributing_packs,
    }
