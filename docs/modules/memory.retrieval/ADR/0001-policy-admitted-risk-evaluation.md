# ADR 0001: Evaluate retrieval risk on the policy-admitted set

**Status:** accepted for the convergence candidate.

## Decision

OOD, channel coverage, contradiction and HNMF seed/settling semantics operate on candidates that survive owner/generation validation, channel capacity and the policy score floor. Final result truncation follows risk evaluation. Omitted low-score candidates remain bound in the union receipt but cannot force abstention or recurrent activation.

## Rationale

Evaluating risk over every raw union member permits a low-value or malicious candidate to remove an otherwise safe high-score result. The admitted-set rule aligns safety evidence with records eligible to affect delivery while retaining full auditability.

## Consequences

Receipt counts distinguish raw union entries, admitted HNMF candidates, selections and policy omissions. Tests must prove permutation invariance, monotonicity below the floor, capacity/count consistency and explicit admitted safety exceptions.
