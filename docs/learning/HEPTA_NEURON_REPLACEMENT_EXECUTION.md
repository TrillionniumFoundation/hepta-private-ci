# Hepta Neuron: five-model replacement, six-stage shadow-only experiment

**Authority:** SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. These scripts may reject invalid claimed evidence; they cannot select, admit, deploy, authorize or release any model. No stage is declared production qualified by these checks. Inference-control, signed final-use, Artifact CAS and ledger owners remain authoritative.

## Immutable candidate scope

The exact Git revision and published LFS weight SHA256 for each arm are in [replacement_models.json](../../qa/stem-bakeoff/replacement_models.json).

| Phase | Model | Execution scope | Parameter class |
| --- | --- | --- | --- |
| Baseline | convaiinnovations/laya | Full typed DecisionModel, not Encoder alone | 421M |
| Baseline | convaiinnovations/laya-typed-decisions | Full typed DecisionModel | 421M |
| Direct substitute | convaiinnovations/laya-multilingual | Full typed DecisionModel | 322M |
| Encoder comparison | Snowflake/snowflake-arctic-embed-m-v2.0 | Frozen Encoder + newly trained independent Head | ~305M |
| Encoder comparison | microsoft/harrier-oss-v1-270m | Frozen Encoder + newly trained independent Head | ~270M |

Do not count P37's laya_encoder_only as a full-Laya decision baseline. Train new compatible Heads for Arctic and Harrier; bind each tokenizer, intended pooling (Harrier last token), normalization, precision, projection-to-512 if used, rank, Head weights, runtime, device and frozen generation. A valid Encoder forward is not a policy forward. Perform separate legal/license approval before weights enter any privileged runtime.

The metadata auditor checks Hugging Face's exact pinned revision, upstream file size and published LFS digest, without downloading checkpoint bytes or executing inference; no independent publisher signature, model quality or license use is certified by this check.

## Frozen, separated data

Use the same tasks, labels, class order, candidate options, fixed action/state rendering and common training budget/seed for every arm. Freeze dataset bytes, source groups, task schema and five cohorts: train, calibration, future_1, future_2 and non-overlapping OOD. Keep final-window labels unavailable to training/calibration. Supply independent typed-policy and multilingual data; the old UCI News Aggregator 2014 historical splits cannot prove fresh future performance, foundation pretraining isolation or any Laya action/score capability. Encoder alternatives also require separate relevance judgments for nDCG@10 and MRR@10.

## Gate-by-gate requirements and actual gaps at P37 dac730dc8

| Gate | Required executed evidence | Status |
| --- | --- | --- |
| 1 Full baselines | Verified complete 421M English & Typed weights, tokenizer/config/Head/decision forward, fixed real tasks and independent evaluation | OPEN: only full checkpoint's Encoder-only extraction previously measured |
| 2 Multilingual 322M | Same full typed tasks, multilingual splits and actual resource comparisons | OPEN |
| 3 Arctic/Harrier | Complete loaded weights, real frozen Encoder forward, independent trainable Heads with identical data/step count/seed, reloaded artifacts, retrieval evaluation | OPEN |
| 4 Calibrate/safety | Frozen calibration split, class imbalance/confusion/positive recall and AUPRC, Brier/ECE10/NLL, selective accuracy/risk and OOD false-accept at predetermined coverage, independent future windows and negative-transfer test | OPEN: P37 acceptance coverage near zero and multiple Head temperature values reached lower search bound |
| 5 Resource scale | Independently allocated 64/256/1024/4096 logical private Heads, actual concurrently active count, original >=100 latency samples per scale for descriptive p99, CPU/GPU/RSS/VRAM/throughput/energy, loaded device and runtime identity | OPEN: P37's measured CPU Head fanout is not production p95/p99, concurrent GPU throughput or energy |
| 6 Lifecycle | Real owner Artifact CAS, predecessor checkpoint migration, CNS cutover, supervisor generation fence, fault-injected crash/reopen, rollback and independently verified old-generation final-use denial with signed receipts | OPEN |

A SHA string is not proof that an operation really happened. Predicted probabilities are re-scored by the shadow preflight, but claims about weights, device, temporal validity, signed receipts and actual physical effects need external verification by the registered owner.

## Commands

From repository root:
1. Run deterministic negative tests: python3 -m unittest discover -s qa/stem-bakeoff -p 'test_replacement_*.py' -v
2. Run live pinned-Hub manifest audit only: python3 qa/stem-bakeoff/replacement_metadata.py --out /tmp/hepta-hub-pointers.json
3. Assert conservative posture: python3 qa/stem-bakeoff/replacement_gate.py --assert-no-production
4. After an independently executed five-arm measurement bundle exists, run: python3 qa/stem-bakeoff/replacement_gate.py --evidence /path/to/actual-evidence.json

The gate's best result for complete *self-reported* evidence is REVIEW_REQUIRED; it **always** reports all_six_production_blockers_closed=false and production_activation_allowed=false, pending independently verified signer/host evidence. Do not construct fake examples and claim that they are real model results. Use P37's real_encoder.py, cell_head_training.py and real_head_fanout.py as the research base only after extending the schema and loading the full five-model profile; pin code and dataset to that execution commit. Do not silently change or overwrite any older measured result.

## Existing evidence and blocked acceptance

P37 Draft [PR #3110](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3110), exact commit dac730dc8ddbd96d87f6dc0c5eb94d3436d90a2b: four real checkpoint Encoder paths, trained Head tensors, and actual CPU 1/8/64/256/1024/4096 allocations. Stem shadow workflow 39721767926 was completed success; exact-SHA blocking-ci 39721767914 was completed failure. The P37 original three timing samples per scale cannot justify production p99 or energy/throughput. Its private Head training uses zero local state and did not train action, value and uncertainty or run complete Laya decision inference. No model is selected for production. Its Draft stacked base is not accepted main.

Stop on pinned model mismatch, missing full-policy action pathway, unknown license or runtime code, data leakage, post-hoc final split selection, unbalanced-class failure, low useful coverage, OOD acceptance regression, stale head generation, target-host timing not attested, absent independently validated Final-use signature, failed/queued/canceled exact-head blocking CI or missing operator acceptance. Preserve existing NDU and independent model selection/canary boundaries. No automatic merge, production grant or model release is permitted.
