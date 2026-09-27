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

## Outstanding work recorded at bfca18dc (see continuation below)

1. Fix long profile/socket naming and the stale fixture; run all current Browser files, not a selected suite.
2. Publish and qualify the coherent Browser/Agentd/worker replay and admission protocol, with exact semantic binding. A tool safety check rejected the attempted Browser service protocol write during this continuation; that write was not retried through an alternate route and is not in the branch.
3. Connect real worker-originated admission and operation egress observations to the new journal APIs inside the appropriate authority/durability boundary.
4. Require observed process/descendant/network termination before releasing uncertain ownership or claiming containment. Retain ownership after failed cleanup; do not merely clear handles.
5. Qualify atomic final action revalidation and engine-private DOM node identity. A local fixed-script experiment is not proof against hostile page-realm monkeypatching or identical-shape node replacement.
6. Fix `verify-deployment-evidence.py::require_file`: `Path.stat()` returns a stat result, which has no `is_file()` method. Add runtime tests; Python compilation alone misses this defect.
7. Finish actual service/native/runtime dependency and launcher closure, formatter, strict lint, exact-head and deterministic merge checks, locked Servo build, real sandbox/HTTPS/storage-isolation/recovery/soak, independent builders and signed evidence verification.
8. Reconcile the detailed guides/pin audit with this ledger and actual final source. Continue to distinguish one-in-flight parent calls from resident worker-pool capacity.

## Completion boundary retained

All stages are not closed. `productionImplementation`, `productExecutionProved`, `deploymentQualification`, `operatorAcceptance`, `activation`, `promotion` and `release` remain false. Credential/upload/download remain disconnected. No merge, bypass, target activation or independent acceptance was requested or performed by this continuation.

## Owner and verifier continuation from bfca18dc

This continuation extends `bfca18dcc4b2cba7be1e248050fd78efede11bf0` on the same PR #1064 branch. Its accompanying source registry binds the changed and newly added files. It does not import results from unpublished patches or replace unrelated Agentd/Servo work.

### Implemented changes

The subprocess driver now allocates a `p.<128-bit-random-hex>` directory independently of profile/principal identifier length. The exact identities remain in the host-private ownership manifest and private protocol. A conservative 103-byte UTF-8 socket pathname bound is checked before resource allocation; an excessive root still fails explicitly rather than truncating names or disabling the bound. The driver returns `privateProfileDirectory` only as in-process composition metadata for the existing effect-network wrapper. `BrowserProfileHost` publishes its explicit identity receipt, not that path.

`OwnedBrowserChild` retains the actual acquired child and observed Linux PID/start-time lifetimes. A successful signal request is not an exit observation. Startup failure, pre-admission cancellation, explicit containment and lease expiry wait for owned process exit and broker shutdown. An incomplete cleanup retains handles and raises `BROWSER_CONTAINMENT_UNPROVED`; it cannot free a pool reservation. Filesystem cleanup clears each owned path only after deletion succeeds and never deletes a failed exclusive-create collision. A later stop retries the same owner without spawning a replacement. Concurrent starts are excluded, concurrent stops share the complete retirement, and effects are fenced as soon as shutdown begins. A pending startup cannot be reported stopped by a pool no-op; its caller must cancel startup first. The physical lease uses both wall-clock and monotonic deadlines.

The Linux process census is bounded and observes only captured lifetimes. It does not signal raw descendant PIDs. It is not independent proof that every possible descendant of a compromised worker is contained; production namespace teardown and exact target-host descendant tests remain mandatory. The outer admission decorator and Rust parent still require their own error propagation and final-use-fence ordering qualification.

The deployment verifier now uses `lstat` plus `stat.S_ISREG`, rather than calling the nonexistent `stat_result.is_file()`. It rejects nonregular/final-symlink, empty and oversized evidence; bounds actual JSON reads; rejects duplicate keys, non-finite constants and invalid UTF-8; and compares expected JSON fields without Boolean/integer coercion. Workflow inputs require canonical positive run IDs and `status=completed` plus `conclusion=success`. Builder locks are checked against the exact committed source lock, and finalization binds the multi-builder and attestation receipts to the current source/tree/pin/worker/run tuple instead of relabelling old aggregate evidence. The workflow's cryptographic `gh attestation verify` remains required. These unit tests are not signed build or target evidence, and hostile filesystem replacement between separate reads is not claimed solved.

### Validation actually executed for this continuation

The original driver and original test file were first checked against Git blobs `67859381b2bb4b7353950b80b48e7010428b9137` and `62036cc612bbf432d9a48af82ffec18512850cca`. A separate baseline execution ran 21 cases: 8 passed and 13 failed, with no skips/cancellations. Twelve failures hit the Unix-socket path bound and the pool test exposed a missing `rm` import. This baseline is distinct from the historical 219-case run above.

After the source fixes, all 21 original driver assertions remain. The missing `rm` import is fixed. The explicitly selected command below passed 41 Node top-level tests, with zero failures, cancellations or skips, on Node v22.16.0/Linux:

```sh
node --test --test-reporter=tap \
  apps/hepta-browser/test/worker-driver.test.js \
  apps/hepta-browser/test/profile-artifacts.test.js \
  apps/hepta-browser/test/worker-lifecycle.test.js \
  apps/hepta-browser/test/worker-owner-regression.test.js \
  apps/hepta-browser/test/evidence-runtime-regression.test.js
```

The 41 cases comprise 21 retained driver tests, 3 path tests, 6 lifetime tests, 10 driver-owner regressions and 1 wrapper that executes 11 Python verifier tests. The Python tests also passed separately using `python3 -B apps/hepta-browser/test/evidence-runtime-regression.py`. Do not count the wrapper and its nested cases as two independent qualifications. Available JavaScript files were syntax-checked individually; the modified Python verifier compiled successfully.

Real local OS processes and Unix sockets are used for exit-before-return, admission cancellation, startup cleanup, lease expiry and pool-capacity retention tests. The child is a Node private-protocol fixture, not Servo; its test launcher is not Bubblewrap. The local checkout contains only the listed test/dependency subset. This is NOT a complete Browser suite, full source-registry execution, native Agentd/Servo build, final-head/synthetic-merge pass, public HTTPS test, soak or independent target receipt. Original and modified file hashes and raw passing/failing logs are retained as local diagnostic evidence.

### Still open after this continuation

The preceding outstanding-work list is historical. Its socket naming and verifier runtime-error items are addressed above; the stale full-runtime fixture and full-package execution still require verification. Remaining repository-controlled work includes coherent native replay/admission protocol, real worker admission and egress producers connected to journal storage, propagation of outer-decorator cleanup failure without converting it into success, and Rust containment before final-use-fence release. Engine-private DOM target identity and atomic final action admission are not implemented by this patch. Actual service/runtime/launcher artifact closure, flock identity, strict native formatting/lint and full exact-head/merge qualification remain open. Updating the detailed design guides cannot substitute for those implementations or tests.

No main update, protected-branch bypass, production activation, independent acceptance, promotion or release is performed. Credential/upload/download remain disconnected. The user-requested four stages are not fully closed.
