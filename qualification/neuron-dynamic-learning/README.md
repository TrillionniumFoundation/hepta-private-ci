# Neuron dynamic Stem / Organ / Cell qualification

**Research / shadow only.** Nothing in this directory is a signed inference
receipt, durable model authorization, independent NDU result or production
rollout. The draft stacked PR depends on the distinct native shared-feature
proposal #1498. No weights, datasets, or real target host are bundled.

## P0 — physical Encoder (partial, no target-weight execution)

`offline_stem.py` loads *actual* local Hugging Face `AutoModel` weights from
an offline snapshot only after verifying **every file** against a complete
SHA-256 manifest and a 40-character model revision. Its allowlist is
`jhu-clsp/mmBERT-small` and `answerdotai/ModernBERT-base` (not Jina
remote-code models). It encodes the complete joint question/options/state,
rejects silent token/feature truncation, does **one physical forward** over
distinct compatible inputs, and fans out per-Cell Q24 results within the exact
Scope/Principal/Purpose/Generation/Epoch/input group.

`model_worker_stem_shadow.rs` is an **owner-private research bridge**: Rust
checks the script and manifest hashes, calls the reviewed local script with
stdin JSON, and revalidates every row, identity, Q24 value and exact Rust
content digest. It reports, but cannot cryptographically prove, the backend's
forward count and timing. It is not wired to normal production dispatch, nor
does it authorize any Cell use. It launches a subprocess per batch: this is
**not** the final long-lived/fused production Rust Encoder kernel.

Example (only after manually provisioning/reviewing a local model snapshot):

```sh
python3 qualification/neuron-dynamic-learning/offline_stem.py \
  --manifest /approved/local/manifest.json \
  --requests /approved/local/frozen_cell_requests.json
```

No automatic download, `trust_remote_code`, floating model revision, fake
fallback or unapproved wide feature projection is provided. Jina v5 must use
its distinct reviewed official `encode_query/encode_document` contract before
an equivalent bridge could be approved.

## P1 — true trainable input-dependent Cell Head (implemented in shadow)

`model_worker_dynamic_gate.rs` defines a checked, digest-sealed V3 Q24
low-rank hard-sigmoid gate. Its gate depends on the current input; it cannot
be absorbed into a fixed linear projection. All Cell state/weights remain
private and immutable after selected Worker load. The old V1 request lacks a
Cell principal, so it cannot invoke dynamic Heads; only the scope-fenced
owner-private V2 reference path can pass a Cell identity.

`cell_learning.py` performs real local NumPy gradient updates (not
placeholder predictions), creates exactly same-initialization frozen controls,
and exports Q24 Head tensors in the Rust field order. Exact Python/Rust
SHA-256 artifact and joint-input golden tests are pinned. The primary
preregistered Head tiers are **2K, 8K, 16K**; 64K/262K remain capacity
ablations in the separate original research harness. SGD training output is
not a signed CAS state commit. Grouped future data and real production
no-change predictions are mandatory for any future effect claim.

## P2 — four Organ transfer ablations (shadow)

`organ_transfer.py` fits a frozen Organ direction from earlier source-task
labels, then gives each independent Cell the same initialization, Head
capacity, update count and temporal target split *with/without* that Organ.
Roles: MemoryRead, Predictor, Decision, Value. The source / train / future
groups are disjoint; future labels cannot enter Organ fitting or Head updates.
Negative transfer and transformation cost are explicitly reported. Synthetic
unit tests **do not** qualify positive future utility.

## P3 — production boundary (DENY ALL, incomplete)

Draft native snapshots now bind Scope as well as Principal, Purpose,
Generation, Authority Epoch, model/tokenizer/normalizer/quantization and
complete input digest. Cross-Scope aliases are rejected. Cache hashes and
unsigned worker observations **never** grant final-use. Outstanding before
any production activation:

* independently signed Artifact CAS load and Head generation migration
* authenticated final-use and effective revocation revalidation
* independently observed signed feature/execution receipts and NDU selection
* durable WAL/checkpoint, restart, fault cuts and CNS generation cutover

These owners exist elsewhere in Hepta; this PR does not silently replace
them or claim that the full loop is integrated.

## P4 — bounded numerical scale probe (not end-to-end)

`scale_probe.py` measures actual CPU *NumPy Head operations* across
64/256/1024/4096 logical Cells × 5/25/100% active × 0/50/90% repeated
synthetic features. It reports observed process RSS, p50/p95/p99,
Head throughput and exact logical tensor bytes. Physical Encoder,
native microbatch, real request queue, WAL/recovery, target CPU/GPU and
cold-wake/full-resident comparison remain **UNMEASURED**.

```sh
python3 -m pip install 'numpy==2.2.6'
python3 -m unittest discover -v -s qualification/neuron-dynamic-learning -p 'test_*.py'
python3 qualification/neuron-dynamic-learning/scale_probe.py --full
```

## External real-pretrained mmBERT evidence (not P0 acceptance)

A separate research-only execution on
[GitHub Actions run 38423706608](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423706608)
completed on `research/shared-stem-six-execution-20261013` source
`d1511eaf9f2af927a8da03247531d9ac41c197ea`, not on this branch.
Its retained public research artifact gives exact model revision
`jhu-clsp/mmBERT-small@abc32620dd4f6ab06f5fbe905dc25f310618e09f`,
a verified downloaded weight source digest, and CPU PyTorch 2.10.0
inference over AG News. The archived raw
`hepta-public-study/execution/report.json` SHA-256 is
`d9858cf9f922791067d97510eb1bf41964cd856c47246d1ceaa7d4a09a0c706f`.

Actual observed *research* counts:
- 128 encoding requests through 16 actual Transformer forwards in eight-wide batches
  (`simulated_encoder=false`).
- Same bounded input scope: a 32-request, repeated-input batch-cache probe
  reported **one** physical forward and 24 cache reuses. Equal-size
  `batch_no_cache` required four forwards; singleton/no-cache required 32.
- The report measures process timing and endpoint RSS but leaves
  `peak_rss_bytes`, GPU memory, joules, FLOPs, production Worker transport,
  target-host p99, and WAL recovery unmeasured/null.
- AG News has only 64 train / 32 calibration / 32 test records in this
  qualification sample; report explicitly marks
  `independent_evaluation=false`, `temporal=false`,
  `laya_comparison_completed=false`, and
  `production_accepted=false`.

**Evidence boundary:** This is independent *research branch* proof of actual
pretrained model use and batch/cache mechanics, **not** the P0 frozen-weight
execution of the present Rust Worker on the final combined SHA. This README
does not import or auto-approve weights, count source-reported forward numbers
as a hardware-independent attestation, or grant any CAS/final-use/NDU right.
The exact latest stacked Rust/native/global CI, approved model loading,
generation fence, separate no-change future outcomes and 64–4096 Cell host
measurements remain mandatory. Keep `DENY_ALL`.

## Promotion gate

Freeze and retain (1) actual no-change predictions, (2) identical-initialized
untrained Head predictions and (3) trained Head predictions before looking at
future outcomes. Only independent held-out temporal/group/OOD evaluation,
negative transfer, reliability (Brier/ECE), real NDU future utility and
target-host process CPU/RSS/p99/throughput/recovery can select a new Cell.
Evaluator, Selector, Executor and final-use owners must remain separate.
Every artifact in this directory has `DENY_ALL` production authority.

**Known blockers:** The current environment has no approved pretrained HF
weights or future outcome data, and no target host-native full end-to-end
measurement. Rust full-matrix CI and final-use/signed CAS convergence must
also pass on the exact source SHA; synthetics are never a substitute.


## Exact stacked source/base convergence (P0)

A source-head research test success is **not** evidence that this stacked
candidate can be merged. The checked two-parent GitHub prospective merge must
bind (a) the **current**, not webhook-historical, upstream #1498 source SHA,
(b) this exact dynamic-learning head SHA, and (c) the verified
`git merge-tree` result. The architecture gate remains fail-closed if either
parent or the merged tree differs, or the base changes during verification.

The earlier architecture failure [run 38272131751](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38272131751)
verified this PR's source head but rejected its stale-base prospective
merge. It must not be relabelled green because native Q24 and offline learning
tests passed independently. Refreshing the current source candidate triggers
a new head/base comparison; an actual non-stale **base-merge** success and
complete blocking CI are still required before even considering integration.

This document adds no model weights, unreviewed data, real Encoder results,
signed NDU, CAS/final-use authority, or measured 64–4096 Cell target-host
throughput. This PR remains Draft/Shadow and never promotes automatically.
