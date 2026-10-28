# Natural same-event joint generation: frozen 8/64-update studies

The implementation and both complete experiments ran. Neither study passes the declared improvement or natural-semantic acceptance gates. The direct output-gradient paths and same-event media delivery are verified; these results do not establish a natural all-modality foundation model or an optimal output portfolio.

## Task and data

The source is the official [DeepMind Perception Test](https://github.com/google-deepmind/perception_test), distributed as real-world MP4s with original audio and action/sound annotations under CC-BY 4.0. Attribution: Patraucean et al., *Perception Test: A Diagnostic Benchmark for Multimodal Video Models*, NeurIPS 2023. The official train archive generation is `1685446268139925`; the code reads its ZIP64 central directory and only the preselected public HTTP ranges. Every downloaded source member has its own SHA-256, size and ZIP CRC. No source download is silently substituted.

The bounded task uses a one-second natural event. The model sees the first and last quarter-second of synchronized video/audio, and jointly emits the missing middle half-second: a 16-token action/sound label caption, a 4,000-sample 8-kHz waveform, a 32×32 keyframe, and four 32×32 frames at 8 fps. Image frame 4 and video target frames 2–5 refer to the same event interval. The caption is an annotation-derived label sequence; this is not open-domain fluent narration or speech synthesis.

| Study | Train sources/events | Development sources/events | Calibration sources/events | Qualification sources/events |
|---|---:|---:|---:|---:|
| First: 8 actual updates per arm | 32 / 102 | 8 / 27 | 8 / 23 | 16 / 47 |
| Expanded: complete 8/64 grid | same 32 / 102 | same 8 / 27 | 16 / 52 new | 32 / 93 new |

All 48 expanded holdout source IDs exclude every one of the original 64 videos. Across both studies there are 112 unique source byte hashes. Inherited training/development tensors are bitwise identical. Sampling uses a frozen SHA-256 priority among eligible original train videos no larger than 5 MB, with at least two visible action/sound overlap events. Each source contributes at most four nonoverlapping windows. These are project partitions of the official train split, not official benchmark test results. Participant identities are unavailable, so video-source separation does not establish participant separation. Small-file selection also limits representativeness.

## Trainable path and actual output gradient

`NaturalPortfolio` extends the research `NeuralPortfolio` shared-state/coupling convention: visual and audio encoders, fusion, initial modality states, two shared recurrent transitions, four trainable modality adapters, and four trainable emissions. This natural port is distinct from the native owner binary exercised by the runtime work package. It does not claim native-owner trajectory equivalence.

A discarded 40-update pilot verifies finite optimization and full gradient paths. A 240-update supervised warmstart uses media/text proxies. Both risk-neutral and entropic arms then restart from exactly that same warmstart and use the same Adam settings, batches, random seeds and emission law. The first study uses eight actual-return updates per arm; the expanded study uses 64. All candidates are reported, including candidates not selected by development performance.

Gaussian image/video/audio samples and categorical text samples are drawn before quantization. Training computes their log density and scores actual reopened PNG, int16 WAV, FFV1 Matroska, and UTF-8 bytes. The gradient estimator uses the complete joint-batch likelihood and a previous-batch baseline, retaining cross terms for shared execution costs. Every encoder/fusion/state/transition/adapter/emission group has finite, nonzero actual-return gradients and changed parameters. The supervised warmstart is explicitly a proxy; it is not relabeled as an exact delivered-NDU gradient. Conditional emission noise factorizes given the shared state; joint rewards and a shared state alone do not prove a rich correlated semantic generative law.

## Frozen objective, continuation and cost

The four post-codec quality scores use caption token F1, image/video reference error, and waveform/spectral audio error. A minimum plus geometric-mean utility makes a missing or poor modality costly; a keyframe/video disagreement term checks a within-bundle relation. It remains a reconstruction utility, and independent semantic-observer adequacy is a separate required acceptance gate.

For risk gamma 2, the selected objective is the population certainty equivalent of net return. Sources receive equal mass; events within each source and output draws within each event receive equal mass. Training samples sources then events uniformly. The gamma-zero arm is an equal-budget expected-return comparator; every final evaluation uses the common gamma-two objective. For deployment evaluation, inference, actor, codec, readback and scoring self/child CPU is measured and charged at the predeclared 0.001 utility per CPU-second, subject to the cached-feature exception below. The first actor used precomputed public features; the expanded actor and nearest-source path explicitly charge online feature computation. Fixed-architecture timing is treated as conditionally exogenous: a likelihood-ratio emission gradient does not estimate arbitrary derivatives of platform timing with respect to neural parameters.

The post-study [selected-action audit](results/NATURAL_SELECTED_ACTION_AUDIT.json) also found a physical-cost scope difference in training: draw-call timing was excluded, and shared batch-forward CPU was charged to both emission replicates. Identical profile hashes therefore do not establish exact per-output physical-cost identity between those historical training and deployment receipts. Total measured run CPU remains separately reported. The later [native whole-trajectory diagnostic](native_joint_gradient.md) freezes a corrected, separately bound execution contract; it does not rewrite these studies or their failed decisions.

The expanded actor has seven candidates rather than five, so it receives a new continuation hash/profile. Objective, scorer, gamma, cost unit, utility bounds and modality requirements are unchanged. Original checkpoints retain their original training profile and are explicitly migrated for expanded evaluation. The expanded 64-update training and deployment use the same new profile. Checkpoint weights, actor weights, candidates and source IDs are sealed before the first qualification score.

| Identity | SHA-256 |
|---|---|
| Original source protocol | `4c6565de42a45ffa55ca150baee9053eb7c8efb246db1dfd98920b5e29b34394` |
| Original profile | `bb9f08dca8ad9e7854990219c695685a05f90d7c711e0418d0dbd0a6df9da273` |
| Expanded source protocol | `ac8861da9884414983f8adce055bfd5352b658680f6a86cfc4bbccc599d05473` |
| Expanded profile | `12ca5adbc8829ef063984e6c0c0f3006c6616cf2965eb515a56b63ddba87d9e7` |
| Expanded qualification seal | `6dfc8145d408cea555959844c5c48825d7724690fa366e22d129e968045c49e8` |

## Qualification results

Each event has two deployed output draws. Interpolation/copy and nearest-training-source retrieval are strong deterministic controls, not claims of learned generation. The neural fixed control is the warmstart with mean/argmax delivery. The actor chooses one whole bundle before generation using a development-fitted positive conditional-moment predictor. It never chooses modalities after seeing reference scores.

| Arm | First study CE, 16 sources | Expanded fresh CE, 32 sources |
|---|---:|---:|
| Interpolation/context copy | 0.535563619 | 0.510778409 |
| Nearest training source | 0.204670330 | 0.258481872 |
| Fixed neural mean/argmax | 0.507338209 | 0.493485562 |
| Expected return, 8 updates | 0.422807055 | 0.423106631 |
| NDU, 8 updates | 0.423844597 | 0.423067599 |
| Expected return, 64 updates | — | 0.423132777 |
| NDU, 64 updates | — | 0.423833547 |
| Selected-action actor | 0.304634409 | 0.395415257 |

Original development selected `ndu_8` as the primary risk checkpoint and `interpolation` as the strongest fixed comparator before expanded qualification. The 64-update candidate remains fully reported. Paired intervals resample original video sources, not individual frames/crops or training seeds.

| Expanded contrast | CE difference | Source-cluster 95% interval |
|---|---:|---|
| NDU8 − expected-return8 | -0.000039032 | [-0.000139584, +0.000014537] |
| NDU64 − expected-return64 | +0.000700770 | [-0.000019523, +0.002255154] |
| NDU8 − interpolation | -0.087710809 | [-0.117669833, -0.063124686] |
| NDU64 − interpolation | -0.086944862 | [-0.116839308, -0.061877510] |
| Actor − interpolation | -0.115363152 | [-0.167307956, -0.062892516] |

The NDU64 versus same-budget expected-return interval includes zero, while both NDU candidates and the actor are below the strong interpolation control. Increasing actual-return updates therefore does not establish a risk-objective benefit here. The high image/video reconstruction scores largely reflect this short, predictable infilling task; they must not be interpreted as natural semantic generation.

On 16 independent calibration video sources, the small source-trained semantic audit reaches action accuracy 13.462% and sound accuracy 46.154%; both miss the frozen 60% adequacy thresholds. The strict generated joint-semantic check is 0.000%. This is an inadequate observer and a failed semantic gate, not evidence of validated zero semantic ability under a general judge. Cross-source audio/text mismatches lower joint utility by 0.054712 on average, showing that matched-event scoring is sensitive to pairing, but not rescuing semantic qualification.

Selected-action moment calibration predicts mean moment 0.396426 versus observed 0.428345; its bias passes the declared coarse 0.1 bound. This limited point calibration does not prove accurate extreme tails or optimal action selection. One training seed is used; source-bootstrap intervals do not quantify training-seed variation.

## Evidence and verification

Both studies are retained in full. There were 1,152 actual four-output training bundles and 2,052 qualification bundles. All 8,208 qualification artifacts are retained, including failures if any; these runs recorded no failed deliveries. The independent validator checks every saved artifact SHA-256, reopens and rescores a stored bundle for every evaluated arm, reloads checkpoints and verifies parameter identities, verifies the executed-source snapshots against frozen hashes, checks cost charged once, checks source-byte uniqueness and split isolation, and compares inherited train/development tensors bitwise. Every check passed. Training output bytes were transient; step returns, seeds, algorithms and resulting checkpoints are retained.

The first run used 201.625 CPU-seconds and 222.825 wall-seconds; the expanded run used 507.746 CPU-seconds and 520.957 wall-seconds, excluding original dataset acquisition/preprocessing. CPU billing includes child codecs. Resource contention makes these host timings descriptive. Runtime versions are recorded in `results/NATURAL_RUNTIME.json`.

Raw official MP4 members were streamed, SHA-256 recorded, decoded, and removed because of temporary storage limits. Complete compact aligned tensors, all qualification bytes, checkpoints, source allocation/range receipts, annotations, and exact executed code are in the evidence archives. Official generation/ETag checks prevent recovery from silently accepting a changed archive. The current recovery reader additionally rejects ignored HTTP ranges before reading a potentially huge body; the exact code used by each completed study is preserved separately.

## Reproduction

Run from the repository root with the recorded Python/torch/media dependencies. Choose new output directories for an explicit replay; a replay of consumed qualification sources is not a fresh confirmatory test.

```bash
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_data --assets /tmp/natural_assets
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_run --assets /tmp/natural_assets --output /tmp/natural_results
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_expand_data --original /tmp/natural_assets --assets /tmp/natural_expanded_assets
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_expand_run --assets /tmp/natural_expanded_assets --output /tmp/natural_expanded_results --first-study /tmp/natural_results
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_validate --root /tmp
```

The next scientific requirement is a stronger natural generator and independently adequate semantic evaluator, together with lower-variance actual-return learning and better conditional moment estimates. The present experiment provides a reproducible negative qualification and an actual trainable four-output path; it does not warrant deployment as an all-modality generative foundation model.
