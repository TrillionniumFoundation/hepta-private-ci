# Read-only organ runtime

`OrganHostV1` is the process-local composition primitive for a previously
validated `OrganGraphsV1`. It is intentionally narrower than the complete CNS
organ lifecycle.

The host accepts only trusted, compiled-in `TrustedReadOnlyOrganV1` handlers.
The trait is not a sandbox and does not make arbitrary implementations safe.
Product composition must review handlers to confirm that they perform no I/O,
hold no capability, invoke no model, spawn no work and cross no effect boundary.
The host additionally rejects every graph with a non-empty `effect_scope`.

Construction requires exactly one handler for each graph organ. `start_all`
uses the validated initialization order and performs reverse cleanup after a
failure. `dispatch_once` checks the exact graph generation, source, output port,
all destination states and the 64 KiB input bound before calling any handler.
It performs exactly one graph hop; it never recurses, chooses fallback, changes
topology, promotes an organ or grants authority. Every successful delivery is
stamped `AuthorityPosture::DENY_ALL`. Handler faults and oversized replies
quarantine the destination. `stop_all` attempts reverse-order cleanup of every
started handler. Each stop is attempted at most once because the trait does not
promise idempotency; a failed stop is explicitly quarantined rather than retried
implicitly by `Drop`. `Drop` cleans up only handlers with no prior stop attempt.

`HostedOrganStateV1` is only ephemeral host-process readiness. `Ready` does not
mean qualified, canary-approved, production-active or externally authorized.
Those decisions remain outside this host and require a new immutable graph
generation plus the independently governed product admission path.

`replace_read_only_generation` performs an explicit successor-generation
cutover of these stateless, compiled-in read-only handlers. The caller must name
the current generation and provide the immediate successor. Graph validation or
new-handler start failure leaves the old host ready. After successful candidate
start, old handlers stop in reverse order, and exclusive mutable access publishes
the new composition. A predecessor cleanup failure stops the candidate and leaves
the old stopped/quarantined states visible; it never reports a successful cutover
or invents rollback. This permits add/remove/replace of read-only handlers without
pretending to migrate an authoritative writer. Durable/effect-bearing organs
still require the separate state-handoff and product admission protocol.

Protocol compatibility is explicit: native `OrganGraphsV1` is an internal
execution model, not a wire alias of canonical `BodyGraphSnapshotV1`. The latter
currently describes manifest identity, initialization dependency/fallback edges
and order; it does not encode native runtime links, feedback profiles or process
failure domains. A loader must not deserialize that canonical record as this
native type or infer omitted feedback evidence. The compiled, stateless,
read-only subset now has a versioned binding adapter:
`encode_compiled_body_graph_v2` and `decode_compiled_body_graph_v2`, followed by
`VerifiedCompiledBodyGraphV2::into_host`. Its complete native graph and explicit
V1 projection are bound to an independent host-owned digest, generation,
single-process placement and compiled handler manifest catalog. See
[ORGAN_WIRE.md](ORGAN_WIRE.md) for the exact encoding and trust boundary. This is
not a canonical V1 codec, a dynamic code loader, or stateful migration. Native
feedback cycles still require an explicit profile; initialization and fallback
remain acyclic. Binding timing evidence does not implement a periodic scheduler
or prove the evidence's physical claims.

The live `hepta-runtime` status composition uses the registry-gated
`admit_compiled_body_graph_v2` entry point before constructing or starting its
compiled handlers. This is the first native producer/consumer vertical slice;
the resulting receipt remains deny-all and the status graph has no durable
writer or external effect boundary.


## Owner callback failure semantics

`replace_read_only_generation_with_migration` validates the complete successor
and handler catalog before invoking the state owner. Snapshot/migrate/rollback
remain trusted owner callbacks, not an implementation of durable state transfer.
A failed candidate may leave the predecessor ready **only when rollback succeeds**.
If restoration fails, all predecessor handlers are quarantined and reject
further dispatch. A failed predecessor stop returns
`MigrationReplacementStopFailed`, retaining both cleanup faults and any rollback
error instead of discarding it. No callback is implicitly retried.

The regression suite interrupts migration and restoration, rejects an invalid
successor before snapshot acquisition and observes rollback failure after old
handler cleanup fails. A real stateful organ still needs fenced single-writer
storage, quiescence, durable phases and current independent recovery evidence.
These process-local callbacks do not authorize arbitrary schemas or effects.

## Healthy registry-mediated replacement

`OrganHandlerRegistryV1::replace_host` checks the current generation, its exact
successor and every predecessor handler's `Ready` state before invoking a
candidate factory. It then uses the existing graph/binding/digest validation and
start-before-drain cutover. Quarantined or stopped predecessors are rejected;
this entry point does not perform recovery or invoke state-migration callbacks.

Unwinding factory panics become typed faults. Start/stop containment is confined
to the new registry replacement path in `organ_registry_lifecycle.rs`; the
existing shared lifecycle and owner migration/recovery entry points keep their
original callback propagation and rollback behavior. This deliberate small copy
of the read-only bookkeeping avoids changing those other entry points. A failed factory or candidate start leaves the predecessor generation
unchanged. A failed predecessor stop cleans up the candidate and leaves the
predecessor stopped/quarantined, without publishing the successor. The stop
attempt is consumed before calling the handler, so `Drop` never retries that
non-idempotent hook after a panic. Candidate start and cleanup faults are both
retained. This is process-local fault containment for trusted read-only code,
not protection from aborting panics, arbitrary destructors, blocking callbacks or
untrusted code; it adds no message-handler panic or durable recovery guarantee.

`organ_registry_lifecycle_tests.rs` covers healthy 40/41-component addition,
replacement and retirement, repeated generations, rejection before construction,
factory/start/stop faults, and refusal to replace a quarantined predecessor.
A separate boundary test checks that the original owner start-panic path still
unwinds without invoking a new rollback. It does not qualify owner migration.
The separate historical `organ_extension_lifecycle_tests.rs` is not included by
this slice; its migration/rollback and fault-recovery scenarios remain outside
this implementation's claim. Native execution evidence must name the actual
candidate and test selection.
