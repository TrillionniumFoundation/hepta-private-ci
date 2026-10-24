# Native agent loop

This crate implements a bounded, transport-independent model/tool loop. It has
no dependency on Codex Core or App Server. It is a library component, not a
replacement production agent or a second conversation store.

## Owner integration

`TurnOwner` adapts the existing context and TaskFlow owner. A `Frame` is an owned
view of that owner's current cursor. Committing a model/tool observation must
atomically append it and advance the same durable cursor using compare-and-swap.
A model request is frozen until a terminal observation. Preparing the following
request uses the existing context compiler, memory and compaction owners, with
mandatory instructions and unfinished calls protected. The loop checks payload
bytes against their digest and enforces context, output, tool, round and total
token bounds.

`InferenceOwner` owns dispatch admission and recovery. Its first call may dispatch
an authorized request. Later calls with the same binding and request ID must
observe that dispatch or return `Unresolved`; an ambiguous connection failure
does not authorize another provider call. A recovered terminal output may be
replayed. Live streams begin at byte zero; EOF without `Completed` pauses the
loop without committing partial text or executing proposed tools.
Completion must name the exact request and reference the owner-retained full
provider continuation. The text/tool projection cannot replace encrypted
reasoning or other opaque provider-native items needed by the next request.

`EffectOwner` adapts the existing kernel operation/destination owner or a scoped
runtime operation. It must durably bind the deterministic operation key before
execution. Same-key recovery observes the original effect. Authorization,
destination idempotency and terminal evidence are the effect owner's duties.
The key binds run, turn, generation, admission, round, call ID, tool and arguments.

Cancellation is retained before requesting cancellation from both owners. The
loop declares cancellation complete only after both acknowledge it. Timeout or
unknown cancellation leaves `CancellationPending`. Persistence/owner errors
retain the original cursor for recovery; they do not become successful results.

## Qualification scope

`tests/owner_loop.rs` exercises the public loop with controlled owner adapters.
It checks model/tool continuation, partial-stream recovery, same-key ambiguous
effects, a failed durable-commit boundary, cancellation acknowledgement, deadline,
duplicate calls and context limits. These are orchestration contract tests.
They do not establish provider authorization, real model quality, a durable
product owner implementation, context-compaction preservation, native runtime
process recovery, or performance parity with Codex. Those require the concrete
owner composition and a matched model/task benchmark.

Run `just test -p codex-hepta-agent-loop` from the workspace.

## Existing context compiler adapter

The optional context-v2 feature consumes the existing V2 compilation, exact
serialization, attachment and verified current admission snapshot. It reuses
prepare_delivery_v2, preserves the owner-serialized bytes, checks objective
binding and reserves output capacity inside the same model profile. The
returned preparation must still be bound to a real provider invocation; it
grants no dispatch authority. Tests exercise mandatory instruction/tool
retention during recompilation and reject revoked or foreign context. Semantic
summarization, persisted product continuation and same-model task quality
remain outside this adapter qualification.

Run just test -p codex-hepta-agent-loop --features context-v2 for both the
loop and actual context-compiler integration tests (16 tests at this revision).

## Responses API stream composition

The optional `responses-api` feature projects the existing Codex API response
parser into the native loop without depending on Codex Core or App Server.
It accepts a previously admitted, single-attempt stream; it never dispatches or
retries a model request. Complete provider items, opaque reasoning, message
phases and reported usage are handed to the original continuation owner before
completion is published. Unfinished or duplicate item identities, projection
drift, missing usage and unsupported tool namespaces fail closed.

The retained-item tests use real protocol types and a controlled stream. They
do not qualify provider authentication, live model quality, durable product
owners, remote cancellation, or production compaction/recovery. Stopping local
stream consumption is explicitly not a provider cancellation acknowledgement.
