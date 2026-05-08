# DPDP glossary

Terms defined as the Digital Personal Data Protection Act 2023 uses them. This is a working glossary for the POC — not legal advice. When in doubt, defer to the statute or to the General Counsel.

## Core terms

**Data Fiduciary** — any person who alone or in conjunction with others determines the purpose and means of processing of personal data. The organization running this POC is a data fiduciary.

**Data Principal** — the individual to whom personal data relates. In the context of a child or person with a disability, includes the parent or lawful guardian. In this POC, `customer_04217` is a data principal.

**Data Processor** — any person who processes personal data on behalf of a data fiduciary. The POC does not cover processor relationships; they belong to Module 0's vendor registry.

**Personal Data** — any data about an individual who is identifiable by or in relation to such data. This is broad by design; the platform's PII taxonomy in §4.2 is a concrete decomposition.

**Processing** — a wholly or partly automated operation performed on digital personal data. Includes collection, recording, organisation, structuring, storage, adaptation, retrieval, use, alignment, indexing, sharing, disclosure, erasure, and destruction.

**Significant Data Fiduciary (SDF)** — a data fiduciary notified by the Central Government as such, based on volume of personal data processed, sensitivity, risk to data principals, and other factors. SDFs have additional obligations including DPIA, independent audit, and DPO appointment.

## Rights-related terms

**Right to Information** — a data principal's right to obtain from the data fiduciary, among other things, a summary of personal data being processed, processing activities, and identities of sharing recipients.

**Right to Correction and Erasure** — a data principal's right to have their personal data corrected if inaccurate or misleading, completed if incomplete, updated, or erased if no longer necessary.

**Right to Grievance Redressal** — a data principal's right to a readily available means of grievance redressal provided by the data fiduciary.

**Right to Nominate** — a data principal's right to nominate any other person who shall exercise their rights in the event of death or incapacity.

**Data Subject Request (DSR)** — umbrella term this POC uses for any exercise of the above rights. Module 03 handles all four rights types.

## Consent-related terms

**Consent** under DPDP must be free, specific, informed, unconditional, and unambiguous with clear affirmative action. This is the "CSIUA" standard that the POC's consent schema (§5.4) is designed to meet.

**Notice** — a document provided to the data principal before or at the time of seeking consent, describing the personal data sought, the purpose of processing, the manner of exercising rights, and the grievance redressal process. The POC's `notice_versions` table stores every notice ever shown.

**Purpose Limitation** — the principle that personal data may only be processed for the specific purpose for which consent was given. The POC's `purpose` enum in `consent_events` is the operational manifestation.

**Legitimate Use** — a category of lawful processing that does not require consent, including for the specified purpose for which the data principal has voluntarily provided data, performance of any function of the State, fulfilment of any obligation under law, compliance with any judgment or decree, for medical emergency, etc.

**Withdrawal of Consent** — the data principal's right to withdraw consent at any time with ease comparable to the ease with which it was given. The POC's withdrawal propagation mechanism (§5.8) implements this obligation.

## Institutional terms

**Data Protection Board of India (DPBI)** — the statutory body established under the Act for inquiries, compliance oversight, and imposition of penalties. The POC's audit trail is designed for DPBI inspection readiness.

**Data Protection Officer (DPO)** — an individual appointed by a Significant Data Fiduciary who represents the SDF under the Act and is the primary contact for grievances. The DPO's contact appears on every notice.

**Consent Manager** — a registered entity that enables a data principal to manage consent through an accessible, transparent, and interoperable platform. Not in scope for this POC.

## Breach and notification

**Personal Data Breach** — any unauthorised processing, accidental disclosure, acquisition, sharing, use, alteration, destruction, or loss of access to personal data that compromises its confidentiality, integrity, or availability.

**72-hour notification** — a data fiduciary is obligated to notify the DPBI of a personal data breach without delay, per the procedures prescribed. The POC's Module 04 targets a well-under-72-hour response, but Module 04 is out of scope for the 14-day sprint.

## Penalties

**Section 33 penalties** — the Act specifies penalties for various contraventions, with maximums up to ₹250 crore per contravention for the most serious failures. The penalty-weighted scoring in Module 05 references this structure.

## POC-specific usage

**Personal Data Register** — the POC's phrase for the living inventory of PII columns maintained by Module 01. Not an Act-defined term; it is the operational artifact that makes the Act's "Know your data" obligation tractable.

**Compliance Score** — the POC's phrase for Module 05's aggregate score. Out of scope for the 14-day sprint; included for terminology consistency with the Phase 1 roadmap.

**Residual Retention** — the POC's phrase for personal data that cannot be erased immediately due to legal retention obligations (e.g., banking records under the Banking Regulation Act). The residual retention register is the POC's mechanism for tracking scheduled future erasure.

## What this glossary does not cover

- **Cross-border data transfers** — the Act's provisions under Section 16, including the Central Government's power to restrict transfers to specific countries. Not in POC scope.
- **Children's data** — the Act's heightened protections for personal data of children (persons under 18). The POC's synthetic data includes a 3% under-18 subset to test the age-gate path, but full children's-data handling is Phase 1 work.
- **Research and statistical processing** — the Act's carve-outs for research and archiving purposes under Section 17. Not in POC scope.

When these topics come up in stakeholder conversations, defer to the General Counsel for authoritative interpretation.
