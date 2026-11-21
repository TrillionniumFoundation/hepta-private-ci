# PR #6799 original `6cb` — final CI facts

Exact source: `6cbad406a4a203201edc0e103c1377d3664e3fbe`; tree `08f5d464bedff1c1acbb3abe1d7f28e43827854f`. Base: `69ec34ac53176ff1e46a1689048817c91adb5be2`. GitHub synthetic merge `7714fcc496317e0d09c8673e172f7749d6147608` and the operator job's deterministic merge `53995eb8862380d508ac50e5220d47811da05958` have the same source tree. Execution identity remains explicit; equal trees do not merge separate CI qualification requirements.

At 2026-11-21 12:43:39 UTC, all **102** exact-head checks were terminal: **70 success, 17 failure, 13 skipped, 2 cancelled**. These counts include aggregate checks and repeated source/merge scopes. They are not counts of unique tests. CI required, Architecture required, original Windows required, and learning.operator required are all failures.

| Scope | Exact original-head outcome | Qualification limit |
| --- | --- | --- |
| B4, repo-checks job `136829982050` | 1350/1350 tests passed, 411.440 seconds, on synthetic merge with identical source tree | Containing job later failed four Python formatting files |
| Agentd strict Clippy, jobs `136829982322` / `136829982227` | Source and deterministic merge both exit 101 with the same seven diagnostics | No Agentd strict Clippy pass for `6cb` |
| Architecture source `136829413505` | 33 completed command records all passed with unchanged source; then cancelled | Runtime-tasks compilation incomplete. The 60-minute workflow timeout is a timing-based inference. Same-tree base-merge skipping does not complete source qualification |
| Daemon native `136829413045` | Ordinary selected cases 2831/2831 passed (186 skipped); original Root parent cases 68/68 passed (1980 skipped), exact expected names verified | Whole job failed in subsequent maintenance, not in these test selections |
| Original Windows | 19 declared groups / 175 exact cases: 171 passed, four positive elevated cases failed, zero retries | Existing unconditional production admission refuses before fixture paths or DACLs are inspected |
| macOS Intel and ARM AuthBus | Each 45 passed / six fixture failures | Original noncanonical fixture parents trigger `UnsafeCheckpoint`; two-helper fixture candidate separately reviewed |
| Windows evidence AuthBus | 76 passed / two positive tests failed, one ignored, 61 filtered; target timeout 300.7 seconds | Non-Unix production parent validation unconditionally returns `UnsafeCheckpoint`; fixtures already canonicalize |
| Musl Agentd | 395 passed / one failed in affected shard, 44 ignored, 1283 filtered | Original live evidence read reached unchanged 500 ms deadline (501403 microseconds); no widening justified |
| Shared Cell owner libraries | 2051/2051 selected cases passed, 171 skipped | Overlapping scopes are not summed with daemon suites |
| Memory Neuron native owner | 411/411 passed, zero skipped | Original source scope only |
| TypeScript SDK | 47/47 tests in 5/5 suites passed | Earlier-head SDK timeout does not apply to this head |
| Learning artifact source | Qualified, including strict Clippy for learning-artifacts | Does not cover Agentd strict Clippy |

The daemon native artifact independently confirms checkout, before-tests, and after-tests inventories are identical: 59,349 files, SHA-256 `176a3d97cae8199689b1973ebbc4c298b7d46cfca1b6d98f91693528314595fd`. Its verified artifact is `14707571675`, 18,214,533 bytes, SHA-256 `edabdaec23a5afd9443136f9c0a43c8ddcdda41e0b0351ac121f982f08b496d1`.

After those tests, `just fix` removed two last-use clones only in `codex-rs/hepta-intelligence-eval/src/structural_comparison_tests.rs`. The following `just fmt --base b8e8c6e82abc1479c573f61a5e17d28d581e6cad` exited 2 while constructing its scope: owning Rust workspace missing for `AUDIT/2026-10-20-agent-continuation/cell_p0/sources/2909/codex-rs/hepta-control-plane/Cargo.toml`. The formatter had not started. Binaries check was not reached. Maintenance is incomplete, the maintained postimage was not after-tested, and the final source is dirty only in that evaluation test file. Its two semantic-preserving clone suggestions are not a published or independently qualified candidate.

Staged episodic, startup, training, Windows Git process, and original Windows owners passes are retained as separate scoped receipts in `current-ci-final-summary.json`. Episodic `just fix` is not strict Clippy: rejected automatic edits were rolled back and the original seven warnings remained. AppContainer mechanism failed; ACL observation was cancelled with no established actor/cause. Other Windows Core/network positive behavior also remains blocked by elevated admission, with a separate CLI-stream timeout recorded.

All of these facts bind to **original `6cb` / tree `08f5` only**. The 2831 and 68 successes, source inventories, and all other original-head results do not qualify the parent's unpublished candidate. No CI rerun, original native-owner replay, remote write, HIA mutation, or read/implementation of the stopped C2D patch occurred in this audit. Current Windows refusal call chains do not establish direct dependence on that unread patch; no semantic nonoverlap claim is made.

Primary records: [all checks](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6799/checks), [daemon native](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44898577429/job/136829413045), [Architecture](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44898577503/job/136829413505), [B4 / repo checks](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44898577538/job/136829982050), [original Windows](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44898577556).
