# PN0 dependency migration and retained original timeouts — partial

This is a reviewable successor to source `155264e3b5d3dcdafa244cd0c31c336ab25a207f`, on the existing PN0–PN6 plan. Its integration parent is `9d8be55e3763bfaba78d6698c3f31bbd79069d3e`. `task_complete=false`, `merge_ready=false`, **NO_GO**. Nothing here closes the four original Windows native lanes or permits production activation.

## Source and interfaces

The workspace keeps all 22 original AWS package versions, including `aws-config = 1.8.12`, and applies a local fork with the original license and upstream archive retained in the historical archive. Normal credentials-login, SSO and process credentials remain enabled. The fork moves ES256 to p256 0.14.0 / elliptic-curve 0.14.3 / crypto-bigint 0.7.10 / ctutils 0.4.6. It uses the fallible getrandom 0.4 system RNG interface and fails signing on entropy errors. JOSE header/payload, raw 64-byte signature and PEM interfaces remain unchanged. The four original DPoP test function bodies remain byte-identical; three added controls cover key reuse, signature shape and entropy failure. New controls have not passed native execution.

The compression dependency moves to zstd 0.14.3 / zstd-safe 8.2.0. No dependency-policy ignore, original audit configuration, security assertion or runtime limit is relaxed. The local AWS fork follows the existing nonworkspace patch convention: `.bazelignore` prevents a hand-written local BUILD from replacing the actual Cargo-generated external package. `MODULE.bazel.lock` is updated in this change. Six real Bazel queries resolved `@crates//:aws-config` through its version alias to the generated external target and read back normal features, version environment and compile data. Those queries do not qualify the consuming Rust target.

## Actual validation and retained failures

| Evidence | Actual result | Qualification limit |
| --- | --- | --- |
| `just bazel-lock-update` | exit 0, 24.515 s | Lock refresh; no consumer build claim |
| Complete `cargo deny check --hide-inclusion-graph` | exit 0, 11.044 s; advisories, bans, licenses and sources all pass | Original deny/audit policies unchanged; separate adjudication retains generic-owner conservative false flags |
| `just test -p codex-aws-auth --lib` | five original tests pass, zero skips, 152.664 s | Compiles the normal patched AWS library; does not execute the seven private vendor unit controls |
| `just test -p codex-http-client --lib` | 90 original tests pass, zero skips, 90.018 s | Real zstd encode/decode and prepared-body reuse controls pass on this Linux host; other consumers and platforms remain open |
| `just fix -p codex-aws-auth` | exit 0, 90.577 s | Candidate's 76 source bytes unchanged |
| Final `just fmt` after that fix | exit 0, 4.095 s after HTTP consumer validation | All 76 source files unchanged; no redundant test repeat |
| Normal Bazel consumer aquery | **FAIL**, actual 300 s child timeout, 385.775 s whole owner | Child reaped; no action graph, consumer compile or cross-platform PASS |
| Seven private DPoP controls, original owned test-copy attempt | **FAIL**, collector FileNotFoundError during changing Cargo target, 47.877 s | Compiler leader killed and waited; no Rust compiler error or test result was produced; exact historical disappearing path is unknown |
| Same original DPoP window, corrected scan revision | **FAIL**, 24.427 s | Actual temporary-file race was handled, but the unchanged original 550 s child deadline expired. No seven-test enumeration or execution. Original absolute 600 s window is now **EXPIRED**, not reset or reusable |

The temporary DPoP test copy explicitly added the nonmember crate as a test-only member and resolved its nine real development dependencies. Its 1,547-package, 196-member graph preserves all 22 AWS versions and normal crypto features, with test-only increments separately accounted. It is not the 1,538-package, 195-member production graph and is not a production test backdoor. Copied build cache, partial outputs and failed collectors are not a fresh prepared package or passing result. All original partial charges, revision histories, assertions, deadlines and raw outputs remain retained.

The five official hosted cancellation annotations independently say the job exceeded **1h0m0s**. Original GNU Clippy, GNU test, musl-named test, release and SDK logs remain complete. Source review found a missing SDK repository-download-cache restore and an undeclared cache-hit output reference; a separate narrow correction is pending. Download reuse is not action-cache reuse and has no measured 60-minute benefit. Source and logs also show the GNU/musl matrix did not bind its target to a real platform; a musl job name and Bazel progress counters are not musl coverage or test PASS counts. Keep both lanes and all original checks until real toolchain/platform qualification exists. No action-key identity, excess parallelism, fixture hang or equivalent prebuilt V8 remedy has been established.

## Order and acceptance on the existing plan

1. Retain the exact fork, Cargo/Bazel inputs, original source failures and this partial result. Keep the independent source review and raw-byte manifest together with the change.
2. Qualify real compression consumers and the seven DPoP controls under valid admitted execution plans. Expired attempts remain failures; neither a partial ELF nor a new clock closes them.
3. Qualify the normal generated Bazel consumer and the actual GNU/musl toolchains. A download-cache interface fix must retain original features, commands, cache namespace, verification, limits and jobs; its performance effect needs actual measurement.
4. Rebind Hepta to the exact new Chain source and separate ordered-parent main qualification. Execute the original pair, four Windows native lanes and every required exact-head/actual-preview check. Do not replace current retained CI or cancel it to publish these local changes.

The original broad-identity-delete and legacy-delete-boundary failures, whole paid 4097-identity attack, true three model rounds, complete cold release/loader/custody/repair and independent 72-hour WAN gates remain open. Mechanism closure and model benefit remain separate. No source count, local policy PASS or archive hash changes these acceptance conditions.

## Immutable evidence

`members.json` lists each original member's complete size and SHA256. `original-source-controls-and-failures.tar.gz` contains the original 461 source/provenance/control/log/receipt files (52,896,725 uncompressed bytes), with every member read back and verified. Archive SHA256: `ea87d96ef74b1c816ce83472753f0b9753c8bb04d3fea9d3632abd61f1923009`.

The archive excludes live source copies, target trees, Bazel output bases and caches. It includes the original upstream crate, authored and formatting patches, official advisories, all original validation logs, both failed DPoP revisions, generated Bazel readbacks, complete hosted timeout logs and independent reviews. This ordinary historical evidence archive is not an experiment input package, fresh prepared state, storage/network budget proof or native qualification. No original raw result is overwritten by a later adjudication.

Additional real HTTP consumer validation is retained byte-for-byte in `zstd-real-http-consumer-original.tar.gz` with `zstd-real-http-consumer.members.json`. This was the previously unresolved zstd consumer check, not a repeat or renewal of any expired DPoP/SDK/model/W1 window. All 76 candidate source files remained exact.


Storage note: the original artifacts listed in the PN0 source-history index remain in immutable source ancestor `9d88e3e5acdd65272581b32735af8a08cfb65dbc`, with exact path/blob/SHA256/length. See `qualification/pn0-ci/SOURCE_HISTORY_EVIDENCE.md` from the repository root before replaying the original manifests. These manifests and failures retain their original pinned9d scope; this is not current-head qualification.
