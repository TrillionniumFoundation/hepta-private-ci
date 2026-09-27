# ADR 0004: protected rollout identity and bounded non-delivery evaluation

- Status: accepted for source candidate
- Date: 2026-09-27
- Scope: `memory.retrieval` delivery composition
- Production activation: not granted

## Context

The first four-mode source path used a fixed approximately five-percent owner hash for canary delivery. It did not provide a protected configurable rollout owner. Shadow and non-delivering canary requests could execute any structurally valid product-size HNMF context, so optional evidence work had no separately declared structural ceiling. Moving those controls into request data would let the treated process select its own arm or consume unapproved resources.

## Decision

1. Preserve bootstrap v1 and its historical cohort algorithm exactly.
2. Add bootstrap v2 with one complete, descriptor-pinned rollout policy: ppm threshold, nonzero cohort salt and four bounded shadow ceilings.
3. Reject partial v2 policies and reject v2 fields under v1.
4. Capture the policy once from trusted host composition; requests cannot mutate it.
5. Bind policy version, threshold, salt and budgets into every routed lifecycle digest.
6. Treat shadow and canary owners outside the delivery cohort as non-exposure. Validate structural budgets before optional HNMF work; budget failure skips that work and preserves compatibility delivery.
7. Keep canary/required invalid policy paths fail closed.

## Consequences

A rollout change is now an explicit descriptor/pin/process-generation transition and invalidates old final-use bindings. The v1 cohort is not silently reshuffled. A v2 salt can intentionally create a new cohort; continuity requires an explicit operator decision.

Structural ceilings reduce accidental shadow amplification, but do not isolate CPU, memory, allocations or wall time. No deployment, SLO, calibration, independent administration or release claim follows from this ADR. Those gates remain in the implementation map and rollout documentation.
