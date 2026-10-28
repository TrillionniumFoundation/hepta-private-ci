# Natural v3: completed observer study and blocked generator qualification

The independently frozen semantic observers failed the original adequacy gate. Action accuracy was **21/64 (32.8125%)** and sound accuracy was **30/64 (46.875%)**. Each modality had to reach at least 60% and strictly exceed its training-majority baseline. The sound observer also fell below that baseline. The production entry guards rejected the downstream study. Qualified warmstart003 updates, actual NDU generator updates, policy-calibration episodes and qualification episodes therefore remain **zero in this study**.

The implementation and mechanism checks below are useful completed work. They do not establish an improvement in generated natural media, an adequate semantic reward, or an optimal output portfolio. The measured failure and the unused policy holdouts are preserved. [Result](natural_results/NATURAL_V3_RESULT.json), [calibration](natural_results/OBSERVER_V3_CALIBRATION.json), [actual entry rejection](natural_results/FAILED_ADEQUACY_ENTRY_CHECK.json).

## Fixed task and source allocation

The task reconstructs the middle two seconds of a four-second event window from the surrounding public audio/video context. The registered delivery contains a 112-pixel video at 8 fps, 16 kHz audio, one image from the reconstructed interval, and an action/sound template caption. Unavailable boundary context carries an explicit availability mask; target samples come from the original media. This is a bounded same-event reconstruction task. Static-image assessment remains fidelity and frame consistency, without an independently qualified image-semantic claim.

The full published vocabulary remains 63 action classes and 17 sound classes. A train-only coverage amendment added 128 generator-training and 128 observer-training original videos while preserving every original 768 allocation entry, retained event, role and holdout assignment. The added groups are disjoint. Source selection used frozen training metadata and deterministic tie ordering. It did not use development or holdout predictions.

| Role | Allocated original videos | Recorded use in this study |
| --- | ---: | --- |
| Generator training | 256 | Prepared; training-source mechanism fixtures; qualified warm003 not started |
| Observer training | 512 | All consumed by the registered observer fit |
| Development | 64 | Frozen observer candidate selection |
| Observer calibration | 64 | Frozen selected-observer adequacy evaluation |
| Policy calibration | 64 | Reserved; no preparation or execution recorded |
| Qualification | 64 | Reserved; no preparation or execution recorded |

Actual training coverage is **54/63 action and 14/17 sound classes** for the generator group, and **55/63 and 14/17** for the observer group. Full class coverage was not achieved. All 896 prepared original-video hashes were checked within the current roles and against the checked historical original-video records; no literal byte duplicate was found. That check does not establish perceptual uniqueness or participant independence. The source-use register preserves all 1,024 allocated IDs plus the historical 112 and additional 16 host-calibration exclusions for future source selection. [Coverage registration](data_coverage_v3_registration.json), [train/development source audit](natural_results/V3_SOURCE_AUDIT_002.json), [calibration source audit](natural_results/OBSERVER_V3_CALIBRATION_SOURCE_AUDIT.json), [source-use register](data_source_usage_register.json).

## Registered observer fit and independent result

The fit used 2,517 retained events from 512 original videos, with source-uniform weights. Eighteen predeclared candidates completed: four ridge choices and two MLP checkpoints for each of S3D action features, TSM action features and PANN sound features. The three MLP families completed 1,024 updates each, or 3,072 optimizer updates in total. No candidate was added after development or calibration predictions were seen.

Development selected S3D MLP1024 for action, at 22/64 (34.375%), and PANN ridge100 for sound, at 35/64 (54.6875%). The selected models and source bindings were frozen before calibration. The development gate already failed; the original independent adequacy evaluation was then completed without changing the selection, thresholds or score. [Development record](natural_results/OBSERVER_V3_DEVELOPMENT.json), [execution registration](natural_results/OBSERVER_V3_EXECUTION_REGISTRATION.json).

| Independent calibration metric | Action | Sound |
| --- | ---: | ---: |
| Correct / original videos | 21/64 | 30/64 |
| Accuracy | 32.8125% | 46.875% |
| Per-modality exact binomial 95% interval | 21.59%–45.69% | 34.28%–59.77% |
| Training-majority control correct | 10/64 | 37/64 |
| Training-majority control accuracy | 15.625% | 57.8125% |
| Labels absent from observer training | 0% | 0% |
| At least 60% and strictly above own control | Failed | Failed |

There is one calibration event per original video, so the reported source-uniform accuracy equals the ordinary fraction correct on these 64 events. Both observers were correct on 12/64 original-media events. That joint correctness is an observer diagnostic, not a measurement of generated-media quality. The binomial intervals assume independent original videos; participant independence is unknown, and the intervals are not a simultaneous multi-metric certificate.

An independent standard-library audit recomputed the counts, controls, intervals, label coverage and gates from the frozen predictions and reference receipts. It verified all 64 freeze/source/event/window bindings, 128 retained NPZ hashes, both selected checkpoint hashes and exact preservation of the original 768 allocation entries. It did not reproduce neural inference from the weights, download or decode the original MP4 files, or independently repeat the entire historical source audit. Its observation that reserved directories are absent applies to the checked study root and is consistent with the execution counters and failed-entry receipts; it is not a claim about every possible execution elsewhere. [Independent report](natural_results/INDEPENDENT_RESULT_AUDIT.json), [audit implementation](natural_independent_result_audit.py).

## What the implementation checks established

The generator implementation contains 945,091 trainable parameters, including raw-context encoders, projections of frozen public features, a shared transition, modality adapters and four emission paths. Its dense residual starts from a strong fixed interpolation prior. The normalized sampled law uses the registered pre-codec Gaussian emissions and categorical caption labels. No claim of natural generation efficacy follows from these implementation choices.

A full-size mechanism check executed two fresh joint draws on a training input. Each draw physically wrote and reopened text, audio, image and video. The sample hashes and advancing RNG chain matched the deferred score replay; both joint log-probability errors were zero. Actual and replay means matched exactly. The efficient fixed-interpolation path matched its original baseline outputs. This check used a fixed zero-vector public-feature test provider and did not execute the native owner or measure semantic adequacy. [Mechanism record](natural_results/NATURAL_EXECUTION_CHECK_001.json).

A separate microbatch/recovery fixture checked the actual proxy loss and Adam update on independent examples. The largest gradient difference was approximately 7.78e-8; the largest one-update parameter difference was approximately 1.58e-6. Model, optimizer, sampler and RNG recovery was bit-exact within that fixture. This supports the resource correction; it does not claim identical floating-point production trajectories for dense and microbatch execution. The interrupted older warm001/002 attempts remain recorded separately, including the last confirmed 256-update marker in warm002 and the absence of a full optimizer/RNG recovery point. [Recovery check](natural_results/MICROBATCH_RECOVERY_CHECK_003.json), [historical custody](natural_archive_index.json).

The unexecuted qualified training path now binds the task ontology independently of generator metadata, rejects used or differently frozen policy holdouts, preserves evidence for an initial failed emission followed by a successful retry, and pins the complete generator/actor/observer/emission/runtime composition. Its deferred replay uses the actual pre-codec samples at the same parameters, without resampling or replacing the actual return. The registered two-episode estimator uses the complete joint trajectory score, the mean actual moment and a baseline from prior updates only. These contracts have explicit limits: direct physical-time dependence on parameters outside the sampled trajectory remains a conditional-exogeneity assumption, and physical CPU has no enforced future upper support. No rigorous future exponential-moment tail certificate is asserted.

## What remains open

The semantic adequacy blocker is still open. Current calibration labels all occurred in observer training, so missing classes cannot alone explain this measured failure. A training-only annotation diagnostic also found multiple labels in some windows. Those proportions neither prove a top-one accuracy ceiling nor identify the cause of the prediction errors. There is no paired cross-study comparison supporting an improvement over the old observer cohorts.

The proposed whole-window multi-label task is a separate, unregistered proposal. It describes frozen label sets, precision and recall requirements that penalize selecting everything, cross-modal event checks and fresh source allocation. It does not change this study's labels, original 60% gate, candidate selection or failed result. Any execution would need its own task, observer and policy identities before new holdout use. [Training-window diagnostic](natural_results/TRAINING_WINDOW_AMBIGUITY_V3_SUMMARY.json), [separate proposal](semantic_multilabel_proposal.md).

Because the reward observer did not qualify, this study supplies no new evidence that actual NDU training beats the strong interpolation prior, a matched mean objective, a fixed policy or a lower-overhead runtime. Those efficacy questions, the semantic observer requirement and the strict physical-cost tail requirement remain explicit scientific or operating constraints. They cannot be marked complete by changing a score after seeing the calibration result.
