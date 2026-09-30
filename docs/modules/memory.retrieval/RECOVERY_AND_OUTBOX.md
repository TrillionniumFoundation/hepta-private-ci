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

For one exact execution identity, ordinary lifecycle phases advance strictly
forward. A stronger durable observation may skip an unmaterialized intermediate
phase, for example `QualifiedDecision -> ConsumedRetrieval` when an exact native
turn already exists. `AcknowledgedRetrieval` is terminal. A quarantined unknown
outcome cannot regress to `QualifiedDecision` or another pre-effect state and
cannot be appended repeatedly as a substitute for reconciliation. Exact
operation reconciliation may advance quarantine only to `PublishedRetrieval`,
`ConsumedRetrieval`, or `AcknowledgedRetrieval`.

## Transactional append rule

`project_retrieval_delivery_lifecycle_v1` binds the verified receipt to the
canonical execution identity:

- principal equals the native principal;
- request equals the exact native request ID;
- decision identity equals the durable retrieval-assignment record ID;
- writer fence and expected frontier are caller-owned durable values; and
- payload identity is the immutable retrieval-delivery receipt digest.

Product code appends through
`append_retrieval_lifecycle_projection_checked_v1`, which delegates to
`append_durable_decision_checked_v1`. Before touching storage, the checked
boundary:

- loads the latest fact for the exact execution identity;
- requires the proposed record frontier to equal the caller's global expected
  frontier plus one;
- rejects a latest per-identity frontier that is ahead of the caller's global
  frontier;
- requires exact identity equality and a nondecreasing writer fence;
- enforces the monotonic phase and quarantine rules above;
- requires quarantine evidence exactly when the phase is
  `QuarantinedUnknownOutcome`;
- recognizes an exact already-committed record as an idempotent replay and
  returns its durable frontier without issuing a second mutating append;
- verifies that a new append reports the exact committed frontier.

An exact replay must still provide the typed quarantine evidence required by a
`QuarantinedUnknownOutcome` record. A same-identity record with different phase,
frontier, fence, or payload is not an idempotent replay and remains a conflict.

The raw `append_retrieval_lifecycle_projection_v1` helper remains a low-level
compatibility surface for existing storage implementations. It is not the
product-qualified append boundary and must not be used by new product callers.

The checked helper performs exactly one existing-port operation after validation:

- ordinary phases use `compare_and_append`; and
- unknown outcomes use `quarantine_unknown_outcome`.

The helper never renews a fence or frontier. A stale process therefore cannot
recover ownership by retrying the append. A port error is an uncertain commit
result: recovery must reload the exact identity and reconcile the immutable
payload before another append. Idempotency, compare-and-swap, retention, replay
verification, and physical persistence remain obligations of the already
selected `DurableDecisionPortV1` implementation.

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
qualification, source integrity, and the generated qualification manifest. The
canonical source-object inventory explicitly binds lifecycle module wiring,
transition validation, external API tests, deadline forwarding, worker capacity,
product admission, vector publication, and qualification-policy source.
After integration, the merge SHA must run independently; branch-head artifacts
cannot be relabelled as merge evidence.

External gates remain false until separately observed evidence exists for a
production encoder and vector publisher, selected deployment host, hard resource
isolation, real-process kill points, immutable/WORM evidence retention,
independent signature, canary and rollback rehearsal, and formal release
approval.
