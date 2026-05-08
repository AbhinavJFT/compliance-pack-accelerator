# Databricks free trial workspace limits

What the trial workspace can and cannot do, as of April 2026. The spec is designed to operate within these limits; this reference exists so you understand why certain design choices were made.

> **Consult Databricks documentation for authoritative current limits.** Trial terms change. If anything in this file contradicts current Databricks documentation, the documentation wins. Treat this as a snapshot for spec design purposes, not an authoritative source.

## What the trial includes

### Databricks platform features

The following are available in the trial and used by this POC:

- **Unity Catalog** with all governance features needed for the POC: catalogs, schemas, tables, views, column tags, lineage, audit log, grants.
- **Delta Lake** with all table features: time travel, Change Data Feed, schema evolution, VACUUM, OPTIMIZE, ZORDER.
- **Auto Loader** for streaming file ingestion into Delta.
- **Delta Live Tables (DLT)** for declarative pipelines.
- **Databricks Runtime 15.4 LTS** and later, including standard and ML runtimes.
- **AI Functions** including `ai_classify`, `ai_extract`, `ai_gen`, `ai_translate`, `ai_summarize`.
- **Databricks SQL** for interactive queries and dashboards.
- **Databricks Workflows** for job orchestration, with manual and scheduled triggers.
- **Databricks Apps** for hosting the DSR intake API (basic deployment).
- **Lakebase** (Postgres OLTP) — GA since February 2026, available in trial in supported regions.
- **Model Serving** endpoints, up to small throughput, used implicitly by AI Functions.

### Compute

- Interactive clusters: yes, with an auto-terminate policy.
- Job clusters: yes.
- SQL warehouses: yes, Serverless or Classic.
- Single Node, All Purpose, and Job compute types all supported.

### Networking

- Default workspace VPC on the chosen cloud.
- Public internet egress for AI Functions and registry downloads.
- Databricks-to-Lakebase integrated auth (no external DNS needed).

## What the trial does NOT include (relevant to this POC)

### Features explicitly unavailable

- **Lakewatch agentic SIEM** — Private Preview as of March 2026. Referenced in the proposal's Module 04 design but out of scope for this POC (§1.4).
- **Custom networking** — no VPC peering, no Private Link, no customer-managed keys in trial.
- **Enterprise SSO integration** — the trial uses Databricks-managed identity. No Okta/Azure AD integration.
- **Advanced observability features** — some system tables may be limited in the trial.
- **Private Preview features generally** — anything not GA is typically gated.

### Capacity constraints

- **Compute credits** — finite balance that must last the 14-day sprint. §9.2.1 of the main spec covers mitigation.
- **Model Serving concurrency** — AI Functions are throttled under the trial; running `ai_classify` across 1,500 patients all at once may rate-limit. Sample to 100 per §4.5.2 of the spec.
- **Workspace storage** — the landing zone volume should comfortably hold the 21,500 rows of synthetic data (well under 100MB total), but watch for accidental large writes.
- **Lakebase tier** — smallest tier is adequate for the POC's 1,000-event volume but would not scale to production.

### Region-specific availability

Confirm at setup time that the chosen region supports:
- Lakebase (availability varies; check the current Databricks region matrix)
- AI Functions (most regions, but some laggards)
- Unity Catalog (all regions now, but feature parity can lag)

If the customer insists on a region without one of these, raise immediately — the spec cannot deliver Artifact 2 (consent log) without Lakebase.

## Design decisions the limits drove

Several choices in the spec exist because of trial constraints:

### One source, synthetic data
Because the trial has no custom networking, we can't connect to a real source database. Synthetic data in a workspace volume is the workable alternative. Bonus: no data-use agreement needed.

### Single shared cluster
Credit budget is finite. Multiple clusters with autoscaling would consume credits faster than necessary for a POC.

### Sample-based `ai_classify`
Rate limits on Model Serving mean full-row classification across 1,500 patients is neither needed nor affordable. Column-level classification on a 100-row sample is the pragmatic fit.

### No Lakewatch, no Module 04
Lakewatch's Private Preview status means it is not in the trial. Since Module 04's design depends on Lakewatch, we defer it to Phase 5 and out of the POC.

### Manual exit criteria checklist
Automated monitoring/alerting is outside the trial's natural envelope. The POC uses the Day 7 human checkpoint and Day 14 demo as primary quality gates.

## What to do when you hit a limit

If during build you discover a limit that wasn't anticipated:

1. Stop and confirm the limit with Databricks documentation.
2. Raise with the human collaborator.
3. Consider whether the limit can be worked around (sampling, different pattern, defer feature) or whether the scope must change.
4. Document the limit in this file so the next sprint's team benefits.

Do not:
- Assume a limit is permanent without checking current docs.
- Work around a limit by moving to a different Databricks product (e.g., Classic Databricks on the customer's own AWS) without explicit agreement.
- Hide the limit from stakeholders — mention it in the Day 14 demo so they understand what the POC proved and didn't prove.

## Post-POC migration considerations

When the POC moves to a customer's production workspace after Phase 1 approval, many of these limits disappear:
- Production workspaces have provisioned compute, not trial credits.
- Private Link and VPC peering enable real source-system connections.
- Enterprise SSO and service principals replace the trial's identity model.
- Private Preview features (Lakewatch, etc.) become available as they reach GA.

The spec's architecture is designed to transplant cleanly from trial to production — the schemas, patterns, and tests are unchanged; what changes is the surrounding infrastructure. This is a deliberate design principle. Do not introduce trial-specific shortcuts that would have to be unwound for production.
