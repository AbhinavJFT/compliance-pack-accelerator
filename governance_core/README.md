# governance_core/ — Regulation-agnostic governance core

This directory holds the **Layer 1 + Layer 2** components from the 4-layer framework
(see `docs/modular_framework.html`). Everything in here is regulation-agnostic —
identical under DPDP-India, UK GDPR, CCPA, PIPEDA, etc.

## What lives here

| File | Purpose | Currently hardcoded in |
|---|---|---|
| `pii_patterns/universal.py` | Universal PII patterns (email, phone, card, name, DOB, IP, medical, address) | `schemas/pii_patterns.py` lines ~130-420 |
| `rights.py` | Full superset of data-subject rights (access, rectification, erasure, portability, objection, restriction, no-automated-decision). Each regulation pack activates a subset. | Implicit today — only access+erasure exist in DSR scripts |
| `consent_model.py` | Consent event schema contract — column set, types, invariants. | `pipelines/phase1_bootstrap.py` ~line 100 (table DDL) |
| `pack_loader.py` | Reads `REGULATION_PACK` env var at bootstrap, loads pack YAML/py files, exposes typed accessors (`get_rules()`, `get_retention_default(purpose)`, `get_residency_filter_sql()`, `get_languages()`, ...) | Not yet built — values live directly inside `phase1_bootstrap.py` |

## What does NOT live here

- Any regulation-specific value (rule citations, retention days, notice text,
  jurisdiction filters, region-specific PII patterns). Those go in `regulations/<pack>/`.
- The persona layer (CCO/GC/CMO/CFO). Personas are in `scripts/` and are
  regulation-agnostic role definitions — not part of the platform core either.
- Storage / infra (catalog names, schema names, volume paths). Those stay in
  `databricks.yml` + `resources/` as they are today.

## Import contract

Consumers (e.g. `pipelines/phase1_bootstrap.py`, `scripts/apply_pii_masks.py`) should
import only from `governance_core.*` for regulation-agnostic behavior, and from
`regulations.<active_pack>.*` for regulation-specific values. `pack_loader.py` is the
single entry point that hides pack location from the rest of the code.

## Status

**Phase 0 skeleton — files below are placeholders with TODO markers.** Values will be
migrated from the current hardcoded locations in the next Phase 0 iteration once the
structure is reviewed and merged.
