# V6 results: complete controlled fitting, incomplete retention

A 4,096-weight cross-fact bridge closes V5's full 128 training-fit gap in all three seeds. The equally enlarged local Head and the historical base pass in zero seeds. Subsequent fixed-budget training does not retain the binding task reliably: the preselected contrastive arm passes in only two seeds. Feedback training and new held-out evaluation were therefore not executed.

This is evidence of finite training-task learnability under this recipe. It does not establish reasoning emergence, an optimal Encoder, NDU benefit, multimodal transfer, faster new-task learning or stable continual learning.

## Frozen experiment

- Runtime: `7fe7e5ec7af93d2bd2645b2ac36ddb40f915ea3d`; 52 source hashes unchanged through completion, including all 48 V5 files.
- Later independent auditors: `0812d5deff7afb8416ed76a287cc1b4439551bd5`. Added auditors did not change the frozen runtime or rerun training.
- Frozen Encoder: `ibm-granite/granite-embedding-97m-multilingual-r2` at `835ad14087e140460703cf0fae09f97d469d65c2`, 97,441,152 scalars, hidden 384. Reused real historical token features; no new Encoder forward in V6 or the supplemental ablation.
- CPU FP32, PyTorch 2.6.0, Transformers 4.57.1, one Torch thread; neural jobs sequential. Environment details are in the raw bundle.
- Same 32 independent paired-world training groups / 128 candidates / 64 candidate-world pairs for every seed. Three seeds repeat examples; they do not create 384 independent cases.
- Natural Reader training: 3,909 candidates / 64 paragraphs; descriptive internal tune: 827 candidates / 194 questions / 16 paragraphs, already exposed in V4. Only official MultiRC training-source data was read.
- New work: six warmups and nine continuations. Three actual V5 base warmups are historical comparison evidence, with their weights, receipts, panels, initializations and costs bound by SHA.

Bridge exchanges facts once during preparation, then uses the existing depth 3 bounded recurrent state. Wide adds the same four 32x32 matrices in a local residual Head, executed every hop. Both contain 42,562 trainable scalars versus base 38,466. Common initial weights and predictions match exactly; residual output matrices start at zero. Equal parameter counts and budget ceilings do not imply equal operations, actual updates or latency.

## Complete controlled training fit

The frozen gate requires 100% candidate and paired-world correctness and CE <=0.10 at a scheduled full 128 diagnostic. Adam .001, batch 16, depth 3, last-hop CE plus .5 world-pair margin, diagnostic interval 250, maximum 8,000 updates. The earliest passing scheduled diagnostic is retained. CE below is independently reconstructed from saved FP32 probabilities; receipt logit-space CE is separate.

| Arm | Seed | Updates | Correct /128 | Both worlds /64 | Probability CE | Fit CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base (historical) | 41 | 8,000 | 122 | 59 | 0.066152 | 121.575856 |
| bridge | 41 | 4,000 | 128 | 64 | 0.004756 | 66.883196 |
| wide | 41 | 8,000 | 126 | 62 | 0.021741 | 129.671970 |
| base (historical) | 47 | 8,000 | 125 | 61 | 0.032511 | 124.016025 |
| bridge | 47 | 500 | 128 | 64 | 0.000554 | 8.379710 |
| wide | 47 | 8,000 | 125 | 61 | 0.032518 | 134.011535 |
| base (historical) | 53 | 8,000 | 125 | 62 | 0.033289 | 130.321882 |
| bridge | 53 | 4,250 | 128 | 64 | 0.018184 | 72.241522 |
| wide | 53 | 8,000 | 124 | 60 | 0.043859 | 132.483593 |

Bridge passes 3/3 with 8,750 actual updates / 140,000 candidate exposures / 147.504428 fit CPU seconds. Wide passes 0/3 with 24,000 updates / 384,000 exposures / 396.167097 seconds. Historical base passes 0/3 with 24,000 updates / 384,000 exposures / 375.913763 seconds. These are observed fitting costs under scheduled stopping, not equal-compute or held-out learning-efficiency estimates.

## Supplemental residual disable diagnostic

This posthoc train-only diagnostic was planned after primary training began and frozen before its own execution. It zeroes only each trained added residual output matrix, leaves the same operations running and reuses the original model panel. It neither trains again nor chooses a model.

| Arm | Seed | Correct original -> disabled /128 | Pairs original -> disabled /64 | Prediction flips |
| --- | ---: | ---: | ---: | ---: |
| bridge | 41 | 128 -> 74 | 64 -> 10 | 54 |
| wide | 41 | 126 -> 126 | 62 -> 62 | 0 |
| bridge | 47 | 128 -> 116 | 64 -> 52 | 12 |
| wide | 47 | 125 -> 123 | 61 -> 59 | 4 |
| bridge | 53 | 128 -> 123 | 64 -> 59 | 5 |
| wide | 53 | 124 -> 121 | 60 -> 57 | 5 |

The bridge residual contributes to these trained predictions, with substantial seed variation. This intervention does not isolate training-time mechanisms or demonstrate held-out causal improvement. Six new panels execute 48 physical batches / 768 candidate observations; their costs are separate from the formal experiment.

## Fixed-budget continuation and retention

Each seed starts all three arms from its identical frozen bridge warmup. Each arm receives the same 500 natural updates / 8,000 exposures. Replay and contrastive add 500 identical binding updates / 8,000 exposures; their pair-margin weights are 0 and .5. All nine runs complete their fixed budget with no diagnostic-based stopping or checkpoint selection.

Retention requires >=95% candidate and paired-world correctness, each losing <=5 percentage points from warmup. This checks retention on the complete old training task, not new generalization.

| Seed | Arm | Correct /128 | Both worlds /64 | Retention | Natural internal F1a | Natural internal EM | Fit CPU seconds |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: |
| 41 | natural_only | 104 | 41 | fail | 0.488619 | 0.123711 | 83.959764 |
| 41 | replay | 125 | 61 | pass | 0.477825 | 0.067010 | 93.724074 |
| 41 | contrastive | 124 | 60 | fail | 0.412752 | 0.082474 | 92.996475 |
| 47 | natural_only | 111 | 47 | fail | 0.501992 | 0.092784 | 82.651275 |
| 47 | replay | 128 | 64 | pass | 0.488145 | 0.087629 | 92.451592 |
| 47 | contrastive | 128 | 64 | pass | 0.508431 | 0.082474 | 91.130383 |
| 53 | natural_only | 99 | 35 | fail | 0.437299 | 0.087629 | 87.197767 |
| 53 | replay | 83 | 23 | fail | 0.418530 | 0.061856 | 95.867526 |
| 53 | contrastive | 126 | 62 | pass | 0.372414 | 0.077320 | 96.605425 |

Contrastive seed 41 retains 124/128 candidates but only 60/64 pairs (93.75%, a 6.25-point loss), so its global 3-seed gate is false. Natural-only passes 0/3; ordinary replay also passes only 2/3, failing seed 53. Replay was not substituted for the preselected contrastive primary.

The previously exposed controlled binding internal tune (16 groups / 64 candidates / 32 pairs) is also weak: paired correctness across the nine continuations is only 3–7/32 (9.375–21.875%). This is a separate old internal panel, not either unopened fresh domain; successful training fit has not demonstrated relationship transfer.

Natural internal diagnostics are mixed: always-positive F1a is 0.622814 and EM 0; every trained continuation has lower F1a, while some question-level EM and other metrics improve over cheap controls. Always-negative and train-majority have F1a 0, EM 0 and accuracy 0.547763. These panels were previously exposed, and none establishes a natural-language reasoning gain. Synthetic-only warmup natural scores are not used as a natural-task forgetting baseline.

The formal `feedback-start`, `all-models-frozen`, `evaluation-start` and final `completion.json` markers are absent. The continuation completion receipt records the failed gate. Implemented real/zero feedback and fresh state-reset/evidence-deletion controls remain unexecuted. Longer-chain tasks were not implemented or evaluated; both planned fresh domains retain the same two-hop ownership-to-storage structure. No official validation or multimodal task was evaluated.

## Actual cost and evidence boundaries

| Formal child process | CPU seconds | Wall seconds | Peak RSS KiB |
| --- | ---: | ---: | ---: |
| prepare | 3.673675 | 2.796809 | 339,628 |
| warmup | 581.705987 | 580.881965 | 1,170,584 |
| continue | 867.923769 | 867.146353 | 1,199,692 |
| Total / maximum peak | 1453.303431 | 1450.825126 | 1,199,692 |

These process receipts cover child startup through exit, restore/setup, training, diagnostics, hashing and serialization. Inner fit totals and physical panel timers are nested breakdowns and must not be added again. Nine continuation fit calls total 816.584280 CPU seconds; the nine arms use 7,500 optimizer updates / 120,000 candidate exposures.

The posthoc ablation child costs 13.590302 CPU / 12.727452 wall seconds, peak RSS 1,485,312 KiB. It is excluded from the formal total. Historical base fitting and old token-cache generation are also separate; reused work is not free. Independent audits, test/fmt runs, plots, packaging and repository operations are not included in the formal training total. Full training/backward FLOPs and individual-case latency were not measured.

Independent stdlib audits replay all nine warmup comparisons (three historical), nine continuation receipts and 27 continuation panels, full sampler/exposure accounting, semantic truth, costs, freeze chronology and closed gates. Initial FP32 sidecars are independently decoded. Later bounded Torch-ZIP decoders additionally verify names, shapes, counts, finiteness and both parameter digests for all nine actual warmup checkpoints and nine actual continuation checkpoints. This extends the original protocol auditor capability without changing training. It does not attest gradients, measured clocks or actual neural execution from bytes alone.

The supplemental ablation audit checks panels, changed-parameter provenance, truth and costs. Feedback/revision auditors and their mutation fixtures are implemented and tested, but have no actual feedback/fresh outputs to audit in this run. Audit PASS means evidence consistency, not learning qualification.

525 base regression tests passed, including native controls with real local binaries. The 18 newly added downstream audit tests also passed in a separate run. Required `just fmt` completed after edits; tests were not rerun after formatting. No hosted CI was consulted.

## Reproduction and next engineering target

Use `BRIDGE_V6_PROTOCOL.md`, immutable runtime ref, `design.json` and the allowlisted raw evidence bundle. Process receipts preserve exact phase argv and all actual costs. The bundle contains all selected completed weights, raw probabilities, learning curves, initial bytes, actual historical baselines, independent reports and supplemental scripts. It excludes the historical Encoder snapshot and token cache; their identities/hashes remain bound and they must be restored for a neural rerun. Do not rerun into the existing once-only output directory.

The next intervention should address retention/readout optimization while preserving the successful cross-fact representation. Freeze a separate continuation protocol and compare retention mechanisms with the same natural sequence, binding exposures and complete old-task gate. Only a passing primary may open feedback and fresh evaluation. This run does not authorize production promotion or relax the gate.
