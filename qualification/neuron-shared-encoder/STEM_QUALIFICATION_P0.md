# Real Stem qualification receipts — research-only P0

This tranche adds the evidence boundary after the frozen Stem, modality registry
and envelope contracts. It records what a real checkpoint run must prove before
its result can enter a matched-budget Stem comparison.

## Contracts

stem_qualification.py defines:

- CheckpointRefV1: model manifest, weights, tokenizer, preprocessor,
  checkpoint, quantization, backend, runtime, device and Stem identity;
- SourceDisjointSplitV1: train/eval/future/OOD source and lineage digests,
  dedupe report, overlap count, source family count, future-window count and
  held-out cohort counts;
- MetricIntervalV1: metric value with LCB/UCB, sample count, confidence,
  evaluator digest and held-out source digest;
- ComponentResourceReceiptV1: one measured component receipt;
- ComponentResourceBundleV1: canonical component bundle covering the selected
  profile (encoder_only, encoder_decoder, or full_generation);
- StemQualificationRunV1: the complete real shadow run manifest, including
  task identity, registry identity and the bound case/budget/cost digests;
- qualify_from_receipt: a fail-closed adapter for the older bridge receipt.

The module performs no checkpoint loading, forward execution, training, model
selection, runtime mutation or production activation.

## Qualification boundary

A run is admissible only when:

1. the checkpoint identity is source-bound and includes weights, tokenizer,
   preprocessor, quantization, backend, runtime and device digests;
2. train, eval, future and OOD sources are mutually disjoint;
3. the dedupe report records zero overlap;
4. the evidence class is REAL_SHADOW;
5. the run status is SHADOW_COMPLETE;
6. every metric has an ordered interval and non-zero sample count;
7. metrics cover the corresponding held-out eval, future and OOD cohorts;
8. the measured resource bundle is complete and has ordered end-to-end
   p50/p95/p99 latency, positive measured peak memory and energy;
9. component receipts cover every component required by the run profile;
10. tower/projector registry digests, Stem digest and generation agree;
11. model-visible gold is false;
12. authority remains DENY_ALL.

Synthetic smoke and historical replay can remain diagnostic artifacts, but
qualify_from_receipt rejects them and also rejects incomplete point-only
receipts. A legacy bridge object is only an input identity check; the adapter
still requires the caller to bind the complete checkpoint, source, interval,
resource and plan evidence. It never fills missing confidence intervals or
resource dimensions with zero.

## Cost accounting

The resource bundle keeps component FLOPs separate for:

- Stem encoder;
- modality tower;
- projector;
- Cell head;
- controller/decoder;
- state/cache;
- verification;
- device.

The bundle also records measured end-to-end latency quantiles, peak memory,
energy, batch size, warmups, measured steps, repetitions and cache hit rate.
Component p95 values are not added together and are not treated as end-to-end
latency, and component peak memory is not silently substituted for end-to-end
peak memory.

Comparing 421M, 311M, 149M and 97M Stems requires a versioned matched budget,
workload profile and normalized cost profile. FLOPs, latency, memory and energy
must not be directly added as if they shared physical units.

## Relationship to sibling experiment plans

This receipt layer is additive and does not modify the existing
QualificationReceiptV1, ResourceCostV1 or prospective equal-budget plan
constructors. It can be composed with those plans by binding their case,
budget and evidence digests. A point-only historical or synthetic receipt
cannot be promoted into a real qualification run without a checkpoint identity,
source-disjoint certificate, confidence interval and measured component bundle.

All output is research-only, shadow-only and non-authorizing. Passing this
protocol is not evidence that a Stem is better, that multimodal alignment
works, or that a model may be selected for production.
