# P2—Backpropagation, Router and whole-replay operator-cost reality

**Research-only / Draft / DENY_ALL.** This is a sidecar of the existing, sealed
[#2208](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2208)
training receipts, **not** a new Router policy, optimizer, pretrained model
loader, NDU authorizer, CellSplit owner or production capability.

## Why this is the next causal blocker

The existing 40-step single-active, fixed-Top-1 and adaptive-Top-1 models each
physically forward **3,840 selected Head-row examples** with **28,508,160
registered Head forward linear MACs**. That equality does **not** account for
separate occupied expert batches, routing comparisons, memory gathering,
backpropagation autograd graph size, optimizer updates, parent-copy verification,
model/materialization, or live worker overhead. Therefore the previous equal-
forward-budget experiment is not an equal-total-compute experiment.

This incremental *actual CPU autograd replay* instruments the **unchanged**
trained `p2_train_sparse_equal_compute.train_arm` with PyTorch CPU profiler
(`with_flops=True`, `profile_memory=True`). It does not refit an alternate
hyperparameter configuration, rank or filter seeds by test accuracy. Each
newly executed arm MUST reproduce its original complete final FP32 weight
SHA and all 96 original label-blind logits (absolute tolerance ≤1e−6), route,
training steps, training-row exposure and split/migration events.

The profile includes the entire existing `train_arm` call: old/new diagnostic
forwards, 40 actual SGD backpropagation steps when learned, split parity
when triggered and heldout inference. It **does not include** original
Granite97 encoder/model loading inside its `torch.profiler` scope: the sidecar
separately performs and counts a **new 224-case original frozen-Encoder
materialization** and records its CPU/wall cost. Any real-model rerun requires a
**second model load** relative to the original P2 producing job; it is an
**extra lifecycle cost**, not a free cached receipt.

## Real observed CPU operator distinction on three synthetic fixtures

The three fixed `41 / 47 / 53` studies use the same 147,840p **random-weight**
Stem used by the historical P2 tests and only public-structured synthetic
cases. Local actual physical Torch CPU profiler counts are:

| Arm | Trained expert rows | Partial ATen FLOP annotations | Autograd backward function events | Gather / index / route calls |
| --- | ---: | ---: | ---: | ---: |
| Frozen single | 0 | 3,502,016 | 0 | 12 |
| Learned single active | 3,840 | 150,105,576 | 1,000 | 212 |
| Fixed Top-1 | 3,840 | 150,105,576 | 1,680 | 381 |
| Train-only adaptive Top-1 | 3,840 | 150,230,648 | 1,340 | 303 |

The identical *partial ATen FLOP totals* for learned single and fixed Top-1
coexist with **more** autograd/route operation events for fixed Top-1. The
adaptive trial also paid its original parent clone and two physical parity
Head micro-batches, and the reported partial FLOP total is correspondingly
larger. These results demonstrate **operator and graph topology differences**
with otherwise matched main forward rows, not definitive total compute
advantage. The per-arm instrumented CPU wall timings were non-monotone among
seeds and are deliberately reported raw, unranked and uncensored in the local
JSON; the arms always run in a fixed order and profiler adds overhead.

**Incomplete flop coverage:** PyTorch CPU profiler can annotate eligible
matrix operators such as `aten::mm`, but it does **not** supply a rigorous full
FLOP count for SiLU, Sigmoid, reductions, index scattering, entire autograd and
SGD, state checks or complete model lifecycle. The study therefore ALWAYS
emits `complete_backward_flops_verified=false`, `equal_total_training_compute_verified=false`,
`whole_request_p99_verified=false`, `energy_usage_verified=false` and no model
winner. A measured CPU time does not authenticate physical model origin or
an independent future episode.

## Independent review and original source ownership

`p2_backward_cost_profile_review.py` does **not import** Torch, the original
trainer or its profiler. It independently reruns the ORIGINAL P2 and trained
Top-1 model/weight/label audit, then verifies this additional cost record's
source SHA, exact original Stem/Head weight SHA, frozen model revision, 96
source IDs, update/exposure/route census, extra replay encoding, all 4 arms,
closed operator keys, per-op CPU time/FLOP sums and signed negative outcomes.
It refuses rehashed fabricated `equal-total-compute` or production claims,
missing backward operators, wrong encoder lineage, missing original arms,
operator cost arithmetic tampering and false free migration. Self-reported
Torch profiling events cannot be independently reconstructed without actually
re-running the source; **do not interpret the numeric audit as independently
signed hardware attestation**.

Real-mode CLI, after the existing real P2 + trained-Top-1 original artifacts
have been created and **before any heldout label file has been opened**:

```bash
python qualification/stem-cell-v1/p2_backward_cost_profiler.py \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --compact-source pinned-compact \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --original-trained-top1-report "$ROOT/trained-top1-unscored.json" \
  --output "$ROOT/backward-operator-profile-unscored.json"
```

Only after independent owner labels are authorized for the old study, open
them **in the separate numeric reviewer**:

```bash
python qualification/stem-cell-v1/p2_backward_cost_profile_review.py \
  --original-panel "$ROOT/panel.json" \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --owner-labels "$ROOT/material/owner-labels.json" \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --original-trained-top1-report "$ROOT/trained-top1-unscored.json" \
  --cost-report "$ROOT/backward-operator-profile-unscored.json" \
  --output "$ROOT/backward-operator-independent-review.json"
```

The workflow pins the same old validated Granite97 revision
`835ad14087e140460703cf0fae09f97d469d65c2`, AG News canonical
source, read-only checkpoint, original source owner and fresh exact PR SHA.
The real model job cannot silently replace missing pretrained weights with
the toy Stem. The **source-only** job can execute 31 adversarial tests without
pretrained model downloads. The source-only green never qualifies the real
model job.

## How to reproduce source-only mechanism

```bash
python -m unittest discover -s qualification/stem-cell-v1 \
  -p test_p2_backward_cost_profiler.py -v
python -O -m unittest discover -s qualification/stem-cell-v1 \
  -p test_p2_backward_cost_profiler.py -v
python -m compileall -q qualification/stem-cell-v1/p2_backward_cost_profiler.py \
  qualification/stem-cell-v1/p2_backward_cost_profile_review.py \
  qualification/stem-cell-v1/test_p2_backward_cost_profiler.py
```

Local evidence `P2_LOCAL_BACKWARD_OPERATOR_3SEED_20261015.json` records all
arms, seeds, original research-only SHA lineage, operator and wall counters and
research-only flags. Complete raw operator-only CPU observations and individual
independent review JSON are in the conversation evidence packet; these are not
a real Granite97 model success. No raw model feature vectors, unscored Head
weight bytes, source text or human validation labels are uploaded to GitHub
Actions artifacts.

## Decisions still blocked

No production model promotion, supervised future learning, NDU/System2 gain,
true lifelong adaptation, revised Stem choice or 10T/100T equivalence follows.
The decisive next gate must obtain completed exact-head *real* Granite97 model
CI, independent human-label results, known/fully profiled backward and router
cost, same-total-compute alternatives, source/time-disjoint future windows and
old-task retention, then original signed Worker/CAS/WAL/FinalUse and ordinary
`blocking-ci`. Keep `Draft / DENY_ALL`, do not merge to `main`.
