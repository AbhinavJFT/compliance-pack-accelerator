{# DPDP India 2023 — Consent notice template.

     Phase 0 skeleton: the 3 hardcoded notice bodies in
     pipelines/phase1_bootstrap.py:~482-554 (English, Hindi, Tamil) will move
     here as a single Jinja template with {{ placeholders }} resolved at render
     time. Per-language localisation is handled by passing a translated
     placeholder dict; no separate template per language.

     Post-migration, phase1_bootstrap renders this template once per language
     in regulations/dpdp_2023/languages.yaml, MERGing the result into
     compliance.notice_versions.

     The template MUST end with the DPDP Act citation — regulators treat this
     as evidence of informed consent.
 #}

{{ company_name }} collects and processes your personal data for the following purposes:

{% for purpose in purposes %}
{{ loop.index }}. {{ purpose.label }}  ({{ purpose.legal_basis }})
{% endfor %}

You can withdraw consent at any time via account settings or by contacting our DPO.
This notice complies with the Digital Personal Data Protection Act 2023.

---
Notice ID: {{ notice_id }}
Version: {{ version }} · Language: {{ language }} · Effective: {{ effective_from }}
