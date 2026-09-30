# memory.retrieval recovery and transactional outbox contract

## Status and claim boundary

This document specifies repository-contained recovery semantics for the existing
`memory.retrieval` product path. It does not introduce a second runtime, a second
learning ledger, or a second native-operation owner. It does not establish a
production encoder, durable vector backend, selected-host qualification,
independent acceptance, activation, or release.

The durable sources remain:

1. the learning ledger's tag-10 `RetrievalPrepared` event, which proves an
   unexposed assignment preparation; and
2. the infer-core native journal, which owns reservation, write-ahead dispatch,
   typed rejection, exact turn identity, and terminal observation.

`codex-hepta-agentd::retrieval_delivery` verifies the join and projects it onto
the canonical lifecycle contract exported by `codex-hepta-memory-retrieval`.
The projection is an append payload for the existing `DurableDecisionPortV1`;
it is not an independently authoritative store.

## Monotonic evidence states

| Delivery evidence | Canonical lifecycle phase | Permitted action |
|---|---|---|
| tag-10 preparation, no durable native dispatch | `QualifiedDecision` | A new effect may be admitted only after all current fences pass. |
| durable dispatch, no typed response or turn | `QuarantinedUnknownOutcome` | Query the exact native operation. Do not create or replay an effect. |
| typed App Server response before a turn | `PublishedRetrieval` | Retain the response as publication evidence; no native start is implied. |
| exact native turn identity | `ConsumedRetrieval` | Reconcile the named turn; never substitute another request. |
| matching terminal observation | `AcknowledgedRetrieval` | Admit outcome/learning only after current final-use checks. |
| terminal status `Indeterminate` | `QuarantinedUnknownOutcome` | Reconcile the exact operation and withhold outcome/learning. |

A write-ahead dispatch is deliberately not publication evidence. It is also not
"not started" evidence. The `DispatchOutcomeUnknown` state closes that ambiguity:
a process that crashes after committing dispatch cannot restart and issue a
second physical effect merely because no response was observed locally.

## Transactional append rule

`project_retrieval_delivery_lifecycle_v1` binds the verified receipt to the
canonical execution identity:

- principal equals the native principal;
- request equals the exact native request ID;
- decision identity equals the durable retrieval-assignment record ID;
- writer fence and expected frontier are caller-owned durable values; and
- payload identity is the immutable retrieval-delivery receipt digest.

`append_retrieval_lifecycle_projection_v1` performs exactly one existing-port
operation:

- ordinary phases use `compare_and_append`; and
- unknown outcomes use `quarantine_unknown_outcome`.

The helper never renews a fence or frontier. A stale process therefore cannot
recover ownership by retrying the append. Idempotency, compare-and-swap,
retention, replay verification, and physical persistence remain obligations of
the already selected `DurableDecisionPortV1` implementation.

## Crash and late-result matrix

The machine-readable authority for the required cases is
`qualification/memory-retrieval/recovery-matrix.json`.

The minimum required behavior is:

- crash before preparation append: no retrieval lifecycle fact exists and no
  effect is assumed;
- crash after preparation, before native dispatch: recover the same preparation
  and rerun current fences before any new effect;
- crash after durable dispatch, before response: quarantine and reconcile the
  exact request; blind retry is forbidden;
- crash after typed response, before native turn: preserve publication evidence
  without claiming native execution;
- crash after native turn, before terminal observation: reconcile the exact turn;
- crash after terminal observation, before lifecycle append: recompute the same
  digest and append idempotently;
- acknowledgement loss after append: replay of the same immutable fact is
  idempotent; a different payload under the same identity is a conflict;
- late success after request deadline/cancellation: it may settle durable truth,
  but it must not be returned, learned from, cached, or republished without a
  fresh current-use decision;
- generation, capability, withdrawal, or revocation advancement: old durable
  truth is retained, while current use fails closed.

## Resource and owner isolation

The existing Agentd retrieval executor continues to own bounded semaphores,
`spawn_blocking` isolation, absolute deadlines, cooperative work control, and
worker-exit observation. Timeout does not release an execution permit while the
underlying worker is still alive. SQLite, vector/index, file, or network owners
must additionally provide a real interrupt or remain isolated until physical
exit; cancellation of the waiting future is not proof that owner work stopped.

## Qualification requirements

Repository qualification must bind the exact source SHA and tree, deterministic
base merge, current-main comparison, Cargo lock, workflow definitions, native
package tests, all-target strict Clippy, formatting, clean source, Agentd process
qualification, source integrity, and the generated qualification manifest.
After integration, the merge SHA must run independently; branch-head artifacts
cannot be relabelled as merge evidence.

External gates remain false until separately observed evidence exists for a
production encoder and vector publisher, selected deployment host, hard resource
isolation, real-process kill points, immutable/WORM evidence retention,
independent signature, canary and rollback rehearsal, and formal release
approval.
