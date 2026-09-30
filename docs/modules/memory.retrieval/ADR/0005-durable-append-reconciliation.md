# ADR 0005: Exact durable lifecycle append reconciliation

- Status: Accepted for the repository-contained source contract
- Date: 2026-09-30
- Scope: `memory.retrieval` lifecycle persistence

## Context

A durable append port can fail before mutation, fail after the durable record is committed but before acknowledgement reaches the caller, or report success while a different object is current. Treating every port error as retry-safe permits a blind second mutation. Trusting only a returned frontier permits a port implementation to acknowledge the wrong record.

The vector publication boundary already resolves this ambiguity by reloading the exact tenant object after a mutating attempt. Retrieval lifecycle persistence requires the same property for the full execution identity.

## Decision

`append_durable_decision_checked_v1` uses the selected `DurableDecisionPortV1` as the only durable owner and applies these rules:

1. Load the latest record for the exact execution identity before mutation.
2. Accept an exact already-committed record as an idempotent replay without a second write.
3. Validate the global frontier, execution identity, writer fence, phase transition, and typed quarantine evidence before mutation.
4. After a mutating error, reload the exact execution identity. Return success only when the exact candidate record is present.
5. When a mutating error cannot be reconciled to the exact record, return `CommitOutcomeUnknown`; callers must not blindly retry.
6. After a nominally successful append, require both the exact returned frontier and an exact typed-record readback.
7. Report a successful-port/wrong-record condition as `CommittedRecordMismatch`.

The error surface records only frontier and phase metadata for a conflicting observation; it does not render tenant, principal, query, payload, or other execution identity content.

## Required tests

The external crate API tests cover:

- acknowledgement loss after an exact durable commit, with no second write;
- mutating failure without exact readback, producing typed unknown outcome;
- successful append followed by confirmation-read failure;
- successful port return with a different committed record;
- existing exact replay, quarantine, fencing, frontier, and terminal-state invariants.

## Consequences

The source contract closes the repository-level blind-retry gap and makes lifecycle append semantics consistent with durable vector publication. It does not select or deploy a production lifecycle backend, establish real-process crash recovery, provide immutable external evidence, or promote production, activation, canary, acceptance, or release claims. Those gates remain external and false until evidence for the frozen exact source is supplied.
