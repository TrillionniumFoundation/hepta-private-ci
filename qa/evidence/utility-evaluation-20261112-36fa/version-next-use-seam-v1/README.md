# Version-owned evaluated NextUse and completion-readiness service

This is an isolated, unformatted and uncompiled source proposal over canonical
cc57 plus the explicitly pinned shared-readback and same-owner S increments.
It is not an active source change or a qualification result.

The two public Version methods consume an opaque original S and the original
preconnected Unix stream / process identity / UID / held pidfd / timeout /
lifetime. They expose no C owner or config. Both use Version's existing four
connection permits and the original framed transport. Exact method signatures
are in `SOURCE_PACKET.json`; `SOURCE_DELTA.patch` contains the complete changes.

Before admitting either purpose, the Version must already be Published. Under
the same state lock, it reads the original D/T/E and Artifact/CURRENT/C, binds S
to the full retained T/E context, constructs the five-cut reader from the same
already-held C owners, and repeats the full original publication read and final
signature/freshness checks. The existing shared T/E clients are reused; there
is no additional connection, clone of Execute custody, queue or retry.

The new two typed prebound-channel wrappers share one 128-request serving loop.
They call the existing actual response or completion-readiness response. Each
handler is checked before and after against the original Version absolute end.
An original response completed after that end cannot be returned as success.
This does not change the HAP's relative internal end or claim an idle socket is
closed at that exact instant. Existing Selection, legacy read and readiness
methods and Contracts are unchanged. Existing C Sources retain their actual
T/E/S reads; an existing reader is not a permanent live-owner lease.

Six prepared mechanism tests use actual original owners and full opaque S.
The same S receipt owner is consumed into its shared command host and the new
same-owner local readonly API returns S without raw DTO or signature renewal.
The tests cover Pending to actual completed C, authentic foreign S rejection,
withdrawn B, four-cut purpose refusal, and both deadline boundaries. The
crossing probe first generates a real original response and yields until a
narrowed 250 ms end, inside the original 500 ms exchange envelope; it does not
fabricate a successful body or advance a clock. Every introduced helper file
ends in `_tests.rs`. Consumers and servers close/join before original peers and
fixtures are torn down.

The tests are cold same-process mechanisms using enrolled fixture credentials.
They do not establish Fresh Root, public cross-UID four-slot operation,
independent real B, real A/C utility, or runtime qualification. No Rust build,
format, H operation, source gate or test was executed for this packet. The
six test methods require the append-only parent mount in `TEST_MOUNT.json`;
ordinary_path is the sole writer of that parent and must preserve its existing
export/transport registrations. Root must register the new production scopes
and boundaries from final actual formatted bytes before qualification.

The original no-queue shared-client semantics remain. Setup must complete one
admission/probe before starting another reader that needs the same T/E slot;
concurrent reads can still fail as Unavailable. Dropping an async await does
not cancel already dispatched blocking work or establish delivery. Nothing in
the proposal starts C, reconstructs a missing owner, or treats missing data as
NoUpdate or authorization.
