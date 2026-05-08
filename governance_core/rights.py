"""Full superset of data-subject rights across privacy regulations.

Each regulation pack activates a subset of these via its `rights.yaml`. The platform
ships only the schema + the universal right definitions; what the pack says is active
determines what the DSR scripts (`scripts/dsr_discovery.py`, `scripts/dsr_erasure.py`,
future `dsr_rectification.py` / `dsr_portability.py` / ...) will enact.

## Rights universe

| Right | DPDP | GDPR (UK/EU) | CCPA/CPRA | PIPEDA | Notes |
|---|---|---|---|---|---|
| `access` | §11 | Art. 15 | §1798.100 | Principle 9 | Universal — implemented today in `dsr_discovery.py` |
| `rectification` | §12(a) | Art. 16 | CPRA §1798.106 | Principle 9 | Correction of inaccurate data |
| `erasure` | §12(b) | Art. 17 | §1798.105 | (via correction) | Implemented today in `dsr_erasure.py` |
| `portability` | — | Art. 20 | — | — | GDPR-specific; structured export to another controller |
| `objection` | §13 | Art. 21 | §1798.120 (sale) | Principle 3 | Opt-out of processing / sale |
| `restriction` | — | Art. 18 | — | — | Suspend processing pending dispute resolution |
| `no_auto_decision` | — | Art. 22 | CPRA ADMT | — | Opt-out of purely automated decisions |
| `grievance` | §13 | — | — | Principle 10 | India/Canada specific complaint channel |
| `nominee` | §14 | — | — | — | DPDP-specific: designate successor on death |

## Migration status (Phase 0)

**SKELETON — only the `RIGHT_CATALOGUE` constant is defined.** Each pack's
`rights.yaml` will cite this catalogue and add regulation-specific SLAs + exemptions.
Implementation of new rights (rectification, portability, objection) is a separate
task queued for Phase 2+ (per regulation).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Right:
    """Canonical identity of a data-subject right.

    A pack activates a Right by referencing its `code`; the pack then supplies
    SLA, citation, exemptions, and default reason text.
    """
    code: str
    label: str
    universal_description: str


RIGHT_CATALOGUE: tuple[Right, ...] = (
    Right("access",            "Access / know",
          "Data subject can request a copy of all personal data held about them."),
    Right("rectification",     "Correction / rectification",
          "Data subject can require correction of inaccurate or incomplete data."),
    Right("erasure",           "Deletion / erasure / right to be forgotten",
          "Data subject can require deletion of their personal data (subject to legal-hold exemptions)."),
    Right("portability",       "Portability",
          "Data subject can require export of their data in a structured, commonly-used, machine-readable format."),
    Right("objection",         "Objection / opt-out",
          "Data subject can object to processing (incl. direct marketing / sale of data)."),
    Right("restriction",       "Restriction of processing",
          "Data subject can require temporary suspension of processing during dispute."),
    Right("no_auto_decision",  "No automated decision",
          "Data subject can opt out of purely automated decisions with significant effects."),
    Right("grievance",         "Grievance / complaint",
          "Data subject can lodge a complaint with the data fiduciary / supervisory authority."),
    Right("nominee",           "Nominee designation",
          "Data subject can nominate a successor to act on their behalf post-incapacity / death."),
)


def right_by_code(code: str) -> Right | None:
    """Return the Right with this code, or None."""
    for r in RIGHT_CATALOGUE:
        if r.code == code:
            return r
    return None
