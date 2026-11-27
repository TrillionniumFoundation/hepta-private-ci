# Local lease expiry test clock

## Observed failure

The original musl test `explicit_owner_expires_bound_lease_and_fences_old_witness`
failed while opening its bound executor, before the intended owner expiry and
old-witness assertions. It set the expiry to the current whole Unix second plus
one before asynchronous acquisition. The remaining setup window can therefore
be arbitrarily shorter than one second. The original rejection was
`Lease(StaleFence("local lease has expired"))`.

## Candidate scope

The non-default `test-lease-clock` feature adds a clock binding to one
`LocalLeaseOutbox` handle. The extension enables that feature only through its
development dependency. Bazel uses its existing test-only library variant and
dependency replacement mechanism. The ordinary library target and default
Cargo feature set do not expose this helper or contain the optional field.
Explicitly enabling a test feature is a build convention, not a security or
authority boundary. A Cargo test or all-targets build can unify development
features across the selected graph.

Newly acquired and reopened handles default to the system clock. The helper
consumes an explicitly selected handle and attaches an `Arc<AtomicU64>` holding
Unix seconds. Subsequent clones share that same clock. In particular,
`LocalCompactExecutor::open_bound` retains `Some(lease.clone())`; it does not
reconstruct that handle from the persisted row. Binding occurs before this
open and before the first active-lease check.

Only the two existing deadline reads are routed through the handle: active
validation and the normal expiry transition. Every identity, epoch, generation,
fencing token, current-head, journal, store-binding, and terminal-state check
remains. With no test clock, the same system-time conversion and errors apply.
The existing unit-only explicit expiry override is unchanged. Database record
timestamps, store-wide head inspection, serialized lease fields, and the
production lifecycle owner are unchanged. This is not a store-wide simulated
clock; a separately acquired or reopened handle must be explicitly bound if a
test needs it to use this clock.

## Preserved test contract

The affected extension fixture starts its controlled clock at 1000 and keeps
`expires_at = starts_at + 1`. Setup cannot consume that logical second. The
original loop still has 120 iterations and the same 25 ms sleep. After each
existing sleep, the fixture advances its clock by the accumulated 25 ms ticks;
40 ticks reach the one-second expiry. It adds no wait, retry, or larger TTL.
Scheduling can still delay the test in wall time, as with the original loop.
The controlled clock establishes deadline semantics rather than measuring
real-world scheduler performance.

All previous assertions remain: store mismatch, owner registration flags,
explicit expiry, idempotent terminal replay, executor and admission rejection,
and the next generation's binding. The expiry assertion observes the same
clock used by the lease. The next expiry is derived from that same clock.

Additional behavior controls require that terminalization before the deadline
is rejected and that the already-open executor rejects an expired active lease
before any terminal row is written. A dependency unit test advances one clock,
checks that its original and cloned handles both expire while a separate clock
remains active, then creates the next generation and checks that the old clone
still fails the identity guard. The early expiry attempt must not append rows.
These are Rust test sources pending actual execution, not recorded passes.

## Qualification still required

This candidate does not claim a native pass. Static review must bind the two
clock reads, unchanged production guards, all old test bodies outside the one
fixture, the exact Cargo feature route, and both Bazel target variants.
`just bazel-lock-update` is required by the repository because Cargo manifests
change; its actual result and any tool absence are recorded separately. No
lockfile is edited by hand. No new external dependency is requested.

The next normal qualification needs the memory and extension library tests,
strict lint, and the existing lock-drift check. It must show the ordinary Bazel
library still has no clock feature and that the extension test graph contains
one memory crate identity using the test-only variant. Default Cargo builds
must not activate the development feature. Source review or a syntactic graph
comparison is not a substitute for those actual build and behavior results.
