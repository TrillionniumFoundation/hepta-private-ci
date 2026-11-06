# Independent review: B21 collector v3 terminal failure evidence

**Decision: ACCEPT_AS_FROZEN_ORIGINAL_FAILURE_EVIDENCE_ONLY.** No blocking correction to the frozen evidence or its verifier is requested. This accepts the bounded interpretation and offline reproducibility of the recorded failure. **B21 and B15 remain OPEN.** It does not accept a product repair, turn the failed workflow into a pass, or change the original collector's `complete=false`.

Reviewer: `/root/holdout_review`, separate from the author. Review date: 2026-11-06. Reviewed input: `/workspace/scratch/07dd58cc9630/recovery-20261106/b21-collector-v3-native`. Reviewer files and replay are isolated under `/tmp/hepta-runtime-recovery-20261106/b21-collector-v3-independent-review`.

## Frozen identity and reproduction

The freeze is 10,143 bytes, Git blob `b94ccbf22bdeca017e740fcaed20e14f3e06113f`, SHA256 `501e829261c9ab90819c397174460038ab8ed7b45b31a1c85963a8d03191f160`. All 42 payload files, totaling 83,441,944 bytes, matched their full size, SHA256 and Git blob identities before being copied to the isolated replay directory. The author files still matched afterward.

I fully read the final `verify_native.py` (20,446 bytes; Git blob `8dc28a00312f783b3ec9d9c3e633c1fafb39d89b`), `project_compact.py`, the borrowed decoder, fixed `spawn.proto`, and README. I inspected the exact Bazel cleanup methods used by the phase interpretation and the actual embedded collector's exit-comparison condition. The isolated frozen-verifier replay returned **exit 0, stderr 0 bytes**, with **16,908 stdout bytes exactly equal** to the frozen author's stdout: SHA256 `4d6c51be532d1042f12fd997591b7855807dcc05e454950c5b3375a8f87a3317`, Git blob `9b27c21d1be5b60e03ea1457a84c53fa477f5701`.

A separate reviewer script, `verify_independent.py`, also returned exit 0 and empty stderr. It compared every ZIP member with the expanded original, checked full BEP/manifest correspondence rather than only counts, independently counted unique Rust case names for the four failed targets, and checked fresh official metadata and source bytes. `replay.execution.json`, `independent-verification.json`, `all-members.independent.json`, and `additional-confirmation.json` retain these results.

## Official archive and source identity

Official artifact **13481118302** belongs to run **42164663819**, job **127718214088**. Fresh official run, jobs and artifact-collection GETs confirm the completed failure and source HEAD. The entire original ZIP is **78,262,690 bytes**, SHA256 `656b66f8e430497d65258f6b8cc3ec1312c93d47ef3625b80caba32bbc4cbb8b`. Independent reads verified all **1,182 unique members**, every CRC, safe member paths, and **93,538,178 expanded bytes**. Every expanded member matched the corresponding ZIP bytes. The 1,567,240-byte official job log matches SHA256 `7e3fb7e806b8051eb8c5f803a70416a26837666f06a63bba029a094a76210e02`.

The source archive's full 10,583 leaves, modes and Merkle tree were checked in the reproduced verifier. Actual checkout `84cc73453eb926d6f2c5b0372c0287b0ab86ed53` and event merge `285d5727d01e38a76a77441ab038e109dbab787c` share tree `45858bc96c0edbc366ec77991646b15971129975`. Removing only `.github/workflows/b21-intel-original-pty.yml` leaves all **10,582 main67 leaves and modes unchanged**, reproducing base tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`. Source status before and after is clean. The source archive is 65,409,614 bytes, SHA256 `3768639f6442f5f0837332ac31bba393d277dc92f68b1dd684e670f086baa01e`.

Fresh immutable GETs of the actual commit, workflow blob `17ff1640c21876a08396db6a40f131a26870fe84`, and collector blob `ee1b82877fbd55a2e3838d768014715617e05ea0` match this source. The workflow's complete embedded Python collector is byte-for-byte equal to that actual collector blob. This run used the original product source; it is **not** evidence for PTY candidate `8075eb367b6e97546af206b27bbf4a3a867497c8`.

## Denominators and preserved failures

| Evidence level | Verified result |
|---|---|
| Sanitized BEP records | 7,441 |
| Unique testResult attempts | 501: 495 PASSED, 5 FAILED, 1 TIMEOUT |
| Unique testSummary payloads | 438: 433 PASSED, 1 FLAKY, 4 FAILED |
| Retained attempt outputs | 1,002 distinct log/XML files, all sizes and SHA256 checked; all 501 XML documents parse |
| Original console target summary | 438 executed of 605; 434 pass includes the eventual FLAKY target, 4 fail, 167 skipped |
| PTY Rust cases | 28 passed, 3 failed, 31 unique names |
| HTTP client Rust cases | 84 passed, 1 failed, 85 unique names |
| grpc_notifications Rust cases | 0 passed, 4 failed |
| grpc_tcp Rust cases | 0 passed, 4 failed |
| Core | 8 shards, 10 original attempts: 8 PASSED, 1 FAILED, 1 TIMEOUT; target summary FLAKY |

The separate reviewer check found no duplicate testResult or testSummary identity and matched each attempt's status, executionInfo, cachedLocally value and output URIs to the manifest. All 438 summary payloads match fully. Each XML contains one Bazel wrapper testcase; Rust counts above are taken from unique names and final Rust summaries in the logs, not from those wrappers.

I fully read the four failed-target logs. PTY failures remain dropped-output receiver drain, preserved-fd Python REPL readiness, and large-input/EOF close-stdin. The original 2s/5s budgets and assertions are unchanged by source identity. Snapshot fields do not establish a common root cause. The HTTP failure records a test-server read returning WouldBlock/errno 35 followed by a thread panic; both gRPC groups record endpoint readiness timeouts. Core shard 5 first attempt preserves 308P/1F at the fork-history delivery boundary; shard 4 first attempt preserves the 900-second timeout. Their original automatic retries pass, but do not erase either initial failure. Core shard 1's nested 1P child segment is not added to the parent's 321P denominator. Duplicate console tails are not extra attempts.

## Exit phases

The original receipts remain **BEP buildFinished = TESTS_FAILED/3; final Bazel process = 38; collector = 1; console copy = 0**. The retained console reports the BES upload failure after the target summary, following four original upload attempts and `remote.buildbuddy.io` UNAVAILABLE. The collector's only recorded error is `original_bazel_exit_mismatch`, arising from its unconditional equality comparison. The original false flag is preserved.

The three complete primary source files were fetched afresh at Bazel 9.3.0's fixed commit `e89755babf3e941bc1e9d8120b1cd48854ab9dfa` and match the frozen bytes. `ExitCode` defines 3 as non-infrastructure TESTS_FAILED and 38 as transient BES upload infrastructure failure; `BuildEventServiceModule.afterCommand` closes transports and can propagate an abrupt exit; `BlazeRuntime.afterCommand` substitutes a module exit when the original command result is not an infrastructure failure. This supports the reported coexistence of the test-phase result and later upload-phase process result. It does not make the test failures successful or prove an unrelated product root cause.

If a separate future collector revision is desired, the minimal conceptual correction is to represent build-finished and final-process outcomes as distinct phase observations and preserve the supporting upload error. This review does not approve a blanket exemption for exit 38 or replacement of historical `complete=false`.

## Compact bindings and their explicit limit

The full compact log is 8,895,372 bytes, SHA256 `7e62ada62895bbf24f330c4a42dae0bcd7bdaf8de539afb12ffaeab463469257`. Offline replay decoded 68,645,745 bytes and 162,228 records. The fixed proto was independently fetched as actual blob `19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0` and matches. The original invocation explicitly selects SHA-256 and ID `36a1348f-4e3e-4700-94cc-91c8f0d6591e`.

Each of the **four failed targets** has one uncached native TestRunner, darwin-sandbox, exit 101, 300,000 ms. Its own XML helper input-log digest and output-XML digest match the retained bytes. The native spawn does not itself supply a usable test.log output digest, so the README correctly describes the helper-based binding. The ten core native attempts are uncached local spawns at 900,000 ms, with exits 8×0, 1×101, 1×142.

Both core retries retain a real compact limitation:

| Core shard | First / retry helper sequence | Digest recorded for both helper outputs | Actual retained retry XML digest |
|---|---|---|---|
| 4 | 161837 / 162228 | `caae20c8dbdd023f77ca8328f6bfed90dca38411ef7bbde8926a7f7d8b025d2a` | `39aaec96f3f077cabeb658d66204023106732e724a34f5418c9ce6f8621be7d7` |
| 5 | 161101 / 162224 | `8d591859594ea92db36495dd72a9c4061542f21316d0e25e907ca7d6418d772b` | `6980c0bd7451408a73ec580ac47fefce07e6dc3bd030796f65904c0403145172` |

Thus the four failed-target own-log/XML bindings are accepted; an all-ten-core-attempt XML output binding is not claimed. The retry pass observations remain BEP/log/XML observations. No cause for the compact digest reuse is inferred.

## Review boundaries and publication handoff

The retained BEP is explicitly credential-sanitized with three marked opaque payload omissions. Its receipt and the original privacy gate are preserved; this review does not relabel it raw BEP or claim detection of unknown secrets. The three historical offline parsing corrections remain in `development-history`; they do not alter the official archive or native failure.

No Rust compilation, formatting, product test, OS mechanism experiment, workflow trigger/rerun/cancel, ref update, PR update, or author-file edit was performed. Only isolated Python/zstd evidence verification and read-only fresh GitHub GETs were used for verification.

Two direct GETs for the new freeze blob returned 404 while the separate packaging/publication work was still in progress. Therefore the present decision binds the exact verified local freeze and already published original source objects. It does **not** claim that the freeze or b20's eventual delivery archive/registry has already been retrieved from GitHub. That final publication readback belongs to root's handoff. It is not a reason to mutate the frozen inputs.

Primary references: [original failed run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42164663819), [actual checkout](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/84cc73453eb926d6f2c5b0372c0287b0ab86ed53), [actual collector blob](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/ee1b82877fbd55a2e3838d768014715617e05ea0), [fixed ExitCode](https://github.com/bazelbuild/bazel/blob/e89755babf3e941bc1e9d8120b1cd48854ab9dfa/src/main/java/com/google/devtools/build/lib/util/ExitCode.java), [fixed upload cleanup](https://github.com/bazelbuild/bazel/blob/e89755babf3e941bc1e9d8120b1cd48854ab9dfa/src/main/java/com/google/devtools/build/lib/buildeventservice/BuildEventServiceModule.java), [fixed command cleanup](https://github.com/bazelbuild/bazel/blob/e89755babf3e941bc1e9d8120b1cd48854ab9dfa/src/main/java/com/google/devtools/build/lib/runtime/BlazeRuntime.java).
