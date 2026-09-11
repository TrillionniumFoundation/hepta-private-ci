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
native type or infer omitted feedback evidence. A future versioned wire adapter
must bind both graphs, port identities, timing profiles and placement before a
non-compiled-in graph can be admitted. Native feedback cycles are allowed only
with an explicit profile; initialization and fallback remain acyclic.
