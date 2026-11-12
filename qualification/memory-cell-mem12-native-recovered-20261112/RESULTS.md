# MEM12 native execution: recovered evidence

**Decision: HOLD.** Recovered evidence establishes 8 strict-isolation passes in the original attempt and 11 memory-test passes in continuation 01. Native qualification remains incomplete: later agentd, profile, delivery, protocol, and scoped-fix stages have not been qualified by the completed attempts retained here.

Both completed attempts used source commit `811e0e27190066e81a23eebed8ad559ae67d228e`, tree `2043cbf11fd00662cc23562123c27ae4e6f72580`. Source identity stayed clean, all 25 recorded postimages stayed byte-identical, and final format passed. These results do not qualify the full evidence-branch tree, MEM13, or MEM14.

## Execution results and preserved failures

| Attempt / stage | Established result |
| --- | --- |
| Original: strict isolation | 8 passed, 0 failed: 6 admission cases and 2 Linux namespace cases. |
| Original: memory episodic | Build failed with phase exit 101 during `cargo test --no-run`. The original log shows `aws-lc-sys` bindgen using Clang 21 could not find `stddef.h`. **0 Rust tests executed in this attempt.** |
| Continuation 01: memory episodic | Command exit 0; original receipt and recovered JUnit prove **11 passed, 0 failed, 0 skipped**. Strict isolation was not repeated. |
| Continuation 01: collector | Runner marked the phase failed because it looked for JUnit in the wrong directory. The original failed RESULT remains unchanged; the correct-path original JUnit and log were recovered without rerunning tests. |
| Later native stages | Not executed by the original attempt or continuation 01 after their respective stop conditions. Continuation 02 is running; no execution result is established here. |
| Final format, both completed attempts | Passed; source unchanged. |

Original job `1a1cea67111-2564-1763` and continuation 01 job `1a1ceb9bc10-2564-1808` both terminated `failed`, exit 1, `timed_out=false`. Original SDK terminal payloads confirm complete, durable output and terminal publication. These outer failure states are preserved separately from continuation 01's successful memory-test command.

Continuation 01's recovered JUnit is 2,717 bytes, SHA256 `6c3e2fbc6551df44daa77d4b74349eee80afcf0d3237318759f7f2d03ea02af2`. Run UUID `372c4563-0ab7-41df-ac66-f2a8d9c87bb8` occurs in the original log; all 11 unique case timestamps fall within the original receipt, and no case is failed, errored, or skipped. Full source identities, original RESULT hashes, raw SDK bindings, and case names are retained in the manifests.

Both completed native attempts made **0 real model calls** and scored **0 memory-benefit episodes**. The negative model endpoint evidence in parent commit `2bcb8e5f16c0b544294f11a1eafa1bfc281cc714` is preserved. Native software-control passes do not establish memory benefit.

## Environment repair and collection-path correction

The environment-only repair downloaded and unpacked `libclang-common-21-dev` version `1:21.1.8-6ubuntu1` into a task-private sysroot, without changing system packages or source. Package SHA256: `c7188f593d77017a4ebb6fea76bb4b5180a3e5a1e7b9f0e3dbd5f5abf7e7183e`. `BINDGEN_EXTRA_CLANG_ARGS` supplies that Clang resource directory.

**The original collector path was correct.** The earlier hypothesis that it incorrectly ignored `CARGO_TARGET_DIR` is withdrawn. Nextest 0.9.151 resolves its default store under the workspace root and uses that profile store for JUnit, independently of `CARGO_TARGET_DIR`. The original path was `source-v2/codex-rs/target/nextest/local/junit.xml`; continuation 01 incorrectly changed it to `cargo-target/nextest/local/junit.xml`. See the fixed-version [default store config](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/default-config.toml#L4-L7), [store path resolution](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L824-L825), and [JUnit configuration](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L1232-L1241). This correction does not change the original `stddef.h` build failure.

## Continuation 02 handoff

The exact 20,240-byte submitted script is retained with SHA256 `38dcba3805a83ddf980d27d53c4263fcc261b209b2630c4991cf0142839bd0b7` and idempotency key `mem12-native-unexecuted-continuation02-811e0e27-20261112-ef0c-v1`. Initial acknowledgement was UNKNOWN after an MCP timeout; that record remains unchanged. Subsequent exact same-key reconciliation returned original job `1a1cedb0568-2564-18ae`, `reused=true`, `retried_launch=false`, observed running. No result or pass count is inferred. The submitted script verifies prior memory evidence, uses the correct JUnit path, and skips strict8/memory11 before the remaining stages.

## Artifacts and integrity checks

| Artifact | Content and verification |
| --- | --- |
| `native-811e0e27.tar.xz` | Unmodified original archive: 149,224 bytes, SHA256 `5c04dd9bef70c43b6a338f44a254e4b28f4e0533c756a4cba733aeb47882ed7a`. |
| `ARCHIVE_VERIFICATION.json` | All 101 tar members checked: 75 regular files and 26 directories, safe relative paths, no links or special files. Original manifest covers the other 74 files; every size/hash, all 25 source postimages, all phase logs, and the empty rewrite patch were verified. |
| `archive-recovery.tar.xz` / `ARCHIVE_RECOVERY_MANIFEST.json` | Three version-pinned chunks, 17 SDK pages, three complete original SDK payloads, read requests, and transport attempts. Every payload/chunk hash and the whole archive hash verified. |
| `checkpoint.tar.xz` / `CHECKPOINT_MANIFEST.json` | First immutable recovery checkpoint: original SDK/start/reconcile context, RESULT/logs/terminal proof, header repair and exact scripts; all 16 member hashes checked. |
| `continuation-recovery.tar.xz` / `CONTINUATION_MANIFEST.json` | Continuation 01's original RESULT, terminal SDK, JUnit, receipt, log and complete SDK pages; verified UUID/case/receipt binding. Continuation 02's submitted script, initial unknown record and subsequent original-job reconciliation are separate. |
| `EVIDENCE.json` / `SHA256SUMS` | Machine-readable boundaries and SHA256 checksums for published artifacts. |

The original archive was downloaded and verified without alteration. No native job, test, or model call was started by this publication task. Previously published checkpoint bytes and original failed results remain unchanged.
