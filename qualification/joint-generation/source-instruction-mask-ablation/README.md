# Instruction-mask ablation under identical FIT source supervision

**Masking passes all 16 original five-gate contrasts; fair NDU passes 0/8 in either arm. Overall false.**

This experiment isolates input instruction masking from the additional FIT source-scene supervision introduced in the earlier positive mechanism. Both arms use the same source labels, initialization, 202→32→12×2 network, decoder, batch/channel schedule, optimizer, 500 supervised + 300 adaptation steps, calibration and serving law. Both copy the input. The sole numerical input-path intervention is whether the final ten instruction dimensions are zeroed. Active versus inactive encoder rows are part of that intervention, not a separately changed network size.

The original masked `SourceSceneModel` remains byte-identical. New `SourceInstructionVisibleModel` retains instruction features and has an explicit distinct mode/digest, type-preserving clone and checkpoint refusal before I/O. Its forward and gradients were tested exactly equal to the unmodified `JointModel` for identical parameter bytes/inputs; a copy does not alter those numerical results. Neither serving path uses source labels, group IDs or the target renderer. Explicit commands remain available outside the model for the same semantic transport.

Sixteen newly trained models: masked/visible × A/N × two fixed original-FIT folds × seeds 103/107. The same already-studied noise seeds 3701/3702/3711/3712 are reused. This is a finite matched causal intervention, **not fresh blind validation or arbitrary-domain generalization**. Original validation and TEST observations stay closed. All eight masked model digests, four masked base digests and all their evaluation metrics exactly reproduce the prior source replication. No weights are restored. All sixteen models and thirty-two calibrated heads freeze before evaluation.

## Results

Calibrated masked minus equally calibrated instruction-visible source model, original partial-command full/low macro metrics:

| Fold | Seed | Noise | Objective | Δ CE | Δ greedy text | Δ pixel MSE | Five-gate pass |
|---:|---:|---:|---|---:|---:|---:|---:|
| 0 | 103 | 3701 | additive | +0.020323 | +0.018727 | -0.000402 | Yes |
| 0 | 103 | 3702 | additive | +0.017913 | +0.018727 | -0.000383 | Yes |
| 0 | 103 | 3701 | ndu | +0.020930 | +0.021536 | -0.000427 | Yes |
| 0 | 103 | 3702 | ndu | +0.018031 | +0.019663 | -0.000394 | Yes |
| 0 | 107 | 3701 | additive | +0.028180 | +0.030899 | -0.000483 | Yes |
| 0 | 107 | 3702 | additive | +0.022734 | +0.023408 | -0.000396 | Yes |
| 0 | 107 | 3701 | ndu | +0.027132 | +0.032772 | -0.000532 | Yes |
| 0 | 107 | 3702 | ndu | +0.020953 | +0.025281 | -0.000430 | Yes |
| 1 | 103 | 3711 | additive | +0.016475 | +0.015873 | -0.000348 | Yes |
| 1 | 103 | 3712 | additive | +0.008344 | +0.008929 | -0.000133 | Yes |
| 1 | 103 | 3711 | ndu | +0.018926 | +0.016865 | -0.000366 | Yes |
| 1 | 103 | 3712 | ndu | +0.009469 | +0.011905 | -0.000137 | Yes |
| 1 | 107 | 3711 | additive | +0.012876 | +0.010913 | -0.000255 | Yes |
| 1 | 107 | 3712 | additive | +0.008503 | +0.003968 | -0.000170 | Yes |
| 1 | 107 | 3711 | ndu | +0.014031 | +0.012897 | -0.000275 | Yes |
| 1 | 107 | 3712 | ndu | +0.008759 | +0.005952 | -0.000162 | Yes |

Masking improves CE by +0.008344 to +0.028180, greedy text by +0.003968 to +0.032772 and reduces pixel MSE in every primary contrast, with no regression in the other original gate metrics. Because both arms receive identical source supervision, this identifies a masking contribution under this fixed finite setup. It does not prove that all earlier source-mechanism gains came from masking, or that the effect transfers to other domains.

Fair NDU inside each architecture remains unsuccessful:

| Fold | Seed | Noise | Masked N−A CE | Visible N−A CE | Either five-gate pass |
|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | -0.000272 | -0.000879 | No |
| 0 | 103 | 3702 | -0.001112 | -0.001229 | No |
| 0 | 107 | 3701 | -0.002993 | -0.001946 | No |
| 0 | 107 | 3702 | -0.004134 | -0.002353 | No |
| 1 | 103 | 3711 | +0.000891 | -0.001561 | No |
| 1 | 103 | 3712 | -0.000224 | -0.001349 | No |
| 1 | 107 | 3711 | +0.000045 | -0.001110 | No |
| 1 | 107 | 3712 | -0.001364 | -0.001620 | No |

Masked and visible fair NDU each pass **0/8**; all eight visible CE differences are negative and visible pixel MSE rises in all eight. Several no-regression gates fail in both modes. Uncalibrated NDU also passes 0/8 in each. Thus mask=true, masked-NDU=false and **overall=false**. A positive content-control intervention is not a positive NDU result.

Self-calibration passes all 32 comparisons and preserves greedy text exactly. Thirty fitted temperatures reach the unchanged upper bound 8, two are interior solutions. All 120 contrasts—including unfavorable and pooled descriptive values—are preserved. No bounds, thresholds, samples or arms were changed after results; pooling cannot rescue a failed component.

## Complete cost

Whole fully waited child: **23.036013 CPU seconds**, 23.139216 wall seconds, 97284 KiB RSS under 60 CPU / 180 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread and the existing synthetic lock. No retry, model save or restore. All eight base preparations, 31 tests, source-label derivation, data generation, input copies/masks, calibration and evaluation are inside the receipt. Equal updates do not assert identical elapsed CPU.

Ledger: 8 bases / 16 clones; 2400 decoder + 4000 supervised + 4800 adaptation updates; 22480 forwards / 1533440 rows; 2416 decode calls / 28992 images; 896 NLL evaluations / 1397760 head-row evaluations; 124800 output joint tables plus 49920 internal base tables; 99840 support and 99840 argmax checks. Each arm copies 11240 batches / 766720 rows; masked zeros 7667200 instruction elements, visible zeros none. Tests are additional to scientific counters but included in whole child CPU. Two FIT datasets, four held-out datasets, zero original TEST calls.

Historical source replication cost 24.010599 CPU seconds separately; prior research/qualification, source/review and unknown supervisor tails remain additional, not zero. This does not claim an end-to-end speedup, restore original digit-study payloads or establish natural-image performance.

## Portable tests

Three added tests cover matched initialization/input copies, exact original forward/gradient equivalence plus seven finite-difference coordinates, and mode/clone/digest/optimizer/checkpoint isolation. The source and original models are published sibling/parent dependencies:

```sh
PYTHONPATH=../source-scene-decomposition:.. python -B -m unittest -v test_visible_source
```

Only portable source, tests, fixed plan and complete aggregates are public—not weights, private inputs, per-request predictions or runtime paths. No production/default change or unrestricted scientific runner.
