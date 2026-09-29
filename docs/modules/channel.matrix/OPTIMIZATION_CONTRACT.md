# channel.matrix typed sender and observable qualification

Status: source implementation; native and target execution require exact receipts.
This document grants no activation, independent acceptance or release authority.

## 1. Entry ownership and failure types

`outbound_v2/admission.rs` performs pre-entry preparation and can return an
ordinary admission error. Its successful result is either `AlreadyTerminal` or
`Entered(EnteredSend)`. `EnteredSend` has private fields containing the actual
kernel `EnteredUseToken` and a borrow of the exact fenced claim. It is not
cloneable and cannot be constructed by external transport implementations.
The transport outcome is private to `gate.rs`; settlement receives it through a
read-only accessor and cannot replace an entered result with a pre-entry error.

`gate.rs::continue_entered` returns `EnteredSend`, not a fallible admission
result. The inner asynchronous result absorbs binding, timestamp, proof-write,
freshness, cancellation, adapter-boundary permit validation and transport
failures into an indeterminate transport observation. The outer caller retains
the proof through `settlement.rs::settle_entered`. Settlement has no pre-entry
cleanup arm. A failed outcome write leaves the live claim fenced for lease-expiry
recovery and normal authenticated sync reconciliation. Kernel entry alone does
not prove network entry, remote acceptance or logical success.

The sender no longer maintains an independent `entered_effect` Boolean. A
post-entry error cannot cause a later caller to treat the current claim as
unentered merely because an await failed before the Boolean was set.

The public transport trait exposes only a raw seam carrying an unforgeable
`MatrixRawSendSeal`. `MatrixSendPermit` is private to `outbound_v2`, and permit
validation is implemented by one module-private blanket adapter. A transport
implementation cannot override that adapter or relabel a post-entry validation
failure as a remote permanent rejection.

## 2. Just-in-time claims and measurement

`claim_limit` remains a bound from 1 to 256, but now means maximum work per pass.
The sender acquires one lease immediately before preparing that record; later
messages remain unclaimed. This removes speculative lease waiting without
introducing concurrency, a second writer, a fresh transaction ID or renewal of
existing deadlines. Existing retry limits, grant checks and sync terminality
remain in force. Cancellation cannot increment attempts on messages that have
not begun their execution turn.

Per-pass and production-window measurements include claim-to-first-transport-poll
sample count, sum and maximum milliseconds. This measures admission overhead
plus preparation/broker work, not end-to-end delivery. Percentiles require an
external histogram implementation; a maximum or mean is not a p95/p99. No
throughput or latency improvement is claimed until measured on the target host.

## 3. Immutable work versus live checks

An `OutboxRecord` owns its content bytes and remains immutably borrowed with its
binding for the lifetime of a gate. Canonical payload verification is performed
once by that gate before kernel entry. `MatrixSendPermit::new` is an infallible
capture of the already-entered immutable tuple and performs no second digest or
proof validation. The module-private authorized adapter performs one independent
permit/content validation at the actual adapter boundary, immediately before it
constructs the raw transport future. Thus the final gate path has one measured
pre-entry verification and one independent boundary verification, not a third
constructor-time repetition. Neither the signed content nor the durable pin is
changed by this optimization.

Permit validation and construction of the real SDK future occur inside the
first live-gated poll. The gate checks the dynamic authority/session/deadline
window both before and after synchronous adapter construction, then again before
every continuation poll. Consequently an external transport cannot perform
constructor-time work before the final gate, and constructor delay cannot
silently extend the grant or lease window.

On every continuation poll, cancellation, absolute grant expiry, physical lease
deadline, authenticated revocation epoch/revision and exact transport/session
identity are checked again. No authority, session or time decision is cached.
Time is checked both before and after synchronous refresh/identity work. Gate
digest count/time and dynamic-check count/time are distinct counters. The digest
count covers the gate only, not earlier request canonicalization or the
independent adapter-boundary permit validation.

The production final-use broker also reopens and revalidates the private
revocation feed on every poll. The fast path compares the opened regular file's
device, inode, length, nanosecond modification/change times, owner, mode and link
count with the last **semantically accepted** snapshot. An exact match skips only
the bounded file read and JSON decode. A changed identity is read into one
bounded snapshot, revalidated after the read, and admitted only by the existing
monotonic epoch/revision/content rules. Rollback, same-revision drift, malformed
JSON, unsafe paths and files that change during the read fail closed and do not
advance the cached identity. This is an input-decoding optimization, not a
cached authorization decision.

## 4. Operations without a second state owner

`telemetry.rs` emits bounded numeric windows from the production sender every
10 seconds or at task exit. Its schema is
`hepta.channel-matrix-runtime-metrics.v1`. No transaction/room/user/grant labels,
message text, tokens or raw capabilities enter those windows. The collector's
stderr handling is an integration prerequisite, not a claimed deployed dashboard.
A partial failed pass still contributes measurements before the task exits.

`scripts/channel_matrix_diagnostics.py` exposes JSON, parameterized transaction
explanations, Prometheus text and `--check` alert exit status. It opens the
canonical database read-only, reads a consistent snapshot with a resource
budget, and never edits, migrates, retries or grants anything. Unknown live
measurements are explicitly unavailable; a missing checkpoint is not zero lag.
See the runbook for policy thresholds and safe corrective actions.

## 5. Receipt-derived status and compatibility

`scripts/channel_matrix_status.py` generates `status.json` and `status.md` in the
external evidence directory. Source navigation, all-target compilation, native
tests, strict lint and formatting have independent states. A successful compile
cannot imply test execution. Missing, failed, interrupted, stale-source and
hash-mismatched evidence cannot silently become success. The working directory
is recorded as `codex-rs`, so the pinned Rust toolchain and Cargo configuration
are used by all native commands.

`QUALIFICATION_SCENARIOS.json` is a closed, ordered inventory. The generated
`scenario-ledger.json` requires every scenario with a native testcase mapping to
pass in both exact-candidate lanes. Each testcase result is bound to the exact
candidate, source snapshot, focused-command receipt and hashed nextest JUnit
artifact. Missing, skipped, flaky or failed mapped tests remain blockers even
when some other native cases pass.

Target qualification and independent acceptance remain `not_proved` in this
local-command view. Their separately governed receipts cannot be manufactured
by a generator. The final artifact manifest binds the generated status, ledger
and logs. `sourceBase`/`observedAtHead` remain provenance ancestors; exact current
commit, tree and blob identities belong to external candidate receipts.

Migration compatibility is **13**: migration 12 preserves stable-transaction
terminal proof across attempts, while migration 13 adds durable inbox recovery
scheduling and monotone quarantine. Startup and rollback documentation must not
approve an older binary that only understands migrations 1-12.

## 6. Regression inventory

| Scenario | Source coverage | Required execution |
|---|---|---|
| Later messages have no speculative lease; work-per-pass bound remains | `final_poll_regressions/optimization.rs` | locked native test |
| Cancellation after entry leaves current unknown and later attempts untouched | same fixture | locked native test |
| Multiple polls retain one gate digest and fresh dynamic checks | `pending_poll_regressions.rs` | locked native test |
| Unchanged revocation feed skips reread/decode; changed accepted feed is applied once; rejected identity is never cached | `hepta-matrixd/src/final_use/revocation_file_tests.rs` | locked native unit test |
| Typed entered result preserves post-entry errors and exposes outcome read-only | gate/settlement plus `test_channel_matrix_transport_boundary.py` | Python boundary regression and locked native test |
| Permit construction is infallible/non-validating; exactly one independent adapter-boundary validation remains | `test_channel_matrix_transport_boundary.py` plus native compilation | Python boundary regression and locked native compile |
| Public transport cannot override permit validation; real future construction remains inside the first gated poll | `test_channel_matrix_transport_boundary.py` plus native compilation | Python boundary regression and locked native compile |
| Numeric telemetry saturation and identity-free output | `outbound_v2/telemetry_tests.rs` | locked native unit test |
| Diagnostic read-only, missing measurement, capacity, parameterization and migration rejection | `test_channel_matrix_diagnostics.py` | Python with real SQLite migrations |
| Receipt scope separation, stale/mutated/Boolean/duplicate rejection | `test_channel_matrix_status.py` | Python evidence fixtures |
| Closed scenario inventory and per-test artifact binding | `test_channel_matrix_qualification.py` | Python evidence fixtures plus exact nextest JUnit |

Real encrypted-session rotation, authenticated restore, sustained retention,
paired-runtime Synapse qualification and independent operator/security
acceptance remain required; these source fixtures do not replace them.
