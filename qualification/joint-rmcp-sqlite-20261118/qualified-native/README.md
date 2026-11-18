# Actual joint dependency and Mac native qualification

## Sources and outcome

The frozen joint runtime/dependency source is `2b3642214ba5ff4aaac27de13322a354a69507e7`, tree `4f558b31a5ea13d3ddf7fa43aec605dd478ef072`. The two hosted qualification jobs actually executed `7fc46c193a9ff8726e43fca2982d9b8f455e3dac`. Their only difference is retained qualification metadata; [SOURCE_RELATION.json](SOURCE_RELATION.json) records the exact Git comparison. This evidence publication changes no production source, dependency, test assertion, deadline or workflow.

| Actual scope | Executed result | Scope retained |
| --- | --- | --- |
| Hosted RMCP qualification | 278 passing Rust case executions, 0 failed; 273 distinct passing target/case identities | 7 ignored registrations; spawned helper executions are counted explicitly. 24 of 42 Bazel test targets executed; 18 Windows cross targets were skipped. |
| Hosted SQLite qualification | 284 passing Rust case executions, 0 failed; 284 distinct passing target/case identities | 2 existing old-version fixture entry points ignored. 9 of 14 Bazel test targets executed; 5 Windows cross targets were skipped. |
| Original Mac fixture repair source `9aaac03f` | 11 unique cases passed once; original command exit 0 | Two earlier attempts executed zero cases. The third outer collector exited 1 because it searched the wrong report directory; its actual original JUnit was recovered read-only. |
| Joint source `2b364221` on Mac | 11 unique cases passed once; command and outer owner exit 0 | A separate source checkout and target executed the same original 11 cases, with no retries and original negative assertions. |

The two hosted jobs include the actual compile, Clippy, operations, canonical lock-generation/check and selected test steps. They do not constitute whole-repository or native Windows qualification. The retained unmaintained Chrono advisory and the original Windows legacy-isolation limitation remain open.

## Hosted original artifacts and exact locks

RMCP: [run 44359468610](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44359468610), job `134996522149`, artifact `14456513074`. The complete [original ZIP](RMCP_ORIGINAL_ARTIFACT.zip) is 8,938,554 bytes with SHA-256 `f8afadfbaf42a5305c7b5e22e5550f7f15ec728871ae42699f38840a21e08d29`. All 15 members match both the GitHub artifact digest and the independently reopened bytes.

SQLite: [run 44359468771](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44359468771), job `134996523370`, artifact `14454168128`. The complete [original ZIP](SQLITE_ORIGINAL_ARTIFACT.zip) is 7,762,562 bytes with SHA-256 `a2af9f6c35daf91c047071845964a855ac763305f8a29b7f5faff4078fc53ecf`. All 16 members were independently reopened and checked.

Both jobs report the actual source head and retain identical committed locks:

- Cargo.lock: `dab5a95131e1b9c9b75144f6309d3a5686c2b82a5aee6a830d31bbeebfc8faf7`.
- MODULE.bazel.lock: `d240b972292c4101a01eceb1281dd15cdc43c77979711281bcaa5d0c680580c1`.
- Both original `locks.patch` files are empty. The graph contains RMCP 3.9.0, rusqlite 0.43.0 and one libsqlite3-sys 0.40.0.
- [CI_READOUT.json](CI_READOUT.json), [RMCP_CASES.json](RMCP_CASES.json) and [SQLITE_CASES.json](SQLITE_CASES.json) bind every parsed case to its original log line, target, result section and explicit duplicate helper identity.
- [CI_AUDIT_ORIGINALS.tar.xz](CI_AUDIT_ORIGINALS.tar.xz) retains 56 audit/API/runtime originals, including the first reader failure from assuming `both-locks.patch` instead of the actual `locks.patch`. It executed no new native tests. SHA-256: `849ff0ed264d459a7d8cfd96cb4c1699048e3e0887f59b7ca3cacf68eb0ec782`.

The complete original ZIPs contain the original Bazel execution logs, compiler/test logs and source/lock records. No synthetic JUnit is substituted for these hosted logs.

## Original Mac failures and recovered report

The first native attempt failed offline dependency resolution before any test ran. A source-preserving locked fetch completed. The second attempt reached compilation and exposed a missing tracked `docs/modules/MODULES.json` input, again before any test ran. The materializer restored that file and `qualification/neuron-v13-generation/proposal_worker.py` from their exact source Git blobs.

The first 11,217-file source inventory remains unchanged. A separate expanded 11,219-file inventory includes the two recovered compile inputs, and verifies all old entries as an unchanged subset. The expanded inventory SHA-256 is `a31830ad74600b5a339258870b05aea8b0ef17408db3977eb9b75642a0bc04e9`.

The third attempt actually ran all 11 cases and exited 0. Nextest wrote the original report under the workspace's `codex-rs/target/nextest/local/junit.xml`; the outer collector looked under its separate Cargo build target. [The failed original RESULT](mac-9aa-attempt3-original-RESULT.json) remains unchanged. The [read-only recovery](mac-9aa-recovered-READOUT.json) verifies the original timestamp, stderr UUID and 11 unique passing case names. No case was rerun to recover the report.

Original JUnit SHA-256: `2335596975d306299217427e112d6677eaaebcdb00c95a2b318c3bf89a2cce5d`; run UUID `fec7d29f-a476-4fd4-a1f8-9312cf519221`. The actual command took 47.040760 seconds including compilation; the original JUnit test window was 0.220 seconds.

## Independent joint-source Mac execution

Actual owner job: `1a1efe51808-ffbe-669`, succeeded, exit 0, complete durable output, no timeout or automatic retry. [RESULT](mac-joint2b-RESULT.json) SHA-256: `d85b293244e2c5bec3fd43056482d3821fdb65a13a75be612e33a5a106942e8e`. [Original JUnit](mac-joint2b-original-junit.xml) SHA-256: `f0372ec53780748a849d6edbd3605f931fdd45669ca0f9afdfbb1aba1a6a3789`; new run UUID `a81117c9-07d9-42c2-bc7e-52d72c29df01`.

All 11 expected cases appear exactly once with zero failures, errors or skips. The original command retains `--retries 0 --test-threads 1 --no-tests fail`, original test names and negative assertions. The 11,598 materialized source files match their immutable inventory before and after execution, SHA-256 `972bb31325a567812e6d22666ddfab4cb24ee790e00a49643d6ae55b491c42af`.

An APFS copy-on-write clone of the already completed owned cache created a separate target. All 50,958 regular files were checked for distinct inodes and a link count of one. The old target was not shared writably. Clone time was 8.797532 seconds; the actual test command took 180.443411 seconds including compilation, and the entire owned validation took 192.688596 seconds. JUnit's test window was 0.232 seconds. These nested times must not be added as independent costs. Energy and monetary costs remain unmeasured.

## Complete Mac originals and publication

[MAC_ORIGINALS.tar.xz](MAC_ORIGINALS.tar.xz) retains 280 indexed original files plus the index, including all owned source-recovery carriers, failed preparations, native owner programs, original logs/receipts, actual JUnit reports, source snapshots and runtime terminal records.

- Archive: 52,331,264 bytes; SHA-256 `47db68782b3d13983749221886d74d8e04e195f1ba403f0a31aeebe2e13be548`.
- [MAC_INDEX.json](MAC_INDEX.json) SHA-256: `6c1dd2a4d724f1c3159104b313246497fccc18abbb7f1b638cb7f8889354b0bc`.
- All members were reopened and checked against original lengths and hashes. Complete source trees and build caches are referenced by immutable Git identities and full inventories; compiled target caches are not in the archive.
- GitHub REST refused the intact archive with HTTP 422 because its request was too large. The same verified bytes were then published through normal Git transport. The original API error and sealing program remain under `publication-failures/`; no archive was split or rewritten.
- The repository's existing exact-path plus exact-SHA allowance binds these three complete archives only. The global 512000-byte limit and original checker remain unchanged. The seven original policy tests and actual published comparison are the final publication gate, with their separate receipts retained when complete.

This evidence does not change E1–E6 outcomes or provide native owner adoption, FinalUse, settlement or an energy-complete cost claim.
