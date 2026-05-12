# regulations/ — Regulation packs (Layer 3 of the framework)

Each subdirectory is one regulation pack. Packs bundle the regulation-specific
configuration that the platform core consumes at bootstrap time. See
[`docs/modular_framework.html`](../docs/modular_framework.html) §3–§4 for the full
framework and
[`docs/adr/0001-multi-jurisdiction-data-subject-routing.md`](../docs/adr/0001-multi-jurisdiction-data-subject-routing.md)
for the per-data-subject routing decision that makes multi-pack mode possible.

## Current packs

| Directory | Regulation | Status | Jurisdiction | Pack version |
|---|---|---|---|---|
| `dpdp_2023/` | Digital Personal Data Protection Act 2023 | Live | India (`IN`) | `1.0.0` |
| `uk_gdpr/` | UK GDPR + Data Protection Act 2018 | Live | United Kingdom (`GB`) | `1.0.0` |
| `eu_gdpr/` | EU General Data Protection Regulation (Regulation (EU) 2016/679) | Live | EU / EEA (`EU`) | `1.0.0` |
| `ccpa/` | California Consumer Privacy Act + California Privacy Rights Act | Live | California, USA (`US`) | `1.0.0` |
| `pipeda/` | Personal Information Protection and Electronic Documents Act | Planned (P1) | Canada (`CA`) | — |

All four live packs MERGE their rules into `bronze.compliance_rules` at
deploy time (51 rows total: 9 + 12 + 14 + 16). Each gap row in
`silver.compliance_gaps` is tagged with `regulation_pack` so per-jurisdiction
filters and per-pack severity rollups work out of the box.

## Pack contract

Every pack directory must contain these files:

| File | Purpose |
|---|---|
| `pack.yaml` | Metadata — `name`, `code`, `jurisdiction`, `version` (semver), `effective_date`, `supervising_authority`, `primary_locale`, `penalty_structure`, `max_penalty`, plus an `activates:` block listing which rights / PII pattern packs / DPO posture / minor age / consent default / transfer mechanisms the pack switches on |
| `rules.yaml` | Compliance rules — each with `rule_id`, `rule_type`, `severity`, `regulations[]`, `applicable_categories[]`, `citation`, `description`, `remediation` |
| `rights.yaml` | Which rights from [`governance_core.rights.RIGHT_CATALOGUE`](../governance_core/rights.py) activate, plus SLAs (`sla_days`, `extendable_to_days`), `citation`, `exemptions[]`, `default_reason_text`, `implemented_in` |
| `retention_defaults.yaml` | Per-purpose retention defaults (days) + `statutory_overrides[]` for laws that mandate longer retention regardless of purpose |
| `notices.yaml` | Seeded notice bodies (one row per `(notice_id, version, language)` into `compliance.notice_versions`); the primary-locale notice is hand-authored, other locales are machine-translated downstream |
| `languages.yaml` | Language registry: `[{code, script, speakers_l1_millions, model_support_tier, human_review_required, seeded_by_poc, notes}]` — drives the multi-language notice generator |
| `residency.yaml` | `allowed_countries[]` (adequacy / EEA / customer-defined allow-list), `restricted_countries_by_sector[]`, `blocked_countries[]`, `apply_filter_to[{table, column}]` |
| `breach_sla.yaml` | `notification.to_authority` + `notification.to_data_subjects` deadlines, content checklists, exemptions, plus `parallel_obligations[]` for non-privacy regulators (NIS 2, DORA, HIPAA, SEC, etc.) |
| `pii_patterns.py` | Region-specific `PIIPattern` instances exposed via `IN_SPECIFIC_PATTERNS` (variable name kept for historical / loader-contract reasons; not jurisdictional). Optional — universal patterns live in `governance_core/pii_patterns/universal.py` |
| `dpia_template.yaml` | DPIA Auto-Generator prompt template — `legal_framework_name`, `section_citation_style`, `system_prompt`, optional `section_descriptions` overrides. The 8 DPIA section keys themselves are regulation-agnostic and live in `governance_core/dpia.py::DPIASections`; this file is the regulation-specific framing the model sees |

### `version` field (ADR-0001 Q2)

Every `pack.yaml` declares a `version:` field (semver). Bump rules:

| Bump | When |
|---|---|
| MAJOR | A `rule_id` is removed or renamed; a right is dropped; a default-consent semantic flips (opt-in → opt-out) |
| MINOR | A new rule, right, retention purpose, language, or PII pattern is added |
| PATCH | Wording-only changes — citation tidy-ups, remediation text rewrites, description clarifications |

The version is exposed via `Pack.version`, threaded into `DPIATemplate.pack_version`,
prepended to the DPIA system prompt as `[regulation pack v<sem>]`, and folded into
the `dpia_prompt_version()` content hash so MLflow traces fork on every pack bump.

## Authoring a new pack

1. Copy a similarly-shaped existing pack (e.g. `eu_gdpr/` if your regulation is GDPR-shaped; `ccpa/` if it's notice-and-opt-out-shaped) to `<new_code>/`.
2. Rewrite every value to cite the new regulation's sections / SLAs / PII formats. Each YAML file's header comment explains the regulation-specific context.
3. Update `languages.yaml` for the new jurisdiction's supported languages.
4. Extend `governance_core/pack_loader.COUNTRY_TO_JURISDICTION` so country names from your principal data route to the new pack's `jurisdiction` code.
5. Deploy — every pack under `regulations/` loads simultaneously; no env-var flip required.
6. Run `tests/test_pack_loader_multi.py` + `tests/test_jurisdiction_validation.py` + `tests/test_pack_versioning.py` to verify structural invariants.
7. Bump `version` to `1.0.0` (or higher for an evolution of an existing pack).

Pack contents are (largely) not code — they're configuration. A regulation pack
can be authored in a few days by someone who understands the regulation, without
engineering support.
