# Learn the return of the retained frontier, not a root restart

Parent: `d1b8a58ee9a189f7029b6897474260525f62059e`, PR #1546.
No default policy, Reader, native NDU API, Riccati backend or existing search
implementation changes. A new controller is trained for resumption explicitly;
the 324-parameter restart controller is not reused with different semantics.

## Completed parent, read directly from hosted job logs

Run **38205461390**, job **114667849537**, generating source `d1b8a58e...`,
completed successfully. Full MemoryCell regression: **1165 passed, two skipped,
1167 total**. Scoped static checks passed. The original budget trial recorded
**1536/1536 episodes, zero execution failures** and retained its negative result.
All **384** split/uninterrupted comparisons matched proofs, generated successors
and session counters. These are repeated executions on the existing tasks.

| Next 48 tasks | Restart heuristic proofs / successors | Resume proofs / successors |
| --- | ---: | ---: |
| Budget 256 | 30 / 8887 | 34 / 7355 |
| Budget 1024 | 39 / 15612 | 41 / 13105 |

Resumption restores direct search, not a learned improvement. Artifact 11728160554
is 463459 bytes; upload digest reported by GitHub is
`ef69d91f2ed74eb9f61d67d343f1ff0a35e8e54f4e9445896e46ea9d95a6c6fb`.
It was not unpacked locally in this stage; no new local manifest audit is claimed.

## Small coherent next control problem

Each episode is an unchanged heuristic `SearchSession`. After its quarter-budget
probe, the controller chooses STOP or RESUME the SAME queue to the full cumulative
allowance. No re-rooting, reordering, policy switching or evaluation-time learning.
An already found exact proof ends the episode. Exhausted queues need no decision.

The input has 32 numbers: 12 existing question/goal features, three budget features,
five bounded queue/visited/pending-batch descriptors, and 12 features for the top
queued arithmetic state. Reading it never advances the pending generator. This
is a lossy summary and is NOT claimed to be a sufficient Markov state.

A 32->16->2 network has **562 parameters**. Outputs estimate verified success and
additional-successor fraction for this fixed resumed policy. The three training
conditions share initialization, architecture, targets and 200 optimizer steps:
full frontier; frontier components zeroed while retaining question/budget; and
joint success/cost targets shuffled across contexts. No post-result tuning.

Only the original twelve training multisets supply labels. Each of the two
budgets gets a real probe and, after probe failure, a real continuation of that
same in-memory cursor. Target cost is FINAL minus PROBE generated successors,
normalized by remaining budget. Cumulative snapshots are never summed twice.
Successful probes and exhausted searches remain in the census without fabricated
continuation targets. The at-most-24 training contexts are highly correlated and
not a large independent dataset. No search-reachability oracle supplies labels.

Training events are appended, flushed and fsynced before/after each advance.
The caller owns the ledger and writes partial records in a finally block; errors
and interrupts propagate rather than becoming negative labels. Filesystem failure
can still prevent persistence. An in-flight failure leaves explicitly incomplete
work; it cannot be reported as a free operation.

## Fixed experiment and acceptance

Seven arms: direct full search, fixed resume, probe-only stop, full frontier head,
root/budget-only head, shuffled targets, and the SAME full head ignoring cost.
The objective remains verified proof minus 0.0001 times ALL generated successors.
The sunk probe cost is absent only from the continuation argmax, not the report.
This counter price is not wall time/FLOPs; journaling and controller costs are
measured separately within episode time. No equal actual-compute claim is made.

Use 96 previously evaluated multisets for diagnosis and the next 48 fixed original
hash-ordered multisets (positions 108:156), disjoint from training and prior task
IDs. Two budgets and seven arms schedule **2016 episodes**. Intermediate arithmetic
states may overlap; this is not independent-domain or language evidence.

Heads are saved/reloaded/frozen before any evaluation. Decisions are persisted
before resumed outcomes. After ALL predictions are sealed, fixed-resume controls
provide Brier/cost targets for both chosen and unchosen continuations, and the
realized STOP/RESUME envelope is computed. Neither these controls nor labels feed
runtime choice. Missing/failed positions retain the full denominator and declared
utility intervals, not confidence intervals. Known cap violations are rejected.

Primary comparison is next-48 / 1024. A candidate must lose NO direct proof and
strictly improve the declared utility over direct, fixed-resume, root-only,
shuffled and cost-blind controls. A pass would still require new confirmation.
This stop-only controller CANNOT create proofs that direct search misses. Its
possible gain is avoiding unsuccessful continuation while retaining solved tasks;
more solved tasks require changing the action set, not a stronger stop predictor.

## Execution status and reproduction

Sixteen new tests are submitted: real-cursor target accounting, no-oracle reads,
control matching, frozen-model schemas, persistent failure handling, sealed full
runner, and paired direct/resume proof invariants. No new tests or performance
results are reported passed before execution. Local container and Python minimal
probes returned service errors. No local compilation, formatting or tensor/file
parity success is claimed. Hosted full regressions and scoped static gates remain.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_frontier_trial.py \
  /path/to/pinned-11724608246.zip /new/frontier-output
```

The existing budget workflow retains historical budget and resume experiments,
then executes this stage without another pretrained Encoder/Reader download.
General nonlinear NDU, FBSDE reasoning, calibrated stopping, multimodal transfer
and production acceptance remain unestablished. Existing language negative
results and Riccati's storage/latency tradeoff are not superseded here.
