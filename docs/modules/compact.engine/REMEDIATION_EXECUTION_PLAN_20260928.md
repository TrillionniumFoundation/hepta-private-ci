# compact.engine boundary and qualification remediation plan — 2026-09-28

This branch tracks the next convergence after the V2 checkpoint implementation. It is intentionally split from source implementation claims: this document is a delivery plan, not evidence that the listed gates have passed.

## Phase 1 — correctness closure

### Transaction and state boundary convergence

- Collapse public mutation paths around four explicit layers:
  - deterministic candidate construction and proof verification;
  - current trust/admission checks;
  - transactional durable mutation;
  - restart reconciliation.
- Remove duplicated ownership checks from wrapper layers where the same invariant can be enforced at one durable mutation boundary.
- Replace hand-managed transaction cleanup with cancellation-safe transaction ownership.
- Require every durable mutation to bind owner, root, lease, epoch and active manifest at the write boundary.

### Recovery closure

Add native regression coverage for:

- cancellation during transaction execution;
- lease replacement between reservation and commit;
- manifest rotation between validation and mutation;
- committed-response loss;
- concurrent outbox readers and writers;
- all reserved admissions after restart.

## Phase 2 — complete operation measurement

Replace estimated metrics with phase measurements:

- admission latency;
- trust verification latency;
- transaction wait and commit latency;
- artifact serialization bytes;
- payload bytes;
- archive bytes;
- database growth;
- WAL growth;
- reopen latency;
- peak RSS.

Separate design ceilings from observed measurements.

## Phase 3 — storage and payload accounting

Maintain independent limits for:

- semantic payload bytes;
- source metadata;
- receipt/proof material;
- durable archive size;
- database allocation growth.

Add boundary tests for every independently bounded resource:

- below limit;
- exact limit;
- above limit.

## Phase 4 — error contract convergence

Preserve structured failure classes through Agentd composition:

- invalid input;
- trust rejection;
- lease conflict;
- capacity rejection;
- corruption;
- outcome unknown;
- retryable reconciliation state.

Do not require callers to parse human-readable error strings.

## Acceptance requirements

Completion requires actual final-candidate evidence, including:

- exact source identity;
- deterministic merge candidate identity;
- native build/test/lint/format results;
- fault injection results;
- capacity measurements;
- recovery evidence.

Documentation, source presence and test definitions are not substitutes for executed evidence.
