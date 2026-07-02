"""Regulation-agnostic consent-event schema contract.

The consent event schema is shared across every privacy regulation. What varies
per regulation is (a) which `purpose` values are meaningful and (b) how withdrawal
semantics work (opt-in default under GDPR/PIPEDA vs. opt-out-style regimes
elsewhere). The schema itself is universal.

## Migration status (Phase 0)

**SKELETON — not yet wired into callers.** The authoritative schema today lives in
two places:

  - `pipelines/phase1_bootstrap.py` CREATE TABLE for `compliance.consent_events_log`
    (~line 100)
  - `schemas/consent_events.sql` (legacy spec file, kept as historical reference)

Next Phase-0 iteration will consolidate into `CONSENT_EVENT_SCHEMA` below, imported
by phase1_bootstrap so the table DDL becomes `f"CREATE TABLE ... ({schema_sql})"`
rather than a hardcoded column list.

## Schema contract (universal — regulation-agnostic columns)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| event_id | STRING | NO | Monotonic per-principal identifier |
| data_principal_id | STRING | NO | FK to principal (customer_id in POC) |
| event_type | STRING | NO | granted / withdrawn / modified / declined |
| event_timestamp | TIMESTAMP | NO | When the principal acted |
| notice_id | STRING | NO | Which notice was shown |
| notice_version | INT | NO | Version of notice seen at consent |
| notice_language | STRING | NO | ISO 639 + region (en-GB, de-DE, fr-FR) |
| channel | STRING | NO | mobile_app / web / call_center / paper |
| purpose | STRING | NO | One of the pack's defined purposes |
| purpose_grant_status | STRING | NO | granted / declined / withdrawn |
| ip_address | STRING | YES | Captured for audit, masked downstream |
| user_agent | STRING | YES | As above |
| consent_capture_method | STRING | NO | opt_in_toggle / opt_out_toggle / signature |
| retention_clock_start | TIMESTAMP | NO | When retention period begins |
| retention_duration_days | INT | NO | From pack's retention_defaults.yaml |
| superseded_by_event_id | STRING | YES | Points at the event that superseded this one |
| partner_source_id | STRING | YES | If captured via third-party partner |
| synced_at | TIMESTAMP | NO | When ingested into the compliance log |
| event_date | DATE GENERATED | NO | Partitioning column |
"""

# TODO(phase-0): populate CONSENT_EVENT_SCHEMA from the current phase1_bootstrap DDL
# and have phase1_bootstrap import it rather than inlining the column list.

CONSENT_EVENT_SCHEMA: dict = {
    # filled in during Phase-0 migration
}
