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
