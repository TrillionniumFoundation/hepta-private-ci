# Validation record: Cell differentiation

## Disposition

**DRAFT / NOT QUALIFIED FOR PRODUCTION ADOPTION.**

Implementation and regression sources have been saved and reviewed. Native
compilation, native tests, formatting, lint, Python tests and the complete CPU
study do not have a confirmed successful execution in this session. No study
quality, speed, cost, throughput or RSI result is claimed.

This record separates authored checks, source review, attempted commands and
observed execution. A valid HOLD is an experiment result only after the actual
experiment has run. No HOLD or success result is invented here.

## Exact source identity

| Item | Identity |
| --- | --- |
| Development base | `732e934ba496d90fbe042b8d41d479ef901643e5` |
| Complete code/workflow checkpoint, before these documents | `cdf60c39d01e4aa623a8401df491c024aad6d6b5` |
| Checkpoint Git tree | `92cf98a944d64a0d519e6eb1c935146e592628cf` |
| Final delivery | The PR head containing this record and README.md |
| Native toolchain | Unchanged repository-pinned codex-rs/rust-toolchain.toml |
| Dependency changes | None in Rust; isolated CPU workflow pins NumPy 2.3.5 |

The final documentation commit adds only README.md and this record to the
checkpoint. Native and Python runs must record the actual checked-out commit
and tree. The workflow compares Git HEAD with its exact source SHA and retains
source.txt; it does not substitute a PR merge ref or a previous passing run.

The source was developed against main. The neuron, plasticity and shared-types
subtrees were compared with integration candidate
`07378034e060f23259bc99c7367f12b1284140f3` and were identical; no unrelated
integration commits were imported. Exact subtree identities are in README.md.

## Changes and authored regression coverage

| Surface | Implemented source and authored checks | Execution |
| --- | --- | --- |
| Seven functional roles and two separate deterministic support classes | Schema/behavior-bound capability identity; mutation and missing-schema controls | PENDING |
| Four population measurements | Alias rejection, shared-base reuse, scoped state, exact generation/version, independent quotas, retained/quarantined state and overflow | PENDING |
| Persistent demand | Adjacent windows, task/source uniqueness, independent task panels, partition OR error trigger, frozen parent/diagnosis/protocol | PENDING |
| Frozen study | Parent/child compatibility, separate nursery, six comparator arms, all requests, old-task panels, complete metering and net benefit | PENDING |
| Independent evidence | Principal/key/credential/controller collision checks; global demand/training/outcome/cost/migration source deduplication | PENDING |
| Migration rehearsal | Parent floor and candidate's own old-task improvements, exact rollback, no old writers or unresolved/replayed effects | PENDING |
| Existing topology owner | Full parent/artifact/generation/window/actor/evidence/single-split binding, no-change candidate, DENY_ALL, independent acceptance required | PENDING |
| CPU learning study | Actual FP64 gradient descent, fixed seeds and splits, six arms, replayable model/data evidence, complete cost-stage populations | PENDING |
| CPU failure behavior | Failed learner, failed incumbent and unavailable prediction kernel preserve planned arms and request denominators; missing costs remain unknown | PENDING |

There are **30 authored Rust tests**: 2 role tests, 9 population tests, 7 demand
tests and 12 study/topology tests. There are **24 authored Python behavioral
tests**. These are test definitions, not passed-test counts. The native
population fixture's 2 / 3 / 4 / 2 counters are an asserted example, not a
production census or executed result.

The sources include adversarial checks for omitted comparator arms, altered
denominators, same-phase cost-event deletion, fabricated predictions and demand
flags, source-map forgery, holdout leakage, post-freeze policy changes, and
migration flags that disagree with the retained observations.

## Source review performed

Independent source review checked the final module declarations and exports,
cross-module visibility, bounded score/cost arithmetic, fixtures and expected
negative cases. It identified and led to corrections for:

- Shared identity/control provenance masquerading as independent actors.
- Demand/training/cost evidence reused as supposedly independent outcomes.
- Old-task migration losing a candidate's improvement while still exceeding
  the parent's lower baseline.
- Topology requests rebound to another parent, generation, actor or study.
- Cost reports dropping a named expensive stage while preserving a phase total.
- Failure paths discarding a learner, entire trial or original requests.
- Unnecessary prediction replay after every request has already failed.
- Incomplete pre/post-migration records being equal and incorrectly reported
  as verified migration behavior.

Source review does not establish Rust type checking, borrow checking, Python
execution, numerical convergence, reproducibility or CI success. Manual source
formatting, where applied, is not a cargo fmt result.

## Actual local execution observations

The initially available scratch runtime had Python 3.12.14 and NumPy 2.3.5.
It did not have just, rustc, cargo, rustfmt or cargo-nextest available.

The following repository entry points were attempted in sequence and each
returned exit status 127 because just was unavailable:

```text
just test -p codex-hepta-neuron
just fmt
just fix -p codex-hepta-neuron
```

No Rust test, formatter or Clippy process ran successfully through those
commands. These attempts are tool-availability failures, not native test
failures or passes.

An earlier version of the Python study was started before the executor
disconnected. Its completion output and exit status were not recovered, and
the sources subsequently changed. That start supplies no valid evidence for
the final source. No study.json, metrics or passing unittest output is asserted.

The managed execution environment subsequently became unavailable. A later
attempt to invoke `python3 --version` failed before command execution with
"No usable execution environment is available." Source recovery, review and
publication then used the authorized repository connector. Those operations
do not execute the Python or Rust programs.

## GitHub execution observations

The original draft PR was #4886. On its earlier source
`228b4d72e5434f4b861f334c99c28022f98dcce2`, qualification run
[42061422947](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42061422947)
was observed as pending, with an empty latest-attempt jobs list.
That observation is not a result for the complete source checkpoint.

The final workflow provides two separate jobs:

1. Native: repository just/nextest test entry point for neuron and plasticity,
   scoped Clippy, cargo fmt check, clean-diff checks and raw evidence artifacts.
2. CPU reference: isolated pinned NumPy runtime, the full behavioral test suite,
   all preregistered trials, serialized-report audit and raw evidence artifacts.

Qualification results must be inspected on the final PR head. This document
contains no completed exact-head CI result. A queued, pending or running
workflow is not a pass. The final PR remains Draft while the required evidence
is missing.

## Remaining qualification work

- Compile and test both Rust packages with the repository-pinned toolchain;
  run the scoped formatter and lint checks, and fix any findings.
- Execute all Python behavioral controls and the complete frozen study.
  Preserve every requested seed, comparator and request, including failures.
- Retain the actual source SHA/tree, source/data/plan digests, models, raw
  observations, stage costs and post-serialization audit results.
- Assess any measured benefit against all controls. A candidate that beats
  the shared parent but not fixed experts or the expanded monolith remains
  HOLD. Do not retune the registered policy after seeing test results.
- Integrate authenticated runtime observations through existing owners and
  qualify real artifact publication, writer handoff, state/effect reconciliation,
  canary, rollback and adoption before claiming live differentiation.
- Establish separate evidence before claiming seven functioning neural roles,
  an optimal cell-type count, autonomous development, or RSI.

The CPU harness is a synthetic research experiment and uses a different
numeric decision representation from the Rust policy. It does not execute the
native gate or prove cross-language acceptance parity. The exported bridge is
proposal-only and has no production caller added by this change.

## Staged source commits

| Stage | Commit | Scope |
| --- | --- | --- |
| 1 | `6e70292bc57f41f82abaf6e21178e307b087b324` | Functional roles and capability contracts |
| native-ci | `5b2e9a6ac0d43f409b9500df09a38d8a25cfee68` | Exact-source native workflow |
| 2 | `f59b58f5c7afc8a740c545c8cd8ca3954d79f49a` | Four population measurements |
| 3 | `0f1b17169cf0ff1cb3cb9663830d1260c9fd4fba` | Frozen differentiation plan and types |
| 4 | `0d7853aeac2bf911abfb23285be228d935150228` | Persistent demand and controls |
| 5 | `ef53f6297ef9b3f799f4f7efd77e17ec78703cda` | Complete study observation schema |
| 6 | `228b4d72e5434f4b861f334c99c28022f98dcce2` | Study gate and existing topology bridge |
| 7 | `23aaecab5e86508b1d32644e8300136810311bd1` | Adversarial native regressions |
| 8 | `6c8e14d18d4971666ff6332e11181f644c93eb1e` | Frozen CPU data, learners and cost contracts |
| 9 | `d6f5292ab63a6bcafef63d4de182c918bb0577af` | Evidence audit and research decision |
| 10 | `f83e9323d9f402efa9590b73b4ab402b9fb5af77` | Complete runner, controls and CPU CI |
| 11 | `0085f7c76eb8d27cb95f6812cc649cde401df4f5` | Kernel-failure and unknown-migration correction |
| 12 | `cdf60c39d01e4aa623a8401df491c024aad6d6b5` | Whitespace-only source formatting |

Each stage is reviewable without importing unrelated integration history.
No dependency lockfile, public-admission default, runtime authority grant or
existing lifecycle owner is replaced by this change.
