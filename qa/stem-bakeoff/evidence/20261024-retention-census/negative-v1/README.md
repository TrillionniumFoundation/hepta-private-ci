# Frozen retention experiment: negative result, independently recomputed

All 18 preregistered conditions completed. Both heads failed both registered gates. The retention-hinge policy increased the primary future NLL relative to legacy, while the old-task noninferiority bound was not established. No policy was selected or retrained after this result.

## Numerical result

All differences are nats per example; lower is better. Intervals are the fixed 2,000-draw paired, category-stratified source-component bootstrap. The three fixed training seeds are averaged within each source first, and June/July receive equal weight.

| Head | Future: hinge − legacy | 95% interval | Old test: hinge − original warmup | 95% interval | Future / retention / joint |
|---|---:|---|---:|---|---|
| linear | +0.0001078507 | [+0.0000190913, +0.0001987136] | +0.0032029658 | [-0.1468702261, +0.1596319584] | fail / fail / fail |
| gated | +0.0001363633 | [+0.0000498845, +0.0002222502] | -0.0286844566 | [-0.1462599369, +0.0986514620] | fail / fail / fail |

The future gate requires the one-sided 97.5% upper bound to be below zero. The retention gate requires that upper bound to be at most +0.02 nats against the original warmup. The gated old-task point estimate improves; its wide interval still does not establish noninferiority. The linear old-task point estimate is slightly worse. Failure of the retention gate does not itself prove forgetting. Both primary future intervals are entirely positive, although their absolute effects are small.

The published raw score includes every seed, month, zero comparator, balanced accuracy, and the secondary old-test contrast against legacy. No favorable subset replaces the primary result.

## Cost and memory

The table sums the three fresh workers per head/arm. CPU is reaped process CPU, including interpreter work. It excludes shared acquisition, encoding, projection, warmup and reference construction. Controller and phase timers are subsets of these totals, not extra costs to add.

| Head | Arm | Reaped CPU seconds | Sequential supervisor wall seconds | Individual worker peak RSS, MiB range |
|---|---|---:|---:|---|
| gated | legacy_full_quadratic | 1.535461 | 1.713661 | 63.426–64.105 |
| gated | retention_hinge_suffix | 2.740495 | 3.209035 | 54.902–55.809 |
| gated | zero | 1.255594 | 1.301549 | 54.902–55.809 |
| linear | legacy_full_quadratic | 1.154784 | 1.350773 | 51.629–55.500 |
| linear | retention_hinge_suffix | 2.002818 | 2.104792 | 48.316–55.500 |
| linear | zero | 1.087249 | 1.308689 | 48.316–55.500 |

Across both heads, hinge uses 1.763153× the measured legacy worker CPU, an additional 2.053068 CPU seconds over six workers. This finite-run ratio is not a load benchmark or a deployment SLA.

Shared costs remain visible: the outer encoder stage reports 27.90 CPU seconds and 35.619165458 wall seconds; the outer 18-condition census reports 45.75 CPU seconds and 47.443987808 wall seconds. The internal census reports 35.750854784 owner CPU seconds + 9.776401 reaped-worker CPU seconds = 45.527255784 seconds before final publication work. Its six reference builds use 34.233840194 CPU seconds and six warmups 0.801555715 seconds, already included in owner CPU. The outer process measurements include more startup/exit/publication work and are rounded; they must not be added to their internal subintervals.

The feature process peak RSS is 1,316,458,496 bytes. The fixed encoder reports 97,441,152 loaded parameters and 389,764,864 resident tensor-storage bytes. The small trainable heads contain 36 or 52 parameters; their full numeric optimizer states contain 864 or 1,248 bytes. These head-state sizes are not total process or agent memory. Individual RSS peaks cannot be summed into a simultaneous process-tree memory estimate.

The compact receipts do not establish all acquisition, source-exclusion, recovery and publication costs. Missing costs are not zero. This result certifies no net benefit, energy saving or production activation.

## Audit and provenance

- Original observed source commit: `6b8f3651b062d5c59659c8e7b67f60c2724adafb`.
- Protocol SHA-256: `5f963295e4e49a64cde085aa2a4dde92c291df3b0450d768f986264e482d3832`.
- Prediction seal SHA-256: `189daef4888c294886707df4203df492a0c68267a3459023396728bf312c6ce9`.
- Original score SHA-256: `316c30e55e44ba4201ebe732225d498825d480a618167c58e323c9f981ccec0e`.
- Transfer archive SHA-256: `7683b135579b62f72a16d405a033b0fb7699dbf753513106637af91a7441cf21`.
- Independent maximum absolute numerical discrepancy: `4.4994390158148434e-18` (comparison tolerance `2e-12`).

The arithmetic auditor and evidence publisher verify 13 transferred payload identities, the seal bindings, all 12 registered execution/scoring source files, the 18 conditions and 6 warmup predictions, 480 unique source/component identities, and the 288 aligned final labels. It does not import the original scorer or execute training. The original run reports complete-state and serving-head reload equality; complete checkpoints and the feature matrix remain outside this compact bundle, so this arithmetic audit does not independently rerun encoder inference, training or checkpoint restoration. The audit also cannot prove absence of unrecorded external label access outside the recorded experiment.

```sh
python3 audit_retention.py --run raw/run --data raw/data --score raw/score.json \
  --source registered-source --output independently-recomputed.json
```

The original experiment used Python 3.13.12 / NumPy 2.2.6. This independent arithmetic recomputation used the environment recorded in `audit.actual.json`; the exact input bytes are preserved. `raw/MANIFEST.json` authenticates the transferred payloads and `BUNDLE_MANIFEST.json` records this publication.

## Limits

This is one balanced, finite historical news-classification family with three fixed fits. Registered component disjointness does not prove semantic independence or absence from foundation-model pretraining. Bootstrap uncertainty does not cover arbitrary training seeds, new task families, or deployment traffic. The negative result applies to this frozen controller/model/data setup; it neither demonstrates general intelligence nor rules out every cell architecture. No agent task, cell splitting, learned network formation, production clock attachment, or Codex replacement benefit was tested here.
