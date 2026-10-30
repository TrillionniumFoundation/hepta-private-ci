# V11 executable tasks and structural evolution

## Result

The typed network runs real compiler-guided repair episodes, but it does not
outperform the strong controls on this task family. Every compared policy,
including BM25, dense nearest neighbors, the compiler rule, and the single MLP,
solves every known held task and abstains on every unsupported held task.
Removing either learned semantic or predictive contribution also leaves success
unchanged. This is a ceiling result, not evidence that the components are needed.

All three split candidates are rejected against the incumbent, continued parent,
fixed experts, and larger MLP. Independent held confirmation also fails. The
implemented gate therefore preserves the incumbent. The wake trials restore an
artificial sleeping shadow; their admission is not a benefit over the original
awake network or evidence for autonomous structural improvement.

Complete evidence is in [tasks-v11](evidence/archives/tasks-v11/README.md),
[task-cost-replay-v11](evidence/archives/task-cost-replay-v11/README.md), and
[structure-v11](evidence/archives/structure-v11/README.md).

## What the task actually measures

[tasks.py](tasks.py) creates authored Rust programs with four repair families:
borrowing a String as `&str`, preserving a moved String by cloning, converting
`u32` to `u64`, and extracting `Option<u32>` with the registered default. An
unsupported family contains an unresolved function. The code uses opaque random
names and independently sampled values. No family label, case ID, gold key, or
expected output enters the model's observation.

Actual Rust 1.95 compilation supplies diagnostic feedback. A successful repair
must compile, run, and produce the independently specified exact stdout. The
executor exposes the same four bounded transformations and a maximum of two
patches/three compiler observations to every policy. An unsupported task succeeds
only through abstention, and its rate is reported separately from known success.

The training set contains 48 single-defect examples and four unsupported examples.
For each training example, all four candidate transformations are compiled and
executed where possible to derive outcome supervision. Calibration has 16 known
and four unsupported cases. Held partitions have 16 single-defect cases plus four
unsupported cases, and 32 two-defect compositions plus four unsupported cases.
Training/calibration/held source identities are disjoint.

The three seeds are 81231, 91243 and 101267. There are 144 known held tasks and
24 unsupported held tasks per policy across those seeds. These are different
authored source instances of a small fixed grammar. They are **not historical
production incidents**, a broad repository-repair benchmark, or independent
evidence of general programming competence.

## Typed components and shared information

| Component | Executed role | Qualification limit |
| --- | --- | --- |
| Event cell | Bounded per-episode source history and durable SQLite decision events | No cross-episode learned episodic retrieval is established |
| Semantic cell | A learned MLP over frozen source/diagnostic embeddings | Five action/abstention outputs on this grammar |
| Skill cell | Shared registered source transformations followed by the actual compiler/executable | The same tool registry is available to every control |
| Predictive cell | A learned four-output model trained on actual per-action outcomes | Useful held forecasting is not established by network success |
| Routing cell | A separately learned MLP consumes source features and semantic/predictive outputs | Its extra value is not established by these ceiling outcomes |

All policies receive the current source and compiler observation. The common
serialized text includes the first diagnostic's code, message, full rendered
diagnostic, and the complete source. BM25 consumes that complete text. The neural
encoder uses a declared 256-token truncation; all embedding-based arms share the
same frozen FP32 encoder and truncation. The compiler rule uses the same observed
diagnostic directly. Different architectures can make different use of the public
input; no policy receives a hidden correct answer or additional tool opportunity.

The single-model arms train jointly on five action labels and four observed
outcome labels. The typed network splits 600 minibatches into 200 semantic,
200 predictive and 200 routing updates. All learned systems consume 9,600 total
sample presentations with batch 16. The schedules and source lists are retained.
These are equal presentation and resource-ceiling comparisons, not equal FLOPs.

| Learned system | Mutable FP32 payload bytes | Total presentations per seed |
| --- | ---: | ---: |
| Single MLP, hidden 96, joint head | 151,332 | 9,600 |
| Larger single MLP, hidden 128 | 201,764 | 9,600 |
| Typed semantic + predictive + routing | 200,760 | 9,600 |

The typed total comprises 99,860 semantic, 49,808 predictive, and 51,092 routing
bytes. Saved checkpoint containers, source examples, feature banks, event SQLite,
compiler observations and the shared encoder are additional. Per-file actual
sizes are retained in each seed's `COSTS.json` and the archive inventories.

This is an executable Python research composition. It is not a claim that all
five types have been admitted through the native Rust control-wire or that the
Transformer adapter has replaced the native V10 numerical operator.

## Task outcomes

Each row aggregates the three task seeds; underlying per-seed denominators remain
available. The same cases are shared across policies, so these are paired results.

| Policy | Known single / 48 | Known two-defect / 96 | Correct unsupported abstentions / 24 |
| --- | ---: | ---: | ---: |
| Compiler rule | 48 | 96 | 24 |
| BM25 retrieval | 48 | 96 | 24 |
| Dense nearest-neighbor retrieval | 48 | 96 | 24 |
| Single model | 48 | 96 | 24 |
| Capacity control | 48 | 96 | 24 |
| Fixed typed network | 48 | 96 | 24 |
| Typed network, semantic contribution disabled | 48 | 96 | 24 |
| Typed network, predictive contribution disabled | 48 | 96 | 24 |

The task calibrator maximizes balanced known/unsupported classification accuracy
over a fixed threshold grid. The other studies have different gates: content
requires zero accepted unknown/ambiguous calibration requests while maximizing
correct known accepts; maintenance additionally requires zero accepted wrong-known
calibration answers. None of these finite calibration conditions is a guarantee
about held requests. Ablations preserve the typed
network's selected threshold. Their inherited `selected.balanced_accuracy` field
belongs to the original typed calibration and is not an ablation calibration
score. No held task selects a new threshold or training budget.

Across all arms and task seeds, the original run makes 4,104 actual uncached
compiler invocations, including training supervision, calibration observations
and held episodes. Each seed's two held partitions use 1,088 actual calls across
the eight arms. All original traces and compiler outputs are retained.

## Corrected telemetry and independent reader replay

An independent review found two derived counter errors in the original frozen
runner: `patch_attempts` counted abstention decisions, and `tool_calls` used a
formula that could overcount an attempted transformation that did not change
source. Original success outcomes and the measured aggregate
`actual_compiler_calls` were not affected. The original files were retained,
including the exact executed sources in `source-snapshot/`.

[task_audit.py](task_audit.py) reconstructs every source transition and recomputes
the counters. It verifies the reconstructed count against the independently
measured original aggregate compiler count. The corrected implementation also
records actual compiler calls, cache hits, observation requests, and whether a
patch was applied for each task. A real-compiler regression test covers a no-op
repair attempt that must not invent another compiler invocation.

The original feature cache was shared between arms in a fixed order, so its
end-to-end timings cannot be used as independent cold-start comparisons. The
separate audit loads the exact saved model checkpoints in a fresh process,
preserves the original thresholds, and clears the feature cache independently
for every seed/phase/arm. It verifies every reconstructed action and every neural
probability against the original trace (`atol=rtol=1e-5`). All comparisons pass.
There is no fitting, recalibration or replacement of the original outcome labels.

The following are three-seed mean decision costs on the two-defect partition.
They include the encoder when needed, exclude compiler execution, and keep the
authenticated base resident. Input file/audit bookkeeping is timed separately.

| Policy | Wall ms per decision | CPU ms per decision |
| --- | ---: | ---: |
| Compiler rule | 0.0019 | 0.0018 |
| BM25 | 0.7504 | 0.8640 |
| Dense nearest neighbor | 114.98 | 228.32 |
| Single model | 116.99 | 231.61 |
| Capacity control | 115.59 | 226.29 |
| Typed network | 109.67 | 217.53 |

Small differences among neural arms are shared-host measurements, not a speedup
claim. Their costs are dominated by the same encoder. Each paired partition
encodes 68 distinct decision texts per embedding-based policy and retains
104,448 bytes of feature arrays. Shared model/tokenizer assets total 484,793,822
bytes. This audit's base load took 2.707 seconds and its process peak RSS was
913,448,960 bytes; RSS includes Python/Torch and all models used by the audit.
It is not the pure memory allocation of one deployed cell. Original uncached
compiler timing is retained separately and is not added to these measurements
to fabricate a newly observed end-to-end run.

## Structural experiment

[structure_experiment.py](structure_experiment.py) binds both training input
files by hash, checks row/label alignment, and freezes all executed sources.
Training comes only from the task experiment's training partition. New
validation two-defect sources are generated before selection; a different held
set is generated only after all validation decisions for that seed. The runner
checks source-set intersections and rechecks source/input hashes at completion.

The split uses two clusters learned from training embeddings, without labels.
The fixed-expert control uses precisely the same partition. Held routing uses
cosine similarity to training-feature centroids, not a gold address or source ID.

| Split comparison | Actual schedule | Mutable FP32 bytes |
| --- | --- | ---: |
| Parent before proposal | 300 × 16 | 99,860 |
| Split proposal | Parent 300 + two children 150 each | 199,720 |
| Continue parent | Parent 300 + continuation 300 | 99,860 |
| Fixed experts | Two experts 300 each | 199,720 |
| Larger MLP | 600 × 16 | 199,700 |

Every matched comparison therefore spends 9,600 cumulative training
presentations. Exact per-row frequencies and wall time can differ and are
recorded. The gate compares actual held-query routing and compiler-derived
outcomes, uses a paired normal lower bound with z=2.576, and requires a lower
net gain above 0.01 against the incumbent and all three matched controls.
The statistical interval is exploratory on a small authored grammar; there
is no population or multiple-comparison guarantee.

Prices are explicit research utility preferences: 0.01 success-rate units per
MiB of active weights, 0.002 per MiB of actual checkpoint storage, and 0.001 per
observed training/maintenance second amortized over 1,000 queries. They are not
monetary measurements. Latency price is zero because validation deliberately
replays identical observed compiler outputs and its timings are hot-cache
validation costs. Independent held compiler execution is uncached. The active
budget is two experts/250,000 mutable bytes; additional action training is
bounded by a cooperative 60-second deadline and transfers by 1,000,000 bytes.

The executor really trains split and merge shadows, saves and releases sleeping
models, reloads wakes, and serializes/reloads migration candidates. It records
leave-one-cell-out validation outcome changes as conditional cell credits.
These credits are not a learned long-horizon network allocator or Shapley values.

All three seeds show the same pattern:

| Action | Validation admissions / 3 | Interpretation |
| --- | ---: | --- |
| Split | 0 | No quality improvement; extra parameters/cost |
| Merge | 0 | Does not meet the declared minimum net-gain margin |
| Sleep | 0 | Outcome loss prevents admission |
| Wake | 3 | Restores an intentionally sleeping shadow; original awake network is still the comparison for structural benefit |
| Local checkpoint migration | 0 | No measured benefit over keeping the original model |

Every split candidate and every strong control also solves all 16 known held
two-defect tasks and rejects all four unsupported held tasks in each seed.
`HELD_CONFIRMATION.json` calculates the independent paired comparisons; zero
of three splits is confirmed. The selected live topology remains the parent.

The gate includes actual checkpoint file sizes, separately prices resident
weight bytes, and rejects incomplete storage accounting. Every failed or
accepted proposal remains in the durable decision ledger. Across the three
seeds, five proposals per seed retain 658,633 / 658,658 / 658,901 bytes of
action artifacts, receipts and SQLite, and consume 10.512 / 9.491 / 9.626 seconds
of measured structural/validation work. These are exploration costs in addition
to the external base, controls, input archive and final held evaluations. All
of those files have separate inventories. Rejected exploration is not erased
from a lifecycle-cost claim.

## Lineage and deployment limits

Split children inherit the entire trained parent, including every parent
training source. Their checkpoint metadata and fit receipts retain that complete
source set. The new route partition does **not** erase inherited dependencies.
These children cannot be published as independently clean-fit native owner
projections without a legitimate reconstruction procedure.

The structural study's migration is a same-process, same-host checkpoint round
trip. A separate same-host, two-process handoff functional run is documented in
[MIGRATION_REPORT.md](MIGRATION_REPORT.md); neither study measures cross-machine
networking or distributed availability. The native Rust lifecycle, Python
learned operators, replay study, and task network are separate implementation
and evaluation slices. Native test execution and its tested source identity
are reported independently; this report does not establish a native pass.
Complete production integration and any claim of a self-forming general memory
system remain unproven.

## Reproduction

Use the recorded Python environment in [requirements.txt](requirements.txt), the
authenticated encoder prepared by [prepare_encoder.py](prepare_encoder.py), and
the pinned Rust 1.95 compiler. Run each command with a new output directory:

```bash
python task_experiment.py --output /tmp/v11-tasks-new \
  --encoder /path/to/pinned-encoder --rustc /path/to/rustc-1.95
python structure_experiment.py --input /tmp/v11-tasks-new \
  --output /tmp/v11-structure-new --encoder /path/to/pinned-encoder \
  --rustc /path/to/rustc-1.95
```

To reproduce the historical original telemetry exactly, restore `tasks-v11` and
run its `source-snapshot/` rather than the corrected current counter code.
To reproduce the read-only audit, restore the original task package and its
complete source snapshot, then use the audit package's verified executed source:

```bash
python task_audit.py --input /path/to/restored/tasks-v11 \
  --output /tmp/v11-task-audit-new --encoder /path/to/pinned-encoder
```

The archive inventories bind exact source, weights, thresholds, schedules,
raw outcomes and corrections. Later report publication does not retroactively
convert a local pre-run freeze into a remote preregistration.
