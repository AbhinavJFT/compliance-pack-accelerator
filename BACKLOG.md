# Compliance Pack Accelerator — Backlog

Working list of items in flight. Originally seeded by the colleague's
DPDP-pack gap-analysis (2026-04-24) and the three-path ingestion demo
scope expansion. Now tracks post-ADR-0001 work after the multi-jurisdiction
M1–M4 cut-over went live (2026-04-26) and the open-question follow-ups
(Q2 pack versioning, Q3 loader validation) merged (2026-04-30).

> **For the multi-jurisdiction work**, the binding plan is
> [`docs/adr/0001-multi-jurisdiction-data-subject-routing.md`](docs/adr/0001-multi-jurisdiction-data-subject-routing.md).
> ADR-0001 itself is complete; open questions that fell out of M1–M4 are
> tracked here and crosslinked.

Legend: `[ ]` open · `[x]` done · `[-]` dropped/subsumed

---

## P0 — Live multi-jurisdiction state (done)

> **2026-07-02:** Per a UK/Europe-only go-to-market scope, the `dpdp_2023`
> (India) and `ccpa` (US) packs referenced throughout this section's
> milestone history have since been removed. Only `uk_gdpr` and `eu_gdpr`
> remain live — see `regulations/README.md`.

Live counts on the `compliance_pack` Unity Catalog (2-pack state, exact
numbers need re-verification via `scripts/regenerate_test_expected.py`):

- 2 regulation packs loaded simultaneously: `uk_gdpr@1.0.0`, `eu_gdpr@1.0.0`
- 26 multi-pack rules in `bronze.compliance_rules` (12 + 14)
- Gaps in `silver.compliance_gaps` tagged with `regulation_pack` (UK GDPR + EU GDPR)
- GB / EU / NULL principal mix (60/35/5 target split — the ADR-0001 Q3 "unmapped" tile)

ADR-0001 milestones (all merged to `main`):

- [x] **M1 Foundation** — pack_loader multi-pack accessors (`loaded_packs()`, `pack_for(jurisdiction)`, `derive_jurisdiction()`)
- [x] **M2 UK GDPR pack** — `regulations/uk_gdpr/` 9 files; multi-pack `bronze.compliance_rules` MERGE
- [x] **M3 UI surfaces** — pack-aware Genie `text_instructions` composer, DPIA template merge for multi-jurisdiction activities, dashboard `jurisdiction` filter
- [x] **M4 Cut-over** — `silver.customers_tagged.jurisdiction` column live; originally a 70/25/5 IN/GB/unmapped synthetic mix (now 60/35/5 GB/EU/unmapped since DPDP's removal, see 2026-07-02 note above); mixed-data smoke test green
- [x] **Q2 Pack versioning** — `version` field on every `pack.yaml`; threaded through DPIATemplate + DPIA prompt; included in `dpia_prompt_version()` hash
- [x] **Q3 Loader jurisdiction validation** — `validate_jurisdictions()` + `format_validation_report()` pure functions; phase1_bootstrap prints the report observationally
- [x] **EU GDPR pack** — `regulations/eu_gdpr/` 9 files; 14 rules, 24-language registry, EU SCCs + Schrems II framing
- [x] **CCPA pack** (removed 2026-07-02) — `regulations/ccpa/` 10 files; 16 rules, opt-out + DNS-DSS + GPC + SPI limit-use semantics, 7 US PII patterns (SSN/ITIN/EIN/DL/passport/bank/ZIP+4). Built and merged, then removed entirely per the UK/Europe-only scope decision.
- [x] **CCO dashboard** — Unmapped Principals tile (Q3 follow-up) added at Executive Overview x=2,y=0
- [x] **DPIA pipeline multi-pack wiring** — `pipelines/dpia_generator.py` + `notebooks/03_agent_bricks.py` no longer hardcode a single `regulation_pack`. The cron auto-derives applicable packs from the jurisdictions present in `customers/users/employees/patients_tagged`, calls `dpia_template_merge.template_for_activity()`, and records the contributors in a new `dpia_runs.regulation_packs ARRAY<STRING>` column (scalar `regulation_pack` retained for Streamlit / Lakeview backward-compat). Pure `_resolve_dpia_packs()` helper + 8 unit tests in `tests/test_dpia_multi_pack.py`. Closes the "merger exists but isn't wired into production" gap surfaced post-M3.

### Three-path ingestion demo (centerpiece, pre-ADR-0001)
**Self-contained POC — no external services.** Three ingestion *patterns* demonstrated in code with synthetic data:
1. Landing zone (Auto Loader) — the 5 existing synthetic tables cover this
2. Lakeflow Connect — simulated via direct-write bronze tables with Salesforce-shaped schema
3. Lakehouse Federation — simulated via view over a `federation_mock` schema

Reason: POC reviewed internally on Free Edition workspace (no account admin). External-service dependencies (AWS, SF, Postgres) create demo logistics risk without strengthening the approach-validation goal. Industry convention for tier-3 demos (Databricks `dbdemos`, Snowflake quickstarts) is self-contained.

All 3 patterns deliver into the same governance layer (classifier → pii_findings → personal_data_register). 36 findings across 10 silver objects.

---

## P1 — Next packs (priority order)

Each pack follows the now-proven contract: 9–10 YAML files + `pii_patterns.py`, zero core change. Each merges as its own PR.

- [ ] **PIPEDA (Canada)** — federal privacy law. Adds `CA` to `COUNTRY_TO_JURISDICTION`. Smaller surface than GDPR (10 fair-information principles); 8–10 rules expected. Adequate for federally regulated industries; Quebec's Law 25 + Alberta PIPA can come later as nested packs.
- [ ] **LGPD (Brazil)** — Lei Geral de Proteção de Dados, very GDPR-shaped. Adds `BR`. ANPD authority. Portuguese as primary locale + ten regional Portuguese dialects in `languages.yaml`.
- [ ] **POPIA (South Africa)** — Protection of Personal Information Act, Information Regulator. Adds `ZA`. Multi-language (11 official) similar in shape to EU GDPR.
- [-] **State-level US laws** (dropped 2026-07-02) — was: under the CCPA pack umbrella or as separate sub-packs: Virginia VCDPA, Colorado CPA, Connecticut CTDPA, Utah UCPA, Texas TDPSA, Oregon OCPA, Montana MCDPA, Iowa ICDPA, Tennessee TIPA, Florida FDBR. Moot — the CCPA pack itself was removed per the UK/Europe-only scope decision.

---

## P2 — Open questions from ADR-0001 (some now resolved)

- [x] **Q2 — Pack versioning** — semver field on `pack.yaml`, threaded through DPIA prompt + MLflow trace hash. Merged 2026-04-30.
- [x] **Q3 — Loader jurisdiction validation** — pure-function classification of observed jurisdictions into `mapped` / `null` / `unmapped_known` / `unmapped_unknown`. Merged 2026-04-30. Phase1_bootstrap prints the report observationally.
- [ ] **Q1 — Per-deployment / per-company rules** — overlay mechanism for client-specific rules that don't belong in a regulation pack (e.g., "this client mandates AES-256 even where the regulation only mandates 'appropriate encryption'"). Likely a `regulations/_overlays/<client_code>/` directory with the same shape as a pack but merge-on-top semantics.
- [ ] **Q4 — Pack-deprecation policy** — what happens when a regulation is repealed or superseded (e.g., a future amendment to EU GDPR or UK GDPR introduces a new penalty tier). Probably `pack.yaml` gets a `superseded_by` field and the loader emits a warning + dual-emits both packs' rules during a transition window.

---

## P3 — Polish + tooling (post-multi-pack)

- [ ] **CCO unmapped-principals tile** wired to per-jurisdiction filter — the new tile counts NULL globally; should respect the page's existing jurisdiction filter for drill-down.
- [ ] **Pack-bump CI guard** — fail any PR that changes `rules.yaml` / `rights.yaml` / `retention_defaults.yaml` without bumping the corresponding `pack.yaml::version`.
- [ ] **`scripts/lint_packs.py`** — pre-deploy validator: every rule cites a valid section; every right code is in `RIGHT_CATALOGUE`; every PII pattern declares `regulations=[]`; YAML keys are spelled correctly. Runs in CI + `deploy_all.sh`.
- [ ] **Genie config templating** — `configs/genie/*.yaml` now hardcode EU GDPR (€20M/€10M) and UK GDPR (£17.5M/£8.7M) penalty ceilings and article citations directly (updated 2026-07-02 from the old DPDP ₹-crore values), but still as static per-pack literals, not derived from `pack.yaml::max_penalty` at render time. Templating over `loaded_packs()` would let each pack contribute its own Genie hints dynamically. Tracked in detail as `GENIE-CFG` below.
- [ ] **Agent-prompt pack-aware refactor** — `governance_core/agent_prompts.py::COMPLIANCE_QA_SYSTEM` now says "UK/EU GDPR compliance assistant" (updated 2026-07-02) but is still a hardcoded literal, not composed from active packs' DPIA template names. Tracked as `AI-PROMPT-PACK` below.
- [ ] **Persona dashboard regeneration** — CCO/GC/CMO/CFO dashboards derive from the master `dashboards/compliance_overview.lvdash.json` (renamed 2026-07-02 from `dpdp_compliance.lvdash.json` — the master was already pack-agnostic) via `scripts/slice_dashboards.py`. Confirm each persona sees their pack's primary citations correctly.

---

## Deferred (acknowledge in scope doc, do not attempt before review)

- **2.1** — Dynamic column masks driven from `pii_findings` (new-source masking)
- **2.4** — Extend persona row filters beyond `consent_events_log`
- **3.3** — Paid-tier Lakebase + DSR portal uncomment path + test
- **4.1** — CI workflow for `tests/` with workspace auth
- **4.4** — CDF consent-withdrawal propagation test
- **4.5** — Automated persona-boundary runtime test (requires live persona users)
- **4.6** — Agent Bricks DPIA roundtrip validation
- **5.3** — Full externalization of workspace-specific literals (warehouse IDs, catalog names)
- **GENIE-CFG** — Move regulation-specific values out of `configs/genie/*.yaml` into the regulation pack. These YAMLs hardcode EU GDPR / UK GDPR penalty ceilings, labor rate, and article citations directly (updated 2026-07-02 from DPDP values, after DPDP/CCPA were removed). With both packs loaded, each will need templating (Jinja over `loaded_packs()` values, keyed off `pack.yaml::max_penalty`) or per-regulation YAMLs so a future third pack doesn't require another hand-edit. ADR-0001-acceptable tech debt — composer surfaces the pack identity at runtime, but the static text is still per-pack-hardcoded.
- **AI-PROMPT-PACK** — Move regulation-specific text in `governance_core/agent_prompts.py` (currently "UK/EU GDPR compliance assistant", updated 2026-07-02 from DPDP wording) into the active regulation pack. Either: (a) per-regulation prompt files (`regulations/<code>/agent_prompts.py`), or (b) keep templates generic and inject regulation metadata via `loaded_packs()` at render time. Same shape of decision as GENIE-CFG.
- **AI-MLFLOW-TESTS** — Add unit tests for `governance_core/agent_prompts.py` (render_dpia_user / render_compliance_qa_user with required-key check + JSON-encoding sanity) and a mocked `_invoke_llm()` retry test. Both pure-local, no Databricks needed.
- **AI-MLFLOW-PII-GUARD** — Runtime check or env-flag-gated assertion that `compliance_qa(question)` rejects raw customer identifiers when called outside the synthetic-data POC.
- **PII-NAME-VAT** (renamed 2026-07-02 from PII-NAME-GST after the SF simulation's India GST field was replaced with a UK VAT number) — Universal PII pattern library (`governance_core/pii_patterns/universal.py`) doesn't catch generic names or UK/EU VAT numbers. Names are intrinsically hard (false-positive prone); a VAT-number pattern (`^[A-Z]{2}\d{9,12}$`-ish, format varies per member state) is a clean addition. Adding it would surface another finding on `sf_accounts_tagged.vat_number`.

---

## Dropped (already addressed — no action)

- [-] **1.1** — Classifier `.collect()` issue — already fixed; `pipelines/classification_dlt.py:10-12` documents no driver-side collects
- [-] **1.2** — Single-pack bootstrap — superseded by ADR-0001 M2 multi-pack MERGE
- [-] **1.3** — `discovered_tables` "drift" — the 5-table list matches actual scanner coverage; no drift
- [-] **2.5** — Phase-0 pack integration — verified live; all 4 packs load + route per-principal
- [-] **3.5** — Retention job unscheduled — declared at `resources/jobs.yml:52-70` in dry-run mode by default
- [-] **3.6** — Fivetran typed-silver mirror — replaced by Lakeflow Connect in P0
- [-] **5.1** — Fivetran vs native narrative — resolved by P0 three-path demo
- [-] **DPIA-MULTIREG** — Multi-regulator DPIA citation in a single document — delivered via `governance_core/dpia_template_merge.py`

---

## Decisions resolved

- **SF schema depth** — 3 standard objects (Lead/Contact/Account). Opportunity/Case deferred — they don't add a *new* ingestion-pattern story.
- **Federation source** — local `federation_mock` schema with passthrough silver views. Not `samples` catalog (no real customer PII).
- **Persona row filter on SF/federation** — deferred to Phase 1.
- **Pack version scheme** — semver per pack; bump MAJOR on rule_id removal/rename, MINOR on new rule/right, PATCH on wording-only changes. Documented inline in each `pack.yaml::version` comment.
- **EU/EEA member-state granularity** — single `EU` pack for all 27 member states + EEA non-EU (IS/LI/NO). A future ADR may split per-member-state if national-DPA divergences (cookies, transfers, statutory retention) demand pack-per-country; current cross-cutting differences are captured in `retention_defaults.yaml::statutory_overrides`.
- **US scope dropped** (2026-07-02) — the CCPA pack and any US state-law granularity question are moot; this platform is scoped to UK/Europe only.
