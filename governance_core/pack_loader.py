"""Regulation pack loader — reads active pack at bootstrap, exposes typed accessors.

The pack loader is the single entry point for regulation-specific values. Pipelines
and scripts import from this module rather than from individual pack files, so the
active pack is switchable via a single env var without code changes elsewhere.

## Usage

    from governance_core.pack_loader import active_pack

    pack = active_pack()
    for rule in pack.rules():
        spark.sql(f"INSERT ... VALUES ({rule['rule_id']}, ...)")

    retention_days = pack.retention_default(purpose="marketing_email")
    allowed = pack.residency_allowed_countries()
    langs = pack.languages()

## Activation

    export REGULATION_PACK=dpdp_2023    # default — current POC behavior
    export REGULATION_PACK=uk_gdpr      # Phase 1 target
    export REGULATION_PACK=ccpa

Pack directories live under `regulations/<code>/`.

## Status

**Phase 0.2:** yaml loader is live; consumed first by the compliance-rules migration
in `pipelines/phase1_bootstrap.py`. Additional accessors (notice templates, residency
SQL rendering, pattern-pack composition) wire in as each migration step lands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as _e:  # noqa: F841
    yaml = None  # Loader surfaces a clearer error below


class PackLoaderError(RuntimeError):
    """Raised when the active pack is missing, malformed, or incomplete."""


DEFAULT_PACK_CODE = "dpdp_2023"
REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_ROOT = REPO_ROOT / "regulations"


def active_pack_code() -> str:
    """Return the active regulation pack code. Defaults to DPDP-2023 (current POC)."""
    return os.environ.get("REGULATION_PACK") or DEFAULT_PACK_CODE


def active_pack_dir() -> Path:
    """Path to the active pack's directory. Raises if it doesn't exist."""
    code = active_pack_code()
    path = PACKS_ROOT / code
    if not path.exists():
        available = [p.name for p in PACKS_ROOT.iterdir() if p.is_dir()] if PACKS_ROOT.exists() else []
        raise PackLoaderError(
            f"Regulation pack '{code}' not found at {path}. Available: {available}"
        )
    return path


def _require_yaml() -> None:
    if yaml is None:
        raise PackLoaderError(
            "PyYAML is required to load regulation packs. Install: pip install pyyaml"
        )


def _read_yaml(path: Path) -> Any:
    _require_yaml()
    if not path.exists():
        raise PackLoaderError(f"Pack file not found: {path}")
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class DPIATemplate:
    """Typed wrapper around a pack's dpia_template.yaml.

    The 8 DPIA section *keys* are regulation-agnostic and defined by
    governance_core/dpia.py::DPIASections. This template controls the
    regulation-specific framing: which legal framework the model is
    told it's drafting under, the citation style for section
    references, the system prompt, and any per-section description
    overrides that get merged into the JSON schema fed to the LLM.
    """
    legal_framework_name: str
    section_citation_style: str
    system_prompt: str
    section_descriptions: dict = field(default_factory=dict)


@dataclass
class Pack:
    """Typed wrapper around a loaded regulation pack. Instantiate via load()."""
    code: str
    path: Path
    metadata: dict = field(default_factory=dict)
    _rules: list | None = field(default=None, repr=False)
    _rights: list | None = field(default=None, repr=False)
    _retention: dict | None = field(default=None, repr=False)
    _residency: dict | None = field(default=None, repr=False)
    _languages: list | None = field(default=None, repr=False)
    _breach_sla: dict | None = field(default=None, repr=False)
    _dpia_template: "DPIATemplate | None" = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.metadata.get("name", self.code)

    @property
    def jurisdiction(self) -> str:
        return self.metadata.get("jurisdiction", "")

    @property
    def primary_locale(self) -> str:
        return self.metadata.get("primary_locale", "en-IN")

    def rules(self) -> list[dict]:
        """Return compliance rules as a list of dicts."""
        if self._rules is None:
            data = _read_yaml(self.path / "rules.yaml")
            self._rules = data.get("rules") or []
        return self._rules

    def rights(self) -> list[dict]:
        """Return activated data-subject rights from rights.yaml."""
        if self._rights is None:
            data = _read_yaml(self.path / "rights.yaml")
            self._rights = data.get("rights") or []
        return self._rights

    def retention_default(self, purpose: str) -> int:
        """Return retention days for a purpose; falls back to 730 if unset."""
        if self._retention is None:
            data = _read_yaml(self.path / "retention_defaults.yaml")
            self._retention = data.get("defaults") or {}
        val = self._retention.get(purpose)
        return int(val) if val is not None else 730

    def residency_allowed_countries(self) -> list[str]:
        """Countries whose rows non-admins may see."""
        if self._residency is None:
            self._residency = _read_yaml(self.path / "residency.yaml") or {}
        return list(self._residency.get("allowed_countries") or [])

    def residency_apply_targets(self) -> list[dict]:
        """[{table, column}] pairs where the residency filter should apply."""
        if self._residency is None:
            self._residency = _read_yaml(self.path / "residency.yaml") or {}
        return list(self._residency.get("apply_filter_to") or [])

    def languages(self) -> list[dict]:
        """Pack's language registry — one entry per locale."""
        if self._languages is None:
            data = _read_yaml(self.path / "languages.yaml")
            self._languages = data.get("languages") or []
        return self._languages

    def seeded_languages(self) -> list[dict]:
        """Languages with seeded_by_poc=true (hand-authored notice bodies)."""
        return [l for l in self.languages() if l.get("seeded_by_poc")]

    def breach_sla(self) -> dict:
        """Breach-notification SLA config."""
        if self._breach_sla is None:
            self._breach_sla = _read_yaml(self.path / "breach_sla.yaml") or {}
        return self._breach_sla

    def pii_patterns(self) -> list:
        """Return the pack's region-specific PII patterns.

        Dynamically imports `regulations.<code>.pii_patterns` and returns its
        IN_SPECIFIC_PATTERNS list. Returns [] if the pack has no
        pii_patterns.py or an empty IN_SPECIFIC_PATTERNS (valid for packs
        that only rely on universal patterns).
        """
        from importlib import import_module
        try:
            mod = import_module(f"regulations.{self.code}.pii_patterns")
        except ImportError:
            return []
        return list(getattr(mod, "IN_SPECIFIC_PATTERNS", []))

    def notices(self) -> list[dict]:
        """Return seeded consent notices from notices.yaml.

        Each entry is a dict with columns matching compliance.notice_versions.
        datetime strings are returned as ISO 8601; callers parse them with
        datetime.fromisoformat() when loading into Spark.
        """
        data = _read_yaml(self.path / "notices.yaml")
        return data.get("notices") or []

    def dpia_template(self) -> DPIATemplate:
        """Return the pack's DPIA prompt template (governance_core/dpia.py).

        Loaded lazily on first access. Required keys: legal_framework_name,
        section_citation_style, system_prompt. section_descriptions is
        optional and defaults to {}.
        """
        if self._dpia_template is None:
            path = self.path / "dpia_template.yaml"
            if not path.exists():
                raise PackLoaderError(
                    f"Pack '{self.code}' is missing dpia_template.yaml at {path}. "
                    f"Required for the DPIA Auto-Generator (Agent 1) — see "
                    f"regulations/README.md for the contract."
                )
            data = _read_yaml(path)
            for required in ("legal_framework_name", "section_citation_style", "system_prompt"):
                if not data.get(required):
                    raise PackLoaderError(
                        f"Pack '{self.code}' dpia_template.yaml is missing "
                        f"required key '{required}'."
                    )
            self._dpia_template = DPIATemplate(
                legal_framework_name=data["legal_framework_name"],
                section_citation_style=data["section_citation_style"],
                system_prompt=data["system_prompt"],
                section_descriptions=data.get("section_descriptions") or {},
            )
        return self._dpia_template

    def default_purposes(self) -> list[str]:
        """Return the list of consent purposes the pack's notices cover.

        Used by phase1_bootstrap's consent-event generator so purposes stay
        consistent between notice templates and generated events.
        """
        data = _read_yaml(self.path / "notices.yaml")
        purposes = data.get("default_purposes")
        if purposes:
            return list(purposes)
        # Fallback: derive from the first notice's purposes_covered
        notices = data.get("notices") or []
        if notices and "purposes_covered" in notices[0]:
            return list(notices[0]["purposes_covered"])
        return []


_cache: dict[str, Pack] = {}


def load() -> Pack:
    """Load the active regulation pack and return a Pack accessor (cached)."""
    code = active_pack_code()
    if code not in _cache:
        path = active_pack_dir()
        metadata = _read_yaml(path / "pack.yaml")
        _cache[code] = Pack(code=code, path=path, metadata=metadata)
    return _cache[code]


# Convenience alias for readability.
active_pack = load
