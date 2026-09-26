# learning.eval recovery and reconciliation contract

This file is normative for repository-controlled recovery behavior. It extends
`PRODUCTION_CONTRACT.md`; it does not grant selection, activation, promotion or
release authority. Every receipt described here remains `DENY_ALL`.

## 1. Canonical product composition

A host that releases a final holdout must compose
`ProductEvaluationRunnerV1` through `AuditedProductEvaluationRunnerV1`. The
latter binds one immutable plan to one attempt ID and records every boundary
transition through `EvaluationAttemptJournalV1` before reporting success or
failure to the caller.

The repository-consumer facade `admit_repository_evaluation_v1` is different. It
allows Agentd and plasticity to consume independently signed eligibility in a
consumer-bound, sealed receipt, but it does not release a final holdout or issue
a `ProductQualificationReceiptV1`. Raw V2/V3 decision functions are
crate-private.

## 2. Attempt identity and terminal states

A plan digest is owned by exactly one attempt ID. It cannot be rebound to a new
attempt ID. Before the final holdout advances, an identical `Started` call is
idempotent. After advancement or an accepted-or-unknown store result, automatic
re-execution is forbidden.

The durable phases are:

- `Started`: plan and pre-holdout state are fixed;
- `RejectedBeforeHoldout`: no holdout state change was observed;
- `HoldoutConsumedWithoutTerminalReceipt`: the state advanced but provider,
  validation or estimation failed before a temporal receipt was produced;
- `HoldoutConsumptionIndeterminate`: the holdout CAS may have committed and the
  owner must be reloaded and reconciled;
- `TemporalEvaluated`: one sealed temporal execution receipt exists;
- `QualificationRejected`: signed qualification or a determinate publication
  operation rejected;
- `PublicationIndeterminate`: the evidence write may have committed;
- `Published`: the durable publication digest has been reconciled and recorded.

`HoldoutConsumedWithoutTerminalReceipt`,
`HoldoutConsumptionIndeterminate`, `QualificationRejected`,
`PublicationIndeterminate` and `Published` are retry-forbidden. The only allowed
transition out of `PublicationIndeterminate` is a read-based reconciliation to
`Published`.

## 3. Attempt-store semantics

`EvaluationAttemptCasStoreV1` is authoritative for one binding. It must provide
linearizable load and compare-and-swap across every participating process or
host. Reusing an expected digest after another writer advances must conflict.
An accepted-or-unknown write must return `Indeterminate`; the journal poisons
that handle until recovery.

The current source supplies the state machine and fault-injection fixtures. A
named target host must supply and qualify the durable CAS implementation and its
namespace authentication. An in-memory fixture is never product evidence.

## 4. Idempotent evidence publication

A target evidence owner implements
`IdempotentQualificationEvidenceSinkV1`:

1. `execution_digest` is the idempotency key;
2. `decision_digest` binds the exact signed decision, trust state and
   authentication evidence;
3. an exact committed retry returns the existing publication record without a
   second write;
4. key reuse with different semantics returns `Conflict`;
5. an accepted-or-unknown write returns `Indeterminate`;
6. reconciliation calls `lookup(execution_digest)` and succeeds only when the
   returned execution and decision digests match and the publication digest is
   nonzero.

`ReconcilingQualificationEvidenceSinkV1` implements this algorithm for the
product runner. A missing record after an indeterminate write remains
indeterminate; it must not be silently retried as a fresh publication.

## 5. Final-holdout checkpoint and compaction

`LockedCheckpointFinalHoldoutCasStoreV1` is a concrete, single-filesystem
checkpoint backend. Each append-only frame contains a complete validated CAS
record. It provides:

- lifetime OS-file exclusion;
- bounded frame, file, checkpoint and holdout-record counts;
- frame checksums and semantic record reconstruction;
- monotonic fence or one-record journal transitions;
- accepted-or-unknown poisoning;
- truncated uncommitted-tail removal;
- independently retained minimum-anchor rollback rejection;
- compaction into a fresh file containing one current checkpoint;
- a sealed `FinalHoldoutCompactionReceiptV1` and storage metrics.

The host must install the compacted file and independently retained anchor as one
operational transaction before retiring the predecessor. Directory durability,
file ownership, backup retention and shared-filesystem semantics remain host
responsibilities. Cross-host use requires qualified linearizable locking and
fsync behavior.

## 6. Required fault injection

Repository qualification must exercise at least:

- stale attempt writers and stale final-holdout writers;
- commit-before-error for attempt state and evidence publication;
- evidence publication without a committed reconciliation record;
- post-holdout provider or estimator failure;
- truncated checkpoint tail;
- checksum/corruption rejection;
- retained-anchor rollback rejection;
- compaction state identity;
- maximum configured checkpoint recovery and disk-budget reporting;
- external compile failure for raw V2/V3 decision imports.

Repeated execution of the same happy-path test is stability evidence, not fault
injection evidence.

## 7. Qualification and external gates

Exact-head and ordered-parent synthetic-merge CI must retain commit-addressed
coverage, compile-fail, fault-injection, capacity and status-verification
artifacts. Source CI cannot self-issue target-host authentication, live outcome
provenance, real future-calendar windows, retention/privacy/unlearning evidence,
independent semantic acceptance, canary, selection, promotion or release.
Those gates remain false until the evidence listed in
`docs/modules/learning.eval/TARGET_HOST_ACCEPTANCE.md` is supplied by the named
owners.
