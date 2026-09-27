# browser.servo remediation ledger — 2026-09-27

## Exact source and scope

The single continuation is PR #1064, branch `codex/browser-servo-full-convergence-20260927`, based on `main@a126987b84737dbc2ee2592442a314117bddb4a2`.
Runtime source immediately before this metadata correction is `650f31244257a8d362e1bbb7fb0a1ea780fc50db`, tree `f50e0b45e75ea55d79908c6a0edd176ee36f5acd`. No other paper/module branch or main was changed. Draft remains required.

This ledger updates the completion statements in the inherited detailed technical guide, worker guide, pin audit and dossier. Those documents remain useful design references, but their stronger source-closure statements do not establish current qualification. The implementation map deliberately retains open repository-controlled gaps. Source hashes identify bytes, not successful execution or deployment.

## Changes actually published

| Commit | Actual scope |
| --- | --- |
| `7a6ce1e95a919e7c84ca9d2885378463b2428c0d` | Selective import from #1010: class-capability validation, operation egress gate, host-private upstream endpoint, bounded framing/deadlines, redaction and matching tests. Kept #1064 native split and journal generation format. |
| `710678f66dda385a3bb60c4c6e854c3b1b60c751` | Read-only composition workflow retains exact source and formatting diagnostics even after earlier failure. Existing tests and strict lint remain. |
| `acdd57f1c1f4dab797eb73c78d2d8e6f11dfbfb6` | Kernel-owned permanent journal lock, immutable transitions, validated incremental indexes, crash recovery, inline retirement, admission/egress storage APIs and real-process regressions. |
| `650f31244257a8d362e1bbb7fb0a1ea780fc50db` | Async DNS/connect cancellation, owned upstream/downstream socket closure, HTTP/CONNECT byte/time bounds, exact pinned HTTP socket use and cleanup retry without dropping resources. |

The new journal admission and egress APIs are storage primitives. The runtime/worker producers and consumers prepared locally are NOT published in these commits. An API test is not a proof that the production call path uses that API.

## Kernel owner lock migration and operational assumptions

The lock is a permanent private regular file at `<journal>.owner-lock`; the owner keeps the open-file description while `/usr/bin/flock` acquires the Linux advisory lock. There is no live stale-PID deletion or lock-directory rename. SIGKILL of the owner releases its descriptor in the kernel.

Never unlink or replace this inode while any writer is alive. Use a protected local Linux filesystem and the same protocol for all writers. A legacy lock directory or legacy JSON lock is rejected rather than reclaimed. Migration requires stopping and observing termination of every old writer, preserving the journal and old lock for review, and installing the new lock protocol offline. Do not mix old and new binaries. A rollback must account for the newer journal event schemas and inline retirement markers.

The launcher checks a canonical root-owned non-writable `/usr/bin/flock`, but exact artifact-digest binding of this new dependency and target filesystem qualification remain open. Root/same-owner malicious lock-inode replacement is not solved by advisory locking.

## Storage and network semantics

Owned appends update validated in-memory operation/profile indexes. Reads reuse the index only when device, inode, size, mtime and ctime match under the owner lock. A foreign append/replacement forces full validation. This improves the ordinary single-owner path; it does not yet provide incremental tail ingestion for a constantly alternating multi-writer workload.

Terminal identities remain monotonic and exact duplicates append no bytes. File/parent fsync, atomic snapshot replacement, bounded capacity and recovery fencing remain required. Empty profile generations can be durably retired. Independent admission and egress receipts survive reopening/compaction; neither is remote business success.

The operation gate stays in front of the profile DNS/IP/SNI broker. Its upstream socket is outside the worker-writable mount. The broker tracks sockets while connecting, checks liveness after async work, limits transfer bytes/time, and waits for actual socket close. Failed gate/network cleanup retains resources for retry and cannot skip the worker stop attempt. Full process/descendant containment still needs the native/runtime continuation.

## Executed evidence and limits

Local runtime: Node v22.16.0 on Linux. No Cargo, Rust compiler/rustfmt, Bubblewrap or built Servo artifact was available locally.

| Source scope | Executed result |
| --- | --- |
| Selected donor import suites | 39 passed, no failures/cancellations/skips. |
| Published journal slice | 87 passed, no failures/cancellations/skips. Includes real SIGKILL, simultaneous lock contenders, foreign-process append and cache invalidation. |
| Published network slice | 28 passed, no failures/cancellations/skips. Includes actual local TCP/UDS connection closure, DNS-close race and oversized response abort. |
| Hash-matched `650f312` package subset | 22 test files, 219 tests: 205 passed, 14 failed, no cancellations/skips. The separate deployment-verifier test was not present in this local subset and is NOT counted as passed. |

The 14 source-matched failures comprise 13 worker-driver cases whose long profile/socket paths exceed the Linux Unix-socket bound, and one runtime fixture still asserting the old fixed ownership digest. Shorter admitted profile roots can avoid the path bound, but the current generated directory naming still needs a product fix; do not remove the bound or suppress the tests.

Larger passing local candidate runs included unpublished protocol/runtime changes and must not be attributed to this remote SHA. CI queued, pending or cancelled states are not successes. No final exact-head/synthetic-merge native qualification, real Servo E2E, public HTTPS, signed multi-builder artifact or target receipt is established by this ledger.

## Outstanding work on this same candidate

1. Fix long profile/socket naming and the stale fixture; run all current Browser files, not a selected suite.
2. Publish and qualify the coherent Browser/Agentd/worker replay and admission protocol, with exact semantic binding. A tool safety check rejected the attempted Browser service protocol write during this continuation; that write was not retried through an alternate route and is not in the branch.
3. Connect real worker-originated admission and operation egress observations to the new journal APIs inside the appropriate authority/durability boundary.
4. Require observed process/descendant/network termination before releasing uncertain ownership or claiming containment. Retain ownership after failed cleanup; do not merely clear handles.
5. Qualify atomic final action revalidation and engine-private DOM node identity. A local fixed-script experiment is not proof against hostile page-realm monkeypatching or identical-shape node replacement.
6. Fix `verify-deployment-evidence.py::require_file`: `Path.stat()` returns a stat result, which has no `is_file()` method. Add runtime tests; Python compilation alone misses this defect.
7. Finish actual service/native/runtime dependency and launcher closure, formatter, strict lint, exact-head and deterministic merge checks, locked Servo build, real sandbox/HTTPS/storage-isolation/recovery/soak, independent builders and signed evidence verification.
8. Reconcile the detailed guides/pin audit with this ledger and actual final source. Continue to distinguish one-in-flight parent calls from resident worker-pool capacity.

## Completion boundary

All stages are not closed. `productionImplementation`, `productExecutionProved`, `deploymentQualification`, `operatorAcceptance`, `activation`, `promotion` and `release` remain false. Credential/upload/download remain disconnected. No merge, bypass, target activation or independent acceptance was requested or performed by this continuation.
