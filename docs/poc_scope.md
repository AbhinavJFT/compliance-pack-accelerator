# Compliance Pack Accelerator — POC Scope and Phase-1 Boundary

This is a one-pager for reviewers. It says exactly what the POC delivers,
what it stops short of, and what is tracked for Phase 1. The intent is
to prevent two failure modes: (a) reviewers expecting a full
multi-regulation production system, and (b) reviewers under-counting
what's already live.

**Architectural foundation:** the POC is built around the regulation-pack
abstraction governed by [ADR-0001](adr/0001-multi-jurisdiction-data-subject-routing.md).
This deployment is scoped to **UK and Europe** — the seed packs are
**UK GDPR** and **EU GDPR**, both loaded simultaneously; every "Module"
below is exercised end-to-end against them. (The India (DPDP) and US
(CCPA) packs originally in this platform have been removed.) The
architecture's per-data-subject routing model means a multinational
customer running both packs applies UK GDPR rules to UK principals and
EU GDPR rules to EU principals simultaneously, in the same database.

The authoritative work-tracking list is `BACKLOG.md`.

---

## In scope (delivered, runnable, reviewable)

The POC delivers **Modules 01 and 02 at full spec depth**, with
demo-grade slices of 03, 05, and 06 to prove extensibility. All modules
are exercised against the EU GDPR seed pack; UK GDPR re-runs them
with a different pack's rules under the same code paths.

### Module 01 — PII discovery & data inventory (full)

Status: **COMPLETE** end-to-end

- **PII pattern library** — 11 universal + region-specific packs (5 UK-specific: NHS Number, NINO, UTR, UK postcode, UK phone; 8 EU-specific: IBAN, EU VAT, DE/FR/IT/ES national IDs, EU phone, EU passport)
- **Vectorized DLT classifier** — `pipelines/classification_dlt.py`, no driver-side `.collect()` on data, scans every silver column. The list of silver objects to scan is sourced dynamically from `bronze.data_sources` (see decision 6 below) — adding a new ingestion path is one row in `scripts/seed_data_sources.py:DATA_SOURCES_SEED` (which runs in `deploy_all.sh` ahead of the medallion refresh), no classifier code change.
- **Three ingestion patterns** all feeding the same governance layer:
  - **Landing zone (Auto Loader)** — 5 silver tables (`employees_tagged`, `customers_tagged`, `patients_tagged`, `transactions_tagged`, `users_tagged`)
  - **Lakeflow Connect simulation** — 3 silver tables (`sf_leads_tagged`, `sf_contacts_tagged`, `sf_accounts_tagged`), populated by direct-write seed (no Auto Loader — that's the visible pattern signal)
  - **Federation simulation** — 2 silver views (`federation_lead_scoring_tagged`, `federation_campaign_response_tagged`) over a `federation_mock` schema
- **Living `personal_data_register`** — PII columns auto-derived from `pii_findings` (exact count shifts with schema/pattern changes — see `tests/_baseline.json`)
- **UC column masks** on PII columns (5 mask UDFs in `compliance.mask_*`)
- **UC column tags** auto-applied from findings via `apply_uc_tags.py`
- **Persona governance layer** — 4 sliced dashboards + 4 scoped Genie spaces (CCO/GC/CMO/CFO) with UC-enforced boundaries

### Module 02 — Consent intelligence (full)

Status: **COMPLETE** end-to-end

- **Immutable consent event log** — `compliance.consent_events_log`, 1,000 events / 292 principals / 6 purposes / 4 channels
- **Granular per-purpose consent** — supersession via `superseded_by_event_id`
- **Notice version tracking** — `compliance.notice_versions` with each pack's full language set (hand-authored primary locale + machine-translated, watermarked)
- **`has_active_consent()` UDF** — single-source-of-truth for "can I email customer X for purpose Y?"
- **Marketing-eligible audience view** — `gold.marketing_eligible_principals` filters down at query time
- **Consent withdrawal propagation** — Delta CDF on silver tables drives downstream re-aggregation

### Module 03 — DSR (demo-grade slice)

Status: **MINIMAL VIABLE STUB + automated chain test**

- `scripts/dsr_discovery.py` — UC lineage-based PII column discovery for a principal
- `scripts/dsr_erasure.py` — Delta DELETE + VACUUM with audit-bundle JSON; built-in `--confirm` gate (dry-run by default)
- Test principal `customer_04217` (Oeshi Desai) walks the full lifecycle
- `tests/test_dsr_e2e.py` (added 2026-04-27) chains discovery → erasure dry-run → audit-bundle, 11 assertions. Non-destructive — verifies the chain without consuming the principal.
- **Not in scope**: a Databricks App–hosted DSR portal (commented out — paid-tier feature; the script-based path is the free-tier equivalent)

### Module 05 — Compliance audit (demo-grade slice)

Status: **PARTIAL**

- `silver.compliance_gaps` — 26 multi-pack rules across 2 regulation packs (UK GDPR / EU GDPR) drive gaps with severity tiers, each tagged by source pack
- Rules are regulation-pack-driven (ADR-0001 M2 live) — every pack in `regulations/` MERGEs its rules at phase1_bootstrap time
- Penalty-weighted exposure rendered via the CFO Genie agent (EU GDPR €20M/€10M, UK GDPR £17.5M/£8.7M higher/standard-tier ceilings)
- **DPIA generator** — productionised in Phase 4: structured pydantic output, quarterly cron (`dpia_generator` job, UNPAUSED on deploy), `compliance.dpia_runs` table with status workflow (draft → approved), `compliance.dpia_artifacts` volume for the JSON+PDF artefacts, and a Databricks Review App (`compliance-dpia-review`) where CCO/GC approve and CFO views read-only
- **Not in scope**: real-time scoring engine

### Module 06 — Retention (demo-grade slice)

Status: **STUB ONLY**

- `pipelines/retention_enforcement.py` — purge logic per `retention_defaults.yaml`
- Bundle job declared in `resources/jobs.yml` with default `mode=dry-run`
- **Not in scope**: tokenization vault integration, scheduled production purges

### Cross-cutting: regulation-pack framework (Phase 0 → ADR-0001 multi-pack, full)

Status: **COMPLETE** — Phase 0 merged 2026-04-24 (`7fce83f`); ADR-0001 M1–M4 + Q2/Q3 follow-ups merged through 2026-05-12. DPDP (India) and CCPA (US) packs removed 2026-07-02 per UK/Europe-only scope.

- `governance_core/` — regulation-agnostic core (multi-pack loader with `loaded_packs()` / `pack_for(jurisdiction)` / `derive_jurisdiction()` / `validate_jurisdictions()`, universal patterns, rights catalogue, consent model, DPIA template merge for multi-jurisdiction activities).
- Two regulation packs ship today, both loaded simultaneously:
  - `regulations/uk_gdpr/` — UK GDPR + DPA 2018 (12 rules, NHS Number / NINO / UTR / UK postcode patterns)
  - `regulations/eu_gdpr/` — EU GDPR Regulation 2016/679 (14 rules, 24 official EU languages, IBAN / EU VAT / DE-FR-IT-ES national IDs)
- Pack semver (ADR-0001 Q2) — every `pack.yaml` declares a `version` field; threaded into DPIA prompt + MLflow trace hash so prompt-version bumps fork traces cleanly.
- Adding a PIPEDA / LGPD / POPIA pack is authoring 9–10 new YAML files — no core changes.

### Cross-cutting: AI agents (full)

Status: **COMPLETE**

- DPIA generator, Compliance Q&A, PII classifier — all on Foundation Model serving
- MLflow tracing, retries + timeouts, versioned prompts (`governance_core/agent_prompts.py`)
- `scripts/setup_agent_bricks.py` (added 2026-04-27) — headless infra check: serving endpoint READY, MLflow experiment idempotent create, prompts module loads. Runnable inside `deploy_all.sh` (step `agents`) and standalone with `--smoke` for an actual LLM round-trip
- **Caveat**: the Compliance Q&A prompt is not yet fully pack-aware; Phase-1 work tracked as `AI-PROMPT-PACK`

---

## Explicitly NOT in scope (deferred to Phase 1)

These are tracked in `BACKLOG.md` under "Deferred to Phase 1." None of
them are bugs; they are scope decisions made because the POC's job is
to prove the *approach* works, not to deliver every production feature.

| Phase-1 item | Why deferred |
|---|---|
| Dynamic column masks (drive `pii_column_masks.sql` from `pii_findings`) | Static SQL is acceptable for 10 silver objects; auto-generation is a productionization concern |
| Persona row filters beyond `consent_events_log` | Demo personas don't need cross-table row scoping; a real deployment would |
| Lakebase + Databricks-App-hosted DSR portal | Lakebase is a paid-tier feature unavailable on Free Edition |
| CI workflow for the test suite | Requires workspace auth in CI; mechanical setup, not an architectural concern |
| CDF withdrawal-propagation test | The mechanism works (verified manually); a regression test is productionization |
| Persona-boundary runtime test (auto) | Requires 4 logged-in persona users; manual procedure documented |
| Agent Bricks DPIA roundtrip test | Validates output quality, which is non-deterministic — production-quality test design is a separate task |
| Workspace-portability of literals | Each teammate currently edits one URL; a config-driven path is convenience, not architecture |
| Regulation-specific values out of YAMLs (`GENIE-CFG`, `AI-PROMPT-PACK`) | First UK GDPR pack will exercise this. Templating ahead of a real second pack risks over-design |
| Universal pattern lib gaps (`PII-NAME-GST`) | Names are intrinsically false-positive-prone; GST is a clean addition for Phase 1 |

---

## Real, before-review polish remaining (BACKLOG P1)

Tracked separately because these *are* worth doing pre-review:

- **3.1** — `scripts/deploy_all.sh` (one-shot deploy)
- **3.2** — README "Step 0" + workspace_host env-var
- **4.2** — Post-deploy smoke test (`pii_findings >= 36` across all 3 ingestion patterns)
- **5.2** — This document

---

## Decision log (the choices reviewers will ask about)

1. **Self-contained POC, no external services** (2026-04-24). Three ingestion *patterns* shown via synthetic data; no AWS/SF/Postgres dependencies. Reason: tier-3 demo convention (Databricks `dbdemos`, Snowflake quickstarts), Free Edition workspace constraints. The S3 external-volume experiment from earlier was rolled back.

2. **Free Edition workspace, no account-admin** (2026-04-24). Persona OAuth apps cannot be self-served; PAT auth is the only option for external integrations.

3. **Phase-0 regulation-pack refactor merged before three-path expansion** (2026-04-24). Means the new ingestion paths benefit from the pack framework: when UK GDPR is authored later, the existing 8 silver tables + 2 views are already pack-aware.

4. **Self-contained federation via `federation_mock` + silver views** (2026-04-27). Views (not tables) are the visible code-shape signal that distinguishes Federation from Lakeflow Connect ingestion.

5. **Genie scope expanded for CCO only in B-pass** (2026-04-27). Other personas have narrow domains by design; a per-persona expansion is documented but not done.

6. **Classifier reads from `bronze.data_sources`, not a hardcoded list** (2026-04-27, Day 1). Closes colleague's gap **1.2** (data_sources never seeded) + **2.2** (classifier hardcoded). The 10 canonical rows (5 Auto Loader + 3 Salesforce + 2 federation) are MERGEd by `scripts/seed_data_sources.py` in the `seed_ds` step of `deploy_all.sh` (added 2026-04-28 because seeding in phase1_bootstrap was too late — the medallion refresh fires before phase1, and the classifier needs `data_sources` already populated). Phase1_bootstrap.py:§2.5 keeps the same MERGE as a partial-deploy backstop. Fresh deploys before `seed_ds` runs use a 5-table fallback list inside `_resolve_silver_tables()`.

---

## What a reviewer should run

1. `scripts/configure_workspace_host.sh https://<their-host>` (one-time)
2. `scripts/deploy_all.sh` — single command, 19 idempotent steps (UC bootstrap → bundle → synthetic → medallion → SF + federation seeders → seed data_sources → refresh → phase1_bootstrap → tags + masks + filters → multilang → agents → smoke → Phase-2 personas → app_deploy → app_perms → dpia_first_run)
3. `python3 tests/test_dsr_e2e.py` — DSR chain (11 checks; not part of deploy_all)
4. Open the dashboard, query each persona's Genie, run a DSR walkthrough on `customer_04217`

Expected end state (post-DPDP/CCPA removal, 2026-07-02 — exact counts
below need re-verification against a live deploy via
`scripts/regenerate_test_expected.py --write`; pre-removal counts are
no longer accurate since India-specific PII columns were dropped and
two packs were removed):
- **PII findings** across 10 silver objects (universal + UK/EU-specific
  patterns from governance_core/ matched on the silver tables).
- **Compliance gaps**, tagged by source pack: UK GDPR + EU GDPR.
- **26 compliance rules** loaded across **2 regulation packs**:
  12 UK GDPR + 14 EU GDPR, each pack at semver v1.0.0.
- **Column masks** across silver + federation_mock.
- **Mixed-jurisdiction customer base** in `silver.customers_tagged`:
  a 60/35/5 GB/EU/unmapped mix (the ADR-0001 Q3 "unmapped principals"
  bucket surfaced on the CCO Executive Overview tile); same per-row
  routing across the other customer-level tables.
- **4 working Genie agents** (CCO/GC/CMO/CFO), with `text_instructions`
  auto-composed from both loaded packs.
- **Productionised DPIA generator** with quarterly cron + Review App + pack-
  version-stamped prompts + multi-regulator citations (Art. 35 EU/UK GDPR).
- All regression suites green: M1 pack_loader 10/10, M3 composers 11/11,
  Q2 versioning 6/6, Q3 validation 8/8 (re-run against the 2-pack state;
  M4 mixed-jurisdiction smoke requires a live workspace to verify).
