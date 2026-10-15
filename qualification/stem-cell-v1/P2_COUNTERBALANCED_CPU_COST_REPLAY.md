# P2 Head cost: genuinely re-train every Top-1 arm in balanced CPU order

**DRAFT / DENY_ALL / RESEARCH ONLY.** This is a child of P2 physical-backward profiler PR #2226 (exact parent `837ef356aef9e53411f702cc7e94bdcef999152f`), not a new model loader, Head selector, production Cell Split owner, or authorization. The old #2180/#2199/#2208/#2226 calculations, weights, scores and negative results remain immutable.

## The inference gap closed

#2208 compared 40 SGD updates, 3,840 active training Head-rows, and 28,508,160 registered forward linear MACs per learned arm. #2226 replayed the training under a PyTorch CPU operator profiler, observing additional routing/autograd work (e.g. 1,680 backward-function evaluations for fixed Top-1 vs 1,000 for single-active), but **profiler overhead** and **fixed model execution order** limit wall-time interpretation. The profiler collects training plus train-only diagnostics and heldout (unscored) forward passes; its ATen FLOP annotations are partial, not complete training-only FLOPs.

This research adds **unprofiled, balanced, paired CPU wall/process-time evidence**, without claiming a whole-service quality/cost equivalence.

## Exact physical producer protocol

1. Reuse the pinned P2, same exact initial 14,868 FP32 Head parameters, same source owner, identical train-only cutoff and **same original 128 train + 96 blind evaluation identities**. Verify the previous two sealed receipts, original model weights, same 224 Q24 feature values re-encoded from the frozen physical Stem. For a *real* request, `p2_backward_cost_profiler.source_lock` refuses mock weights and requires original pinned Granite R2 97M identity (`835ad14087e140460703cf0fae09f97d469d65c2`); no local weight download or fabricated fallback.
2. Execute **one cost-accounted warmup training run per arm**. For each of **8 registered measured rounds**, re-train all four arms from the **same original initialization** and record actual `process_time_ns` and `perf_counter_ns` around the entire `train_arm` execution: frozen no-change, single-active, fixed Top-1, adaptive Top-1. No Torch profiler or `torch.compile` is used in this timing phase. Original train diagnostics, split parity, weight migration, optimizer, and 96 blind predictions are within the timed call.
3. Use an eight-order **four-arm counterbalanced crossover**: Williams-like base `(0,1,3,2)`, all four cyclic arm translations and their reversals, with one **predeclared seed-specific permutation of arm names**. Each arm occurs **twice in each ordinal position**, so the fastest phase cannot always occupy the warmest CPU slot. All 4 × 8 measured + 4 warmup full runs are charged and reported, including slow/negative runs. Only eligible round counts 8/16/24/32 are allowed.
4. Every one of the 36 physical executions must reproduce the original exact final weight SHA, split decision and physical expert/head batch counts, all **96 source-locked blind logits within 1e-6** of the preexisting frozen predictions, and unchanged frozen Stem weights. A new physical run reencodes all 224 original features and records model-load and feature materialization costs rather than reusing free features by assumption.
5. The unscored producer **does not read any validation labels**. It writes a create-only JSON receipt. A separate stdlib-only reviewer, which does not import Torch or producer, first opens original human labels and reruns previous independent P2 + operator-cost reviews, and only then validates the new exact observation schema, all trial slots and order/position census, weights, split/migration work, CPU/wall clock nesting and unsupported performance/authority claims.

## Actual local mechanism evidence (three fixed seeds, *mock weights*)

The local tests use a **147,840-parameter randomly initialized fake Stem** and synthetic-public-shaped source and labels, NOT the actual Granite97 model or prospective independent tasks. Three seeds 41/47/53, four arms × eight paired measurement rounds plus four paid warmups per seed. CPU Torch `2.10.0+cpu`, single OMP/MKL thread, no profiler during timed trials. The numbers are *descriptive median within-round full Head call CPU ratios* against 40-step single-active; the entire call includes training, train-only split diagnostic and 96 blind predictions.

| Arm | Seed 41 | Seed 47 | Seed 53 |
| --- | ---: | ---: | ---: |
| Frozen single (zero SGD) | 0.040 | 0.041 | 0.043 |
| 40-step single-active (normalizer) | 1.000 | 1.000 | 1.000 |
| Fixed Top-1 | **1.148** | **1.146** | **1.150** |
| Adaptive Top-1 | **1.087** | **1.116** | **1.088** |

The frozen Head is lower-cost partly because it is not trained, **not** an equal-learning-quality baseline. The fixed Router is physically slower despite equal registered forward expert rows; this is a real negative cost control, and both quicker and slower trials remain in every stored round. Only the number of recorded Head training forwards is equal: 3,840 each per learned execution. **Neither equal total CPU cost nor complete FLOPs is established.** The ratio is not an independent population/episode statistic, a production p95/p99, a true energy/GPU benchmark, or evidence of Cell Split quality.

Each fresh *real* hosted replay would additionally load the full original model, reencode 224 sources, then repeat this Head training. **Do not compare only the cached Head phase and call it the total shared Stem lifecycle cost.** Model weights, source text and trained Head bytes are never uploaded as hosted artifacts; only independent sanitized aggregate reviews and dependency/log receipts are retained. If real CI fails/queues, no actual pretrained measurements exist from this change.

## Reproduction

From a checked-out repository containing the original P2 and new source:

```sh
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_counterbalanced_cpu_training.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_counterbalanced_cpu_training.py' -v
```

In the pinned public pretrained workflow, the write-once steps are sequenced:

```sh
python qualification/stem-cell-v1/p2_counterbalanced_cpu_training.py \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --compact-source pinned-compact \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --original-trained-top1-report "$ROOT/trained-top1-unscored.json" \
  --rounds 8 --crossover-seed 20261015 \
  --output "$ROOT/counterbalanced-cpu-unscored.json"

# After all original and cost predictions are sealed, the independent reader opens
# the original owner labels and the previous completely reviewed operator source:
python qualification/stem-cell-v1/p2_counterbalanced_cpu_training_review.py \
  --original-panel "$ROOT/panel.json" \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --owner-labels "$ROOT/material/owner-labels.json" \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --original-trained-top1-report "$ROOT/trained-top1-unscored.json" \
  --original-backward-cost-report "$ROOT/backward-operator-profile-unscored.json" \
  --counterbalanced-cost-report "$ROOT/counterbalanced-cpu-unscored.json" \
  --output "$ROOT/counterbalanced-cpu-independent-review.json"
```

## Scientific and operational hard gates

- There is no reason to infer equal *backward/optimizer* FLOPs or equal total budget from these measured times. CPU results are platform/environment-specific and sequential-process observations; arm training and reported profiler remain correlated on the same repeated 96 examples. A self-hashed time cannot independently prove a hardware timestamp; the reviewer catches missing/malformed/arithmetically inconsistent claims but not a self-consistently forged clock.
- The data remain retrospective **English AG News**, not longitudinal future1/future2/future3/OOD or independently sourced memory-retention episodes. No Reader sufficient-evidence certification, Cell Split utility, genuine NDU/FBSDE gain, multimodal generation or 10T/100T equivalence is established.
- Original `inference.control`, trained source/material owner, native Worker/CNS/CAS/WAL/FinalUse, promotion gates, `main`, `CURRENT` and selected Stem are untouched. Passing the research-only CI is **DENY_ALL**, not permission to mutate a topology or serve a new model.

## Exact local regression census and fail-closed outcomes

The new counterbalanced producer/reviewer suite passed **31/31** normal and **31/31** Python `-O` tests. Previously independent research source suites were re-executed and checked by their own completed process logs: original operator profiler 31, trained physical Top-1 32, postfit sparse 22, equal-parameter P2 24, real Granite-interface P1 27, shared 4,096 Cell P1 33 and Reader provenance P0 59. Thus **259 distinct focused test methods completed successfully in each mode**; this is not a model qualification or a hosted CI pass. An initial all-in-one inherited run **timed out** after several passing components; the original incomplete command is explicitly not counted as a completed regression, and all remaining components were run separately and verified. Exact aggregated counts are retained in the research-only JSON census.
