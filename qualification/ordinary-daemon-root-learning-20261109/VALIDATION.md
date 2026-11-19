# Native qualification and source binding

Production acceptance remains **HOLD**. The ordinary daemon now has the
original Root checkpoint capability bootstrap, but no deployed stage-owner
composition calls `with_root_learning_stage_owners`. Pending capability is
explicitly refused before runtime setup. No training, independent evaluation,
model publication, production launch or merged-main result is asserted.

## Reviewed source

- User-cited source: `38c95265e8e549ff60fd88e1db5d3bf31b4264e7` (#5430).
- Base: `5530f84e1305c4c86b8be19c4c8765c4340e51db` (#5458, ordinary runtime stack).
- Final code commit: `b443fe0cd7642316d016d78d6d3fbaa3e9dfc341` (#5467).
- Final code Git tree: `4fc761d58f62f7aaa04e2f6571f732a9a1b2a452`.
- This qualification cut changes only this directory. It does not claim its
  own commit identity recursively or substitute a branch name for a source hash.

The code was split into eight reviewable cuts, all below 500 changed lines.
Module/export dependencies were reviewed; native validation was performed on
the combined candidate, not independently on each intermediate review cut.

| PR | Cut | Changed lines | Commit |
|---|---|---:|---|
| [#5460](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5460) | profile | 348 | `2b16de5eb01175ee96ee5f7904a937ebdc639447` |
| [#5461](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5461) | handoff | 310 | `ffe8a29dd0da8cc013f45c340f2540a1f522351d` |
| [#5462](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5462) | registration | 346 | `b6dedd68938eb320a6fb3cad1840ba4ac849aba9` |
| [#5463](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5463) | registration-tests | 266 | `01e51f19b42561562d32ad50c92fbb772d52e443` |
| [#5464](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5464) | service | 356 | `5982a7ba4f22609e7a82c48e0d3853ae8c44783b` |
| [#5465](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5465) | consumer | 312 | `bd2f1f95f223295e52ca39e6d5685073b1a793b3` |
| [#5466](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5466) | consumer-tests | 293 | `3de5d77e5b33b46e9ede44ba0b2e03bcc54dc705` |
| [#5467](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5467) | source-closure | 461 | `b443fe0cd7642316d016d78d6d3fbaa3e9dfc341` |

## Executed qualification

| Attempt | Result | Evidence scope |
|---|---|---|
| Initial compile-only | exit 0 | Earlier 25-file delta; not the final test candidate |
| Formal v1 library run | compile exit 101, zero tests executed | E0599 on `Sha256Digest.to_string()` in a new test; full failure retained |
| Formal v2 library run | **760 passed, 64 skipped** | `just test --locked --offline -p codex-hepta-agentd --lib --test-threads 2` |
| Formal v2 Root subset | **3 passed**, 821 other cases skipped | Real UID 0 via sudo; explicit ignored-case filter and one test thread |
| Formal v2 binaries | exit 0 | `cargo check --locked --offline --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd --bins` |
| Scoped fix | exit 0 | `just fix --locked --offline -p codex-hepta-agentd` |
| Format | exit 0 | `just fmt` from `codex-rs` |
| Maintained and renamed binaries | exit 0 | Final compiler check on the maintained source |
| Final caller closure | PASS | 179 boundaries, 164 protected rows, 6,146 Rust files; `authorityGranted=false` |
| Source regressions | 9 passed | Exact callers, custody/scope checks, open-only recovery and top-level refusal guards |

The three Root tests cover original CAS registration/reopen history, sealed
scope plus dedicated UDS restore, and transfer from actual Root to a separate
UID 60001 child. The child's original output records its actual UID, original
Root PID and `sealed=true cloexec=true`. It belongs to the third parent test and
is not counted as a fourth top-level test. There are 763 passed top-level tests;
skipped cases are never counted as passes. The direct UDS fixture does not test
the complete deployed registered writer/listener path.

The native toolchain used Rust 1.96.0, just 1.51.0 and nextest 0.9.103, an
independent offline target directory, four build jobs and a 32 GiB limit.
Raw logs retain existing nonfatal warnings; no warning-free claim is made.

## Tested versus maintained source

The v2 behavior-test inventory is
`6d63b225d311abe5eb5dde8748376888d8c95b4d2ad97f3a3aa7c7e0caa6a360`. It is unchanged before and after tests.
Repository-required maintenance then touched only 17 candidate Rust files:
formatting and one removal of `.clone()` on a Copy value in a test. A subsequent
two-site API rename from `into_runtime` to `into_learning_runtime` avoids a
conservative typed-caller ambiguity with existing V13 methods. The method body,
old V13 code and scanner were not changed. Per AGENTS.md, behavior tests were
not rerun after fix/fmt; this is recorded rather than treating the two source
inventories as identical. The final maintained/renamed binaries compile.

Final native inventory:
`4cd123acf4cb4133c846600e6564a922c8001d62d52f926d1e05262c0a778925`.
All 10,608 local `codex-rs` objects (10,607 regular files and one symlink) match
that inventory. Every one of the 10,582 unchanged baseline objects was also
checked against its actual Git blob. No source path is missing or additional.
This establishes byte and symlink-target identity, not unrecorded POSIX modes.

Native inventories contain 2,527 preexisting sparse absent/directory entries;
these are not additional source files. The final inventory contains 11,150
actual objects. Native CALLERS remains the baseline version; the candidate
CALLERS and new QA regression are validated separately by the final static gate.
The scanner inputs were unchanged across the complete scan.

The `hepta-joint-propose` helper was reused, not rebuilt in this task. Its pinned
binary SHA-256 is `d347fbab314bda1dc2e29d3f5fca7d7f70eb263dbc740a9e281dc9fd9e312c42`.
The archive records its original compiler artifact/build identities and checks
all 21 source files against this task's source. This is a stated dependency of
the native test result, not a fresh helper-build claim.

## Evidence files

`native-evidence-v1.tar.xz` contains eight attempt records, raw logs, two JUnit
files, failed/test/maintenance/rename inventories, deltas and helper binding.
`source-and-review-evidence-v1.tar.xz` contains the full source projection,
independent evidence review, raw final and earlier caller receipts, formatter
marker adjustments, source fingerprints and publication readbacks. Each archive
has a payload manifest; their full-file hashes are in `SHA256SUMS`.
`validation.json` gives machine-readable scope and results; `published-stack.json`
binds the eight code PRs to their read-back commits and Git trees.

## Remaining acceptance gates

Actual stage owners/recovery, bounded data/training jobs, independent evaluation
and signed attestations, ordinary Circuit providers and governed plasticity must
still be assembled. Published generation requires original protected CURRENT,
Control FinalUse and the guarded successor journal/owner path. The ordinary
`Unpublished` generation is unchanged. Q24 remains stateless, Reset-only and one
forward per task. Single-operation scope, a 500 ms active exchange bound and a
300 s session bound do not establish continuous training or a general LLM ABI.
See [README.md](README.md) for the concrete CLI and original-owner recovery path.
