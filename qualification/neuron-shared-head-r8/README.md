# Hepta Neuron R8 — shared representations and lightweight per-Cell heads

This is **research-only**, strictly non-authorizing qualification code. It is a
preproduction shadow candidate and must never produce learning-artifact promotion,
model installation, authority, or deployment receipts. It does **not** execute
ModernBERT, Laya or live Hepta `NeuronRuntime` by itself.

## Environment and source bounds

Python 3.11+ and NumPy 2.x. Verified locally with Python 3.13.5, NumPy 2.3.5,
CPU-only. The single-file runner uses bounded numeric features (`1..512`) and
numeric labels. Inputs are `.npz` loaded with `allow_pickle=False` and must
carry `x` (float32), `id`, `group`, `time`, `cell`, `encoder_digest`, and
`scope_digest`; training sets also carry `y`. Optional `teacher` probabilities
on the training split permit distillation; teacher provenance must be separately
verified before any conclusion about actual Laya knowledge transfer.

The `encoder_digest` and `scope_digest` strings are **caller-supplied identities**,
not verified signatures. Hashes in reports make local artifacts tamper-evident
only when independently pinned and verified. They are not Hepta authorization.

## Experiment 01: bounded Head capacity

```bash
python r8_experiments.py train --train /data/train.npz --valid /data/valid.npz \
  --kind film --budget 2048 --steps 1000 --classes 2 --seed 13 \
  --output /results/head.npz --report /results/head.json
python r8_experiments.py predict --model /results/head.npz \
  --input /data/future_unlabelled.npz --output /results/heldout_predictions.json
python r8_experiments.py evaluate --candidate /results/heldout_predictions.json \
  --baseline /frozen/no_change_predictions.json \
  --outcomes /private_evaluator/future_outcomes.json \\
  --candidate-ood /results/candidate_ood.json \\
  --baseline-ood /frozen/no_change_ood.json \\
  --ood-outcomes /private_evaluator/ood_outcomes.json \\
  --output /results/future.json
```

Train `linear`, `film`, `lowrank8`, `lowrank16`, `mlp`, `swiglu` at
2048/16384/65536/262144 trainable-parameter caps. Realized param counts are
reported; linear and FiLM are not padded to fake budget parity. Run matched
training **steps** and independently match compute/time separately; FLOPs are
not automatically matched by equal steps. Train, validation and future episode
groups and future timestamps must be disjoint. Training NEVER reads hidden
future labels, and evaluation never writes the model. Brier, ECE, accuracy and
NLL are reported. OOD AUROC is computed only when the evaluator receives paired ID/OOD
predictions and a separate independent-observation OOD manifest; a synthetic
fixture tests just the calculation. Authentic OOD claims, true NDU delta and
negative transfer remain blocked until independent evidence is supplied.

## Experiment 02: external frozen-encoder/teacher comparison

The fourth-party exporter must publish predictions on identical complete
future decision sets for each exact pinned arm:
`laya_original`, `shared_laya_head`, `organ_expert_bank`,
`modernbert_base_head`. `compare-representations` rejects missing arms,
non-paired event IDs, absent original-Laya backend identity, and synthetic
outcomes. This runner **does not contain the weights or implement the
Organ Expert Bank trainer**. Representation comparisons cannot be executed
honestly until independently trained/evaluated model exporters exist.

```bash
python r8_experiments.py compare-representations \
  --arm laya_original=/runs/laya_original.json \
  --arm shared_laya_head=/runs/laya_shared_head.json \
  --arm organ_expert_bank=/runs/organ_expert_bank.json \
  --arm modernbert_base_head=/runs/modernbert_base.json \
  --outcomes /private_evaluator/future_outcomes.json \
  --output /results/representation_compare.json
```

Each arm JSON has `schema=hepta.neuron.head-experiments.v1`,
`production_admitted=false`, `arm`, a real pinned `model_file_sha256`,
`train_groups`, `valid_groups`, optional `valid_time_max`, optional
`encoder_digest`, `rows` with matching `id/group/time/probabilities` and for
`laya_original`, `backend=laya_original_model`. The record names are evidence
claims, not authenticated model execution. External evaluator/selector must
verify exact effective model identity. No state-only cache is presumed
numerically equivalent to Laya's question-and-options-conditioned encoder.

## Experiment 03: cell-scale numerical microbenchmark

```bash
python r8_experiments.py scale --cells 4096 --pattern partial \
  --kind film --budget 2048 --requests 2048 --active 1 \
  --train-frequency 0 --output /results/scale.json
```

Repeat each of 64/256/1024/4096 cells × same/partial/distinct input. The
microbenchmark runs *actual NumPy per-cell Heads* and a *synthetic 32-to-d
numeric projection*, **not** Laya/ModernBERT or production batch execution.
It reports p50/p95/p99 local request times, measured process peak RSS,
allocated Head bytes, hit ratio and updates. Process-level and Host-level
startup/CPU isolation matter. It does **not** measure GPU, WAL, recovery,
NDU, production scheduling or encoder-backend throughput. Those must use
live host workloads, signed receipts and the existing independent evaluator.

`--max-head-bytes` is a hard preallocation guard; do not accidentally instantiate
4096 × 262K trainable tensors on a small host. The update mode simulates local
error-driven gradients only; it is not durability-tested cell learning.

## Reproducible no-authority smoke fixture

```bash
python r8_experiments.py synthetic-fixture --dir /tmp/r8
python -m unittest -v test_r8_experiments.py
```

All `synthetic-fixture` data and results must be marked **synthetic**, must
never be substituted for the original Laya arm or independent NDU benefit, and
cannot qualify any production release. The built-in `no_change.json` and `no_change_ood.json` are
synthetic uniform-probability baselines, **not** the user's deployed Cell policy.
A real experiment must freeze the actual incumbent policy before candidate
training begins and bind it to the same evaluator windows.

## Admission (all blocked by default)

Production selection requires *separate* verification: 1) pinned code/model,
weights, tokenizer, normalizer, scope/permission and dataset lineage;
2) episode/source-group-disjoint heldout + future windows;
3) authentic
original Laya/ModernBERT runs; 4) Brier, ECE, OOD and subgroup/negative
transfer; 5) independent outcomes and NDU net benefit; 6) target-host
CPU/RSS/GPU, p95/p99, WAL, failover, restart, cache invalidation, 64..4096
scope runs; 7) independent Evaluator -> Selector -> Executor, recovery and
rollback receipts. The `promotion: BLOCKED` field is intentional.