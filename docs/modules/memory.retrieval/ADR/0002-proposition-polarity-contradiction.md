# ADR 0002: Bind contradiction evidence to proposition and polarity

**Status:** accepted for the convergence candidate.

## Decision

Contradiction evidence contains a nonzero proposition digest and an explicit `Supports` or `Opposes` polarity. Conflict requires both polarities for the same scoped proposition/generation. Multiple records on one side are corroboration. Active graph contradiction edges are additional conflict evidence only when both endpoints are admitted, positively active and the edge weight is positive.

## Rationale

A single observation-wide group digest loses proposition identity and polarity, causing two same-side contradiction-support records to trigger false abstention. Typed evidence makes the safety claim reviewable and testable.

## Consequences

Wire/persistent consumers must migrate deliberately if the type becomes external. The current surface is repository-internal source candidate. Owner adapters bind the proposition to the exact request or a typed KG proposition; generic graph relations cannot be relabelled.
