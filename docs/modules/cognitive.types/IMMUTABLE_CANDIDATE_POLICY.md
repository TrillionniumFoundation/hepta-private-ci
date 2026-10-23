# Cognitive Types Immutable Candidate Policy

This branch is developed through ordinary reviewable commits. Qualification,
source export, fuzzing, mutation, and evidence workflows are read-only and may
not create commits, move refs, or push source changes.

## Candidate identity

Every qualification claim is bound to one exact source commit and tree. A
synthetic merge is recorded separately with its ordered parents and must never
replace exact-head evidence. A later source commit invalidates earlier runtime,
resource, fuzz, and consumer-entrypoint receipts for qualification purposes.

## Request-scoped derived state

Canonical bytes and digest profiles may be retained only inside a value derived
from one currently validated payload. Such a value:

- contains no owner-currentness, authorization, revocation, activation, or
  release conclusion;
- is not stored in a process-global or cross-request mutable cache;
- is not reused across source snapshots or owner epochs;
- exposes the exact canonical bytes from which both digest profiles were
  computed; and
- must still be combined with a fresh observation from the real product owner
  immediately before a final use.

## Identity policy

Wire V1 preserves the caller's Unicode scalar sequence. Owners of identifiers
with semantic uniqueness must therefore choose and enforce one explicit policy
before constructing a contract value: the repository `StableId` grammar,
owner-owned normalization with a named profile, or rejection of confusable and
normalization-variant spellings. The generic codec does not silently normalize
text and does not turn byte identity into logical identity.

## Product boundary

`Validated<T>`, canonical encoding, digest equality, a consumer binding, or a
handoff receipt grants no read, write, model, provider, tool, external-effect,
promotion, activation, or release authority. Each product consumer must acquire
its own fresh owner observation and cross the final-use boundary within that
owner's synchronization scope.

## Evidence discipline

Fuzz campaigns are separated by protocol family and record the exact source
commit/tree, target, corpus digest, run duration, executions, peak RSS, coverage
summary, crash inventory, and toolchain. Empty, skipped, cancelled, timed-out,
truncated, dirty-tree, or resealed evidence is not success.
