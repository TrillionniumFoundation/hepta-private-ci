# cognitive.read final-use closure candidate

Status: source changes and regression definitions; exact-head and deterministic
merge execution remain required. All production, activation, independent
acceptance and release flags remain false. See `README.md` for the current
source identity and the distinction between executed checks and authored tests.

## Preserved ownership and budgets

The existing `hepta-memory::CognitiveStore` remains the only durable fact owner.
The read crate does not acquire SQL, mutation authority or a second journal.
Exact-ID V1 canonical bytes, construction preflight and all-or-error behavior
are unchanged. The Agentd response still has the same serialized fields and the
same complete 8 KiB budget. `PreparedReadSnapshotV1` and `OwnerCutReadView` remain
request-local immutable structural views, not authorization/currentness caches.
The existing native worker still records dispatch before owner revalidation and
enters the final-use token immediately before physical `TurnStart`; uncertain
send outcomes remain reconciliation-only.

## Publication evidence and fresh planning

The previous publication plan's receipt field was not part of the final-use
comparison. The opaque Agentd `read_digest` now additionally binds:

- the exact existing owner-cut/read binding;
- the authenticated owner identity and process launch generation;
- the evaluated ordered pre-plan context digest;
- the publication plan receipt digest; and
- the read/abstain disposition.

This uses domain `hepta.agentd.cognitive-context-plan-bound-read.v2`. It does not
change `ReadIdsResultV1` or its canonical domain. It is an integrity binding, not
a signature, a source-authentication substitute or a future-use grant.

The pre-plan payload is reconstructed using the underlying owner-read digest,
not the outer plan-bound digest, avoiding a circular hash. Final use compares
the entire publication binding, rejects changed owner/generation/receipt/payload,
reacquires and verifies the current memory state, rechecks the ranker and retrieval
owners, and checks the memory cut again after those awaited operations.

Only then does the control-plane planner evaluate a **new** one-second
observation. Its checked half-open interval is `[observed_at, expires_at)`, with
clock regression and arithmetic overflow rejected. There is no await between
this fresh planning evaluation and its deadline check. The earlier publication
plan is historical audit evidence and is not reused as an unexpired lease.
An unchanged historical context may be reconsidered only after all these fresh
checks; the implementation does not claim to validate a hidden original expiry
that the existing response schema does not carry.

This does not block a memory mutation after revalidation. It preserves the
existing observation-not-lease boundary and the independent final-use authority
owner rather than inventing a cross-request freshness permit.

### Compatibility and rollback

Old and new contexts retain the same JSON shape, but their opaque read bindings
are not interchangeable. An old in-flight context is rejected by a new owner;
a new context is rejected by the old read-binding verifier. Deployment and
rollback must discard/reacquire in-flight cognitive contexts and retain worker
capability negotiation. Never introduce a fallback accepting an old receipt
without fresh validation. Roll back the Agentd read and final-use paths together.

## Publication versus delivery and physical use

`RetrievalAssignmentFactV1` is an existing write-ahead publication record. Its
legacy `context_exposed` and `delivered_candidates` fields must **not** be
interpreted alone as socket-delivery acknowledgement or proof that the model
used context. The published-context digest binds the final JSON, including the
new plan-bound read digest. Actual dispatch/start evidence belongs to the
existing inference-control journal and must be correlated to that exact digest.
Cancellation, failed delivery, final-use rejection and an ambiguous physical send
must not be upgraded into a confirmed exposure merely because preparation was
recorded. This candidate does not claim that all downstream learning consumers
already enforce that join; the migration remains a separately tracked gap.

## Telemetry

A request-local `OperationObservation` records latency when it is dropped, so
error paths and cancelled futures are included rather than only successful
publications. Final-use failures also reach the existing bounded revalidation
counter and alert path. Additional low-cardinality metrics are:

| Metric | Labels | Meaning |
| --- | --- | --- |
| `codex.hepta.cognitive_read.operations` | `phase`, `outcome` | Completed or abandoned read/final-use attempts. |
| `codex.hepta.cognitive_read.operation_latency_us` | `phase`, `outcome` | Attempt duration including rejection/cancellation. |

`phase` is `read` or `final_use`; `outcome` is `success` or
`rejected_or_cancelled`. Rejection and cancellation are deliberately not falsely
separated when a dropped future provides no finer outcome. The existing
`latency_us` series now includes unsuccessful read attempts. No record, owner,
query, content or digest is used as a label. Telemetry failures do not alter read
behavior. Abnormal process termination cannot run Rust destructors and is not
claimed as an observed cancellation.

## Regression inventory and evidence requirements

New source tests cover publication receipt substitution; owner/generation
binding; ordered payload and disposition changes; fresh-plan boundary expiry,
clock regression and overflow; stale-plan replacement by a fresh evaluation;
dropped and timed-out request accounting; and a real SQLite owner read followed
by final-use receipt/generation/oversize rejection. Existing correction,
tombstone, ranker revocation, source frontier and physical-worker tests remain
mandatory, not replaced by these narrower tests.

The source-preparation workflow is an explicitly scoped authoring operation. It
may format already reviewed Rust paths, repair only Agentd's declared direct
`codex-otel` dependency in Cargo.lock, and make an ordinary source commit followed
by a documentation-only exact-map child. The selected-cut integration is already
materialized directly in ordinary Rust source. It refuses concurrent branch
drift, non-fast-forward pushes, unrelated source edits and elevated acceptance
flags. It does not mutate the read-only qualifier or issue a qualification pass.

## Remaining product work

`SELECTED_OWNER_CUT.md` describes the now-materialized normal Agentd exact-ID
path, which avoids whole-scope history materialization while preserving bounded
selected ancestry and global currentness witnesses. Global ledger counts and
whole-head metadata scanning remain; a transactional owner-maintained root is
not implemented or qualified by this patch. Large-history and deep-ancestry
Rust tests are authored, not yet observed passing.

The seven registered consumers retain their distinct states in
`CONSUMER_EXECUTION.json`; no registered port, source-only canonical shadow or
package pass is relabeled as a completed normal-product migration. Delivery/use
learning correlation, exact source/merge CI, target-host measurements,
independent review and controlled acceptance remain required.
