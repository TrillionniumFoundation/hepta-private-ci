# Real two-slot MemoryCell evolution experiment

This retains the complete V3 experiment: actual Head and Router tensors,
source-group-separated data, encoded features, operation snapshots, and every
evaluated prediction. Authority remains `DENY_ALL`, mode `SHADOW_ONLY`.

## Result

The precommitted split does **not** establish a consistent advantage over static
continuation at the matched budget. It raises accuracy in July and the small
publisher holdout, but lowers August accuracy in **all three seeds**. The pooled
single Head also has higher accuracy in both ordinary evaluation windows.

Each entry is mean accuracy / mean NLL across seeds 7, 17 and 29:

| Historical evaluation | Unchanged parent | Static continuation | Split | Pooled single Head |
| --- | --- | --- | --- | --- |
| July ordinary, 128 stories | .794271 / .633496 | .778646 / .593102 | .796875 / .587818 | .812500 / .829920 |
| August ordinary, 96 stories | .791667 / .654869 | .802083 / .613377 | .781250 / .622808 | .809028 / .843383 |
| July publisher holdout, 48 stories | .819444 / .432718 | .826389 / .511325 | .861111 / .456530 | .840278 / .828440 |

NLL and accuracy need not rank models identically. The report retains both,
per-seed results and 2,000 paired story-bootstrap intervals. Intervals are
descriptive, without multiplicity correction; 48 OOD stories provide limited
precision. No winner or next hyperparameter is selected from these outcomes.

## Precommitted source separation

The source is [Gasparetti's UCI News Aggregator](https://doi.org/10.24432/C5F61C),
CC BY 4.0, archive SHA-256
`1f5f08691f0ce576cb0b5cfdbcb8c55e0ec14dda8f3e07933da72c500338845a`.
All 768 story groups and canonical titles from `news-cohorts-v2` are excluded.
One earliest record per story and one canonical title are retained before fixed
hash assignment. Class balancing uses source labels, never model outcomes.

| Role | Month | Separate stories |
| --- | --- | --- |
| Parent Head A / B / Router training | March 2014 | 96 / 96 / 64 |
| Parent Head / Router calibration | April 2014 | 64 / 64 |
| Evolution replay A / B / Router training | May 2014 | 96 / 96 / 64 |
| Evolution Head / Router / merge calibration | June 2014 | 64 / 64 / 64 |
| Evaluation | July / August / July publisher holdout | 128 / 96 / 48 |

The 1,104 new stories are disjoint across these roles. The original V1 proposal
failed on source availability before loading an Encoder or scoring any example:
August had only 26 ordinary and 6 OOD medical stories after exclusion. V2 fixed
the table above using those counts; July had 14 OOD medical stories. The failed
plan, exact source and error are retained in `history/`. There was no model
quality-based resampling. These remain historical 2014 examples from one source;
foundation-pretraining exposure is unknown and no prospective traffic was used.

## What actually executed and what was matched

The pinned Granite97m revision is
`835ad14087e140460703cf0fae09f97d469d65c2`; checkpoint inventory SHA-256 is
`08bdb7bb7eefb051ac74924787354a3638ba8a0e6fe6ffdd96ae57d6f1402db3`.
The frozen Encoder contains 97,441,152 actual loaded parameters and 389,764,864
resident tensor bytes. Its before/after hashes agree. All arms and seeds share
one encoding; `features.npz` preserves the actual features. This candidate
differs from the earlier EG2 routing experiment, so scores are not comparable
across those experiments.

Both primary arms use the same two replay partitions and source-separated
Router data. Split warm-starts two private children from preselected Head A and
replaces the two-slot roster. Static continuation retains both IDs and
warm-starts each from its own parent. Both train gated private Heads for 100 SGD
steps at 0.1 and a fresh hidden-width-16 Router for 200 steps at 0.1. No Encoder
parameters change. The split trigger and partitions are explicit caller inputs.

| Resource per primary arm, per seed | Exact matched value |
| --- | ---: |
| Active Cell slots | 2 |
| Active parameter/buffer storage, including Router | 86,368 bytes |
| Head plus Router parameter × example × update count | 175,379,200 |
| Router example × update count | 12,800 |
| SGD optimizer state | 0 bytes |
| Head/example forwards during fitting, calibration and internal reporting | 21,248 |
| Independently observed Head module invocations for that work | 232 |
| Selected Heads per inference example | 1 |

The update count is a transparent work proxy, not measured hardware FLOPs.
Actual forward observation agrees with the operation receipts. The parent
preparation and pooled baseline have separate recorded work. The pooled Head
uses all 512 March+May training and 256 April+June calibration records, 200 steps,
one resident Head and no Router; its training budget is not matched to either
evolution arm. The unchanged-parent arm also has no evolution update cost.

The resident cap applies to one active snapshot, not all experimental arms or
archived rollback versions held by the process. Shared Encoder, allocator,
backend workspace, process peak RSS, latency and energy are outside the match.
Transition and gradient reservations are separated from measured/directly
counted usage. Saved snapshots adopt reloaded NPZ weights and reject residual
gradients; stale training gradients are not silently included in an inference
snapshot. Observed timings are not service benchmarks.

## Executed structural and withdrawal checks

For every seed, merge uses actual predictions from both split teachers on 192
replay rows: 384 teacher/example calls, followed by real student optimization.
Retiring `child_b` leaves exactly zero calls to it and zero Router forwards.
Rollback reloads the original parent files, advances graph generation to 4, and
reproduces the original probabilities exactly. These operations and ordinary
predictions also survive independent retained-digest artifact reloads.

Four actual source withdrawals cover the retired parent B's training data,
parent Router calibration, child training and child Router training. They cause
18 whole-snapshot refusals per seed with zero Head calls. Descendants inherit
all ancestor training, calibration, teacher and Router dependencies. A withdrawn
child-only source permits recovery of a clean parent at a fresh generation;
withdrawn ancestor sources cannot be bypassed by filtering individual Cells.

V3 fixes a resource lifecycle issue found after V2: old training wrappers left
gradient buffers attached to frozen modules. Adoption now reloads persisted
weights, and inference rejects gradients. All **55 NPZ files**, including the
feature cache, and the **complete prediction ledger** are byte-identical between
V2 and V3. `history/v2-to-v3-parity.json.gz` retains the independent file-by-file
comparison, both plan identities and the historical snapshot source. No learned
configuration or prediction changed. The broad code inventory also records an
unimported concurrent LoCoMo scoring-file change; the parity report identifies
the actual statically reachable dependency subset separately.

## Evidence and reproduction

`inventory.json` maps every one of the 139 original V3 files, plus history and
acquisition evidence, to its retained path, original/stored length and SHA-256.
Large JSON and historical Python sources use deterministic gzip. NPZ bytes stay
unchanged. Restore each inventory entry at `source_path` in a fresh directory,
decompress entries marked `gzip`, and verify **both** stored and original hashes
before using the snapshot loader with the independently retained manifest hash.
The complete predictions are in `prediction_ledger.json.gz`; `report.json.gz`
retains every actual operation and budget receipt. The ledger has 69 batches,
7,488 observed Head/example calls and 45 Router forwards across post-training
evaluation, reload, mechanism checks and recovery, separately from training.

With the pinned environment and source/model terms already accepted, reproduce:

```sh
OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1 \
python qa/stem-bakeoff/real_evolution_probe.py \
  --snapshot /path/to/pinned-granite97m \
  --inventory-sha256 08bdb7bb7eefb051ac74924787354a3638ba8a0e6fe6ffdd96ae57d6f1402db3 \
  --cohorts /path/to/news-cohorts-v2 --archive /path/to/news-aggregator.zip \
  --output /path/to/new-run --operator-accepted-terms --threads 4 --batch-size 16
```

This is executable offline topology and learning evidence. It does not close
automatic split-policy selection, durable memory-task benefit, authenticated
production source withdrawal, native deployment, prospective acceptance,
cross-node execution or slow shared-Encoder distillation. Standalone descendant
Head exports cannot substitute their current train/calibration sources for the
complete evolution snapshot dependency closure.
