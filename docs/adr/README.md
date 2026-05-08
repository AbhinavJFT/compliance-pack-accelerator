# Architecture Decision Records (ADRs)

This directory holds the **why** behind significant architectural choices in
this repository — decisions that shape how the system behaves, how packs
extend it, and how customers deploy it.

If you're contributing code that touches the rule engine, the data model,
the pack contract, or anything cross-cutting, **read the relevant ADR first**.
ADRs are the single source of truth when code and docs disagree.

## Index

| #     | Title                                                                                  | Status     | Date       |
|-------|----------------------------------------------------------------------------------------|------------|------------|
| 0001  | [Multi-jurisdiction data-subject routing](0001-multi-jurisdiction-data-subject-routing.md) | Accepted   | 2026-05-08 |

## What goes in an ADR

An ADR documents a decision that:
- Has more than one defensible answer
- Will be hard to reverse later (schema, public APIs, pack contract, customer-facing behavior)
- A reasonable contributor might re-litigate without context

What does **not** go in an ADR:
- Implementation details that change frequently (which library, which file path)
- Things that would be obvious from reading the code
- Things that are documented elsewhere (`docs/architecture.html` for the diagram, `regulations/README.md` for the pack contract, individual `pack.yaml` files for per-regulation choices)

If you're not sure whether a decision rises to ADR-level: write it as a code
comment first. If the same context shows up in two more places, promote it.

## Template

Copy `template.md` (below) when starting a new ADR. Number sequentially
(`NNNN-kebab-case-title.md`).

```markdown
# ADR-NNNN — Short imperative title

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
**Date:** YYYY-MM-DD
**Implementation:** Pending | In progress | Complete (commit <sha>)

## Context

What forces are at play. What problem are we solving, what constraints
matter, and why does it need a decision now rather than later. 3–6
paragraphs is usually right; longer if there's a real prior history.

## Decision

The choice we made. Stated in the imperative. One paragraph or a short
list. This is the section future-you will read when re-litigating; keep
it crisp.

## Consequences

### Positive
- What this enables
- What gets simpler

### Negative
- What gets harder
- What we're committing to maintain

### Neutral
- Things that change but aren't a clear win or loss

## Alternatives considered

For each alternative: 1–2 sentences on what it was, and why we didn't
pick it. Not exhaustive; only the ones that were genuinely on the table.

## Edge cases

Categorised list of edge cases that *should* fall out of the decision
naturally, with the resolution we've chosen (or "deferred to Phase X"
for ones we explicitly punt on). This is the section that pays off
forever — when an unusual case hits prod, this is where we look first.

## Open questions

Things we don't have an answer for yet, but want to revisit. Each
question should have an owner and a "by when" — a question with no
owner becomes someone else's surprise.

## References

External RFCs / regulations / papers / vendor docs we drew on.
```

## Status meanings

- **Proposed** — written, under discussion, not yet implemented or sometimes not yet agreed
- **Accepted** — agreed and either implemented or actively being implemented; the decision binds future work
- **Deprecated** — the decision used to apply but doesn't anymore; left in place for archeology
- **Superseded by ADR-NNNN** — replaced by a later ADR that revisited the same question. Both stay in the index; the new one links back

When an ADR is superseded, do NOT delete the original. Update its status
header to point at the replacement and leave its body intact. Future readers
need to understand both why we used to do X and why we now do Y.
