# MEM12 native execution: recovered original evidence

**Decision: HOLD.** The original native attempt is incomplete. It ran against source commit `811e0e27190066e81a23eebed8ad559ae67d228e`, tree `2043cbf11fd00662cc23562123c27ae4e6f72580`; source identity stayed clean and recorded postimages stayed byte-identical. These results do not qualify the full evidence-branch tree, MEM13, or MEM14.

## Original execution

| Stage | Established result |
| --- | --- |
| Strict isolation | 8 passed, 0 failed: 6 admission cases and 2 Linux namespace cases. |
| Memory episodic | Build failed with phase exit 101 during `cargo test --no-run`. The full original log shows `aws-lc-sys` bindgen using Clang 21 could not find `stddef.h`. **0 Rust tests executed.** |
| Agentd, qualification profile, native delivery, protocol, scoped fix | Not run after the memory build failure. |
| Final format | Passed; source unchanged. |

The original job `1a1cea67111-2564-1763` terminated `failed`, exit 1, `timed_out=false`. Its original 905-byte SDK terminal payload confirms complete, durable output and terminal publication. The original RESULT is 20,931 bytes with SHA256 `34ad8d821103393df9778496c5dd031eb72bea415cf2769fe82a41420286b556`. The source identity and before/after file hashes are retained in that RESULT.

This native attempt made **0 real model calls** and scored **0 memory-benefit episodes**. It does not alter the negative model endpoint evidence retained by parent commit `2bcb8e5f16c0b544294f11a1eafa1bfc281cc714`.

## Repair and continuation boundary

The environment-only repair downloaded and unpacked `libclang-common-21-dev` version `1:21.1.8-6ubuntu1` into a task-private sysroot, without changing system packages or source. The package SHA256 is `c7188f593d77017a4ebb6fea76bb4b5180a3e5a1e7b9f0e3dbd5f5abf7e7183e`; the repair supplies the Clang resource directory through `BINDGEN_EXTRA_CLANG_ARGS`.

Continuation job `1a1ceb9bc10-2564-1808` was launched on the same source for previously unexecuted Rust phases. Its retained publication record says `incomplete`; detailed stage-result readback remains pending in this checkpoint. No continuation pass count is claimed. The submitted continuation does not repeat the 8 strict-isolation cases.

**Collection-path correction:** the original collector path was correct. The earlier hypothesis that the original collector incorrectly ignored `CARGO_TARGET_DIR` is withdrawn. Nextest 0.9.151 resolves its default store as `workspace_root/target/nextest/<profile>`, independently of `CARGO_TARGET_DIR`; JUnit uses that profile store. The continuation changed its collector to a target-dir-based path, which was incorrect. Actual continuation receipt/JUnit recovery is pending; no already executed test is rerun. The original `missing fresh JUnit` observation does not replace the independently established `stddef.h` build failure before Rust tests executed. See the fixed-version [default store config](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/default-config.toml#L4-L7), [store path resolution](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L824-L825), and [JUnit configuration](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L1232-L1241).

## Evidence retained

- `checkpoint.tar.xz` contains the full restored recovery context: original SDK payloads/pages and start/reconcile context, original RESULT and logs, terminal proof, header repair, and exact submitted scripts. `CHECKPOINT_MANIFEST.json` provides SHA256 and byte counts for all 16 members; every member was checked after packaging.
- `EVIDENCE.json` separates source identity, original attempt results, repair, continuation observations, and publication state.
- `SHA256SUMS` binds the published files.

The original remote archive is advertised as 149,224 bytes, SHA256 `5c04dd9bef70c43b6a338f44a254e4b28f4e0533c756a4cba733aeb47882ed7a`. Its version-pinned download is still in progress at this checkpoint; a complete local archive or archive-member verification is not yet claimed. Recovery performed no native job, test, or model rerun.
