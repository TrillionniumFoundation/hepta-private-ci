# Fixed-head CI follow-up

This is a read-only diagnosis of existing runs. No CI rerun or source mutation was used to obtain it.
Source equality identifies unchanged implicated code; it is not a new successful baseline run.
Later steps skipped after a failure remain unverified. Overall CI is not green.

## Complete-state proposal: PR 6845

Head `9f6a1891deba84fb4448205d3cad4cd25114f567` changes only the two recovery files
and their exports. Its five new recovery tests all pass in the actual native-owner job.

| Job | Observed failure |
|---|---|
| [MemoryCell training-owner](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862883422/job/136719989375) | Missing `MultiAgentMode` in `thread_summary.rs:190`; also invalid `Timestamp` to `SystemTime` conversion in `rollout.rs:316` |
| [MemoryCell native-owner](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862883422/job/136724321493) | Eight existing process-helper tests lack required helper metadata; 408/416 pass, including all five new recovery tests |
| [Neuroscience helper](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862882383/job/136719983563) | Downloaded compiler artifact confirms the same `MultiAgentMode` error |
| [Shared Cell helper](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862882433/job/136719984057) | Downloaded compiler artifact confirms the same `MultiAgentMode` error |
| [Neuron Gated helper](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862882484/job/136719984282) | Downloaded compiler artifact confirms the same `MultiAgentMode` error |
| [Rust UI source](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862882246/job/136719983411) and [merge](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862882246/job/136719983275) | Dependency-closure test detects a missing `codex-rs/utils/windows-private-state/**` workflow trigger |

The implicated app-server files, old helper tests, UI regression test and UI workflow all have
identical Git blob IDs at base `0cee57ca617e0324e2df8e9447a2c075a6c76952` and this head.
The neuroscience merge checkout has the same Git tree as the head. These are directly verified
comparisons, not inferences from similarly named failures.

## Research-receipt proposal: PR 6844

Head `02749c7810c19abbc149ba2cda88488020c28b71` has the fixed baseline as its sole parent
and adds only three learning-artifacts files/exports. Source and merge lanes both pass the five new
receipt tests, build, strict Clippy, owner regression (165 passed, 1 skipped), cross-crate and reload checks.

| Job | Observed failure and limitation |
|---|---|
| [Learning source](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877925/job/136719971525) and [merge](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877925/job/136719971315) | Existing app-server import and Timestamp/SystemTime conversion errors block cognitive-read |
| [Architecture](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877032/job/136719967206) | Existing neuron Clippy warnings become errors; the merge lane's native step is skipped |
| [Daemon](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862876949/job/136719966423) | 1,214 source-closure Python checks produce 83 failures and 6 errors before native compilation |
| [Codespell](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136719967688) | Three `Fo` findings in two unchanged historical evidence JSON files |
| [Helper shard 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136721276811) | Compiler stderr confirms `MultiAgentMode`; other shards fail the same wrapper stage but their compiler stderr was not individually inspected |
| [Contract gate](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136721276829) | Existing qualification records contain stale exact workflow references |
| [NDU native](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136721277035) | 629 passed, 3 failed, 2 skipped: actual holdout error-contract assertions fail |
| [Learning operator source](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136721277054) and [merge](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862877129/job/136721277086) | Rust 1.95 is rejected by locked rama dependencies requiring 1.96 |

The three NDU assertions are retained as substantive failures, not relabeled environment noise:
`Err(Store(Indeterminate))` versus `Err(Indeterminate)` at physical test line 138;
`Some(Holdout(Store(Indeterminate)))` versus `Some(Holdout(Poisoned))` at release test line 251;
and the same actual wrapper versus `Some(Holdout(Indeterminate))` at release test line 278.
All implicated source/configuration files are outside this exact three-file change. That fact and the
passing direct HCSN tests do not establish whole-repository regression freedom.

## Preserved evidence

`ci-followup-v1.tar.gz` preserves the source comparisons, job excerpts, downloaded artifacts,
extracted compiler logs and separate receipt/state summaries. Its hash and member count are bound
in `ARTIFACTS.json`; `verify_evidence.py` also checks this supplement.
The evidence-only PR's newly triggered workflows may still be running at delivery. Scoped local
tests, successful individual CI tests and failed or skipped workflow lanes are reported separately.
