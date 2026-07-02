"""Pack-aware Genie text_instructions composer (ADR-0001 M3 + Option 3).

When multiple regulation packs are loaded, every persona's Genie space needs
to learn how to qualify answers by jurisdiction — a CMO asking "can I email
this customer?" must check the principal's jurisdiction, route to the right
pack's consent rule, and answer correctly. Hand-editing each persona's
text_instructions every time a pack is added scales badly.

This module composes the final `text_instructions` block from three layers:

  1. **Static base** — the persona's hand-authored guidance (regulator-agnostic
     voice, persona role, refusal patterns, style instructions). May contain
     ``{{pack_scope}}`` / ``{{pack_names}}`` / ``{{pack_short_names}}``
     placeholders that get filled in based on loaded packs.

  2. **Per-pack contributions** — each loaded pack contributes a
     ``persona_guidance.yaml`` whose persona-keyed sections (cco / gc / cmo /
     cfo) are merged in. This is where pack-specific section mappings,
     penalty models, and example questions live.

  3. **Auto-generated routing footer** — a "Loaded regulation packs" block
     enumerating every pack in regulations/ with jurisdiction, supervising
     authority, and citation style.

Override: a persona YAML can set ``auto_compose: false`` to skip layers 2-3
entirely (the hand-authored text_instructions is used verbatim). This is the
"hand-authored override" path ADR-0001 reserves for deployments where the
persona's guidance is genuinely pack-agnostic.

Used by `scripts/configure_persona_genie_instructions.py` at deploy time.
"""

from __future__ import annotations

from .pack_loader import Pack, loaded_packs


_MULTI_PACK_HEADER = """
**Multi-jurisdiction routing (loaded automatically — do not edit this block)**

This Genie space operates across multiple regulation packs simultaneously.
Each data subject (customer, user, patient, employee) carries a
`jurisdiction` column on their silver-table row that routes rule
evaluation to the pack governing them. When answering questions:

- For any question about a specific principal, qualify the answer with
  their jurisdiction. GB principals are governed by UK GDPR; EU/EEA
  principals by EU GDPR. Retention windows, consent semantics, lawful
  basis, and DSR SLAs differ between packs.
- For aggregate questions ("how many compliance gaps do we have?"),
  default to a per-jurisdiction breakdown unless the user explicitly
  asks for a union number.
- Cite the specific article / section the answer rests on. Use the
  pack's citation style — see the per-pack list below.
- If a principal's jurisdiction is NULL or unmapped, flag it as a
  compliance gap rather than guessing.
"""


_SINGLE_PACK_HEADER = """
**Active regulation pack: {pack_name}**

This Genie space is currently operating under a single regulation pack
({pack_code}, jurisdiction {jurisdiction}). All answers should cite
{citation_style} where applicable; the supervising authority is
{authority}.
"""


def _format_pack_summary(pack: Pack) -> str:
    """One-line description of a loaded pack."""
    cite_style = ""
    try:
        cite_style = pack.dpia_template().section_citation_style
    except Exception:  # noqa: BLE001 — pack may not have a DPIA template
        cite_style = f"{pack.code} citations"

    return (
        f"  - **{pack.metadata.get('name', pack.code)}** "
        f"(`{pack.code}`, jurisdiction `{pack.jurisdiction or '?'}`). "
        f"Supervising authority: {pack.metadata.get('supervising_authority', 'unknown')}. "
        f"Citation style: {cite_style}."
    )


# ---------------------------------------------------------------------------
# Template-variable substitution
# ---------------------------------------------------------------------------

def _pack_short_name(pack: Pack) -> str:
    """Use pack's authored short_name (e.g. 'UK GDPR') with fallback to pack.code."""
    guidance = pack.persona_guidance() or {}
    return guidance.get("short_name") or pack.code


def _compute_template_vars(packs: list[Pack]) -> dict[str, str]:
    """Return template variables for substitution in persona base text.

    Available variables (use ``{{name}}`` in YAML):

      pack_scope        : adjective for the persona's role ("UK GDPR" or
                          "multi-jurisdiction"). Used in "You are the X
                          compliance assistant".
      pack_names        : comma-separated full names of loaded packs
                          ("UK GDPR, EU GDPR").
      pack_short_names  : comma-separated short names ("UK GDPR,
                          EU GDPR"). Use in scope/refusal text.
      pack_count        : "1" or "2" — string form for direct interpolation.
    """
    if not packs:
        return {
            "pack_scope": "compliance",
            "pack_names": "(no regulation packs loaded)",
            "pack_short_names": "(none)",
            "pack_count": "0",
        }
    if len(packs) == 1:
        p = packs[0]
        return {
            "pack_scope": _pack_short_name(p),
            "pack_names": p.metadata.get("name", p.code),
            "pack_short_names": _pack_short_name(p),
            "pack_count": "1",
        }
    short_names = [_pack_short_name(p) for p in packs]
    full_names = [p.metadata.get("name", p.code) for p in packs]
    return {
        "pack_scope": "multi-jurisdiction",
        "pack_names": ", ".join(full_names),
        "pack_short_names": ", ".join(short_names),
        "pack_count": str(len(packs)),
    }


def _substitute(text: str, variables: dict[str, str]) -> str:
    """Replace ``{{var}}`` placeholders in text. Missing keys are left as-is
    so a typo doesn't blow up the prompt — the literal placeholder will
    appear in the agent's instructions, surfacing the bug loudly."""
    out = text
    for k, v in variables.items():
        out = out.replace("{{" + k + "}}", str(v))
        out = out.replace("{{ " + k + " }}", str(v))  # tolerate spaced form
    return out


# ---------------------------------------------------------------------------
# Per-pack persona-guidance merge
# ---------------------------------------------------------------------------

def _format_per_pack_block(persona: str, packs: list[Pack]) -> str:
    """Build the per-pack guidance section for a given persona.

    Walks every loaded pack's ``persona_guidance.yaml``, picks the section
    keyed by ``persona`` (cco/gc/cmo/cfo), and composes a block that includes:
      - Glossary entries from every pack
      - Per-pack scope notes
      - Per-pack rule_section_mapping (GC primarily)
      - Per-pack penalty_model (CFO primarily)
      - Per-pack example questions (added as agent suggestions)

    Returns '' if no pack contributed anything for this persona.
    """
    if not persona:
        return ""

    glossary_entries: list[str] = []
    scope_notes: list[tuple[str, str]] = []     # (short_name, scope_note)
    section_mappings: list[tuple[str, dict]] = []  # (short_name, mapping)
    penalty_models: list[tuple[str, str]] = []  # (short_name, penalty_model)
    example_questions: list[tuple[str, list]] = []  # (short_name, [questions])

    for p in packs:
        guidance = p.persona_guidance() or {}
        if not guidance:
            continue
        short = guidance.get("short_name") or p.code

        glossary = guidance.get("glossary_entry")
        if glossary:
            glossary_entries.append(glossary.strip())

        persona_section = guidance.get(persona) or {}
        if not isinstance(persona_section, dict):
            continue

        if persona_section.get("scope_note"):
            scope_notes.append((short, persona_section["scope_note"].strip()))
        if persona_section.get("rule_section_mapping"):
            section_mappings.append((short, persona_section["rule_section_mapping"]))
        if persona_section.get("penalty_model"):
            penalty_models.append((short, persona_section["penalty_model"].strip()))
        if persona_section.get("example_questions"):
            example_questions.append((short, persona_section["example_questions"]))

    if not any([glossary_entries, scope_notes, section_mappings,
                penalty_models, example_questions]):
        return ""

    parts: list[str] = []

    parts.append(
        "\n**Pack-contributed guidance (loaded automatically — do not edit this block)**\n"
    )

    if glossary_entries:
        parts.append("**Glossary:**")
        for g in glossary_entries:
            parts.append(g)
        parts.append("")

    if scope_notes:
        parts.append("**Scope from loaded packs:**")
        for short, note in scope_notes:
            parts.append(f"- *{short}*: {note}")
        parts.append("")

    if section_mappings:
        parts.append("**Rule-ID → regulation-section mapping (use these citations):**")
        for short, mapping in section_mappings:
            parts.append(f"- *{short}*:")
            for rule_id, section in mapping.items():
                parts.append(f"    {rule_id} → {short} {section}")
        parts.append("")

    if penalty_models:
        parts.append("**Penalty models from loaded packs:**")
        for short, model in penalty_models:
            parts.append(f"*{short}:*")
            parts.append(model)
            parts.append("")

    if example_questions:
        parts.append("**Example questions you can confidently answer:**")
        for short, qs in example_questions:
            for q in qs:
                parts.append(f'- ({short}) "{q}"')
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compose(base_text: str, packs: list[Pack] | None = None,
            persona: str | None = None) -> str:
    """Return text_instructions with template substitution + pack-aware blocks.

    Composition order:
      1. Substitute ``{{pack_scope}}`` / ``{{pack_names}}`` / ``{{pack_short_names}}``
         / ``{{pack_count}}`` in the base text.
      2. Append per-pack persona guidance (glossary + scope notes + rule
         section mappings + penalty models + example questions). Skipped if
         ``persona`` is None.
      3. Append the routing footer (single-pack header or multi-pack block
         + per-pack enumeration).

    ``base_text`` is the persona's hand-authored guidance. ``packs`` defaults
    to ``loaded_packs()`` if not supplied. ``persona`` is the persona key
    (cco/gc/cmo/cfo) used to pick per-pack persona-specific snippets.
    """
    if packs is None:
        packs = loaded_packs()

    if not packs:
        # No packs loaded — degenerate case. Return the base text unchanged
        # (after template substitution with zero-pack fallback values) so
        # deployers don't get a misleading "all packs disabled" block.
        return _substitute(base_text, _compute_template_vars(packs))

    # Layer 1: template substitution on hand-authored base text.
    out_parts: list[str] = [
        _substitute(base_text, _compute_template_vars(packs)).rstrip()
    ]

    # Layer 2: per-pack persona-guidance contributions.
    if persona:
        per_pack = _format_per_pack_block(persona, packs)
        if per_pack:
            out_parts.append(per_pack.rstrip())

    # Layer 3: routing footer (auto-appended).
    if len(packs) == 1:
        p = packs[0]
        cite_style = ""
        try:
            cite_style = p.dpia_template().section_citation_style
        except Exception:  # noqa: BLE001
            cite_style = f"{p.code} citations"
        out_parts.append(_SINGLE_PACK_HEADER.format(
            pack_name=p.metadata.get("name", p.code),
            pack_code=p.code,
            jurisdiction=p.jurisdiction or "?",
            citation_style=cite_style,
            authority=p.metadata.get("supervising_authority", "unknown"),
        ).rstrip())
    else:
        out_parts.append(_MULTI_PACK_HEADER.rstrip())
        out_parts.append("\n**Loaded regulation packs:**")
        for p in packs:
            out_parts.append(_format_pack_summary(p))

    return "\n\n".join(out_parts) + "\n"


def compose_for_persona(persona_cfg: dict, packs: list[Pack] | None = None) -> str:
    """Return composed text_instructions for a persona config dict.

    Reads ``persona`` from the config (e.g. 'cco') so per-pack persona-specific
    guidance can be merged in. Honours the ``auto_compose`` flag — if set to
    ``False``, the base text is returned unchanged (hand-authored override).
    """
    base = persona_cfg.get("text_instructions", "") or ""
    if persona_cfg.get("auto_compose") is False:
        return base
    persona = persona_cfg.get("persona")
    return compose(base, packs=packs, persona=persona)
