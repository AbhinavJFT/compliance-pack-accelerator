# regulations/ — Regulation packs (Layer 3 of the framework)

Each subdirectory is one regulation pack. Packs bundle the regulation-specific
configuration that the platform core consumes at bootstrap time. See
[`docs/modular_framework.html`](../docs/modular_framework.html) §3–§4 for the full
framework.

## Current packs

| Directory | Regulation | Status | Jurisdiction |
|---|---|---|---|
| `dpdp_2023/` | Digital Personal Data Protection Act 2023 | Phase 0 skeleton — values migrate from current hardcoded locations | India |
| `uk_gdpr/` | UK GDPR + Data Protection Act 2018 | Phase 1 target | United Kingdom |
| `eu_gdpr/` | EU General Data Protection Regulation | Phase 2 | EU / EEA |
| `ccpa/` | California Consumer Privacy Act / CPRA | Phase 2 | California, USA |
| `pipeda/` | Personal Information Protection and Electronic Documents Act | Phase 2 | Canada |

## Pack contract

Every pack directory must contain these files:

| File | Purpose |
|---|---|
| `pack.yaml` | Metadata — name, code, jurisdiction, authority, effective date, penalty structure, which rights/PII packs activate |
| `rules.yaml` | Compliance rules — each with `rule_id`, `rule_type`, `severity`, `citation`, `applicable_categories`, `description`, `remediation` |
| `rights.yaml` | Which rights from [`governance_core.rights.RIGHT_CATALOGUE`](../governance_core/rights.py) activate, plus SLAs, citations, exemptions, default reason text |
| `retention_defaults.yaml` | Per-purpose retention periods (days) |
| `notice_template.md` | Notice body as a Jinja template with `{{ placeholders }}` |
| `languages.yaml` | Language registry: `[{code, script, model_support_tier, human_review_required}]` |
| `residency.yaml` | Allowed countries, adequacy list, blocked countries |
| `breach_sla.yaml` | Notification deadline, authority contact, required content |
| `pii_patterns.py` | Region-specific PII patterns (Aadhaar, NINO, SSN, SIN, ...). Optional — universal patterns live in `governance_core/pii_patterns/universal.py` |
| `dpia_template.yaml` | DPIA Auto-Generator (Agent 1) prompt template — `legal_framework_name`, `section_citation_style`, `system_prompt`, optional `section_descriptions` overrides. The 8 DPIA section keys themselves are regulation-agnostic and live in `governance_core/dpia.py::DPIASections`; this file is the regulation-specific framing the model sees |

## Authoring a new pack

1. Copy `dpdp_2023/` to `<new_code>/` as a template.
2. Rewrite every value to cite the new regulation's sections / SLAs / PII formats.
3. Update the language registry for the new jurisdiction's supported languages.
4. `export REGULATION_PACK=<new_code>` and re-run `phase1_bootstrap` — the platform
   code stays unchanged; values come from your pack.
5. Run the full test suite (`tests/test_*.py`) against the new pack to verify
   structural invariants.

Pack contents are (largely) not code — they're configuration. A regulation pack
can be authored in a few days by someone who understands the regulation, without
engineering support.
