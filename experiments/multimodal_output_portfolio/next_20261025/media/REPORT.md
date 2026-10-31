# Next media experiment: actual waveform learning and independent qualification

## Current decision

The frozen V3 abstention ensemble has now passed its once-only independent-from-development qualification: **259/300 registered real recordings (86.333%)**, above the unchanged 85% point gate. The selected input classifier also passed with **273/300 (91.000%)**. The shared cohort contains 298 unique WAV byte identities and 147 speakers. Its two endpoints are correlated, and the two Whisper components individually remain below the gate (base 249/300; small 243/300). Only the registered ensemble is qualified for the next output evaluation.

The earlier standalone V2 failure (both components 244/300 on a different 98-speaker cohort), all interrupted runs, and both failed development candidates remain intact. The repaired generation candidate passed its original development gates before this new cohort was opened. No model, parser, threshold, source, or commitment rule was changed using the new results. The final 128-pair/32-writer media confirmation has now completed: all 640 actual four-modal outputs were generated and every original numeric sample gate passed. Image/text/audio/video/audio-video input routes achieved 127/128, 128/128, 114/128, 117/128, and 125/128 strict joint successes respectively. This is a finite ten-class, canonical-voice and constructed-motion result, not a foundation-model or NDU-superiority claim.

## What was implemented and trained

`WaveformStudent` is a 1,040,704-parameter network with `Linear(10,64)`, Tanh, `Linear(64,16000)`, and Tanh. Its input is a predicted ten-digit semantic simplex; its output is an actual two-second, 8 kHz waveform. It was trained for 2,000 steps against ten phase-preserving Piper teacher waveforms, one per digit. Teacher synthesis is restricted to training. Inference uses the student parameters and predicted semantic state and does not retrieve teacher recordings or invoke a TTS service. The checkpoint is `5dc512d4b8d1c9a91a4660cd7383fd2db136df72bc84054d98c4d99f6afc9756`.

The teacher fit was numerically extremely close: waveform SNR was 96.3–101.6 dB with a 1e-12 error floor, and the student weights changed with nonzero gradients. This establishes ten-condition imitation, not speech generalization. This decoder can memorize its ten conditions and canonical voice. It is not the original VAE, an arbitrary-vocabulary speech model, or evidence of naturalness judged by people. Student training took 35.978 s wall and 34.748 s CPU; audit ASRs were not loaded during training.

The audio ingress classifier was fine-tuned from the existing model on 3,000 real, official-training Speech Commands recordings, with 300 recordings per digit from 1,301 speakers. The 2,000-step recipe used fixed time/frequency masking. On the initial validation cohort it recognized 277/300 recordings (92.333%), passing its unchanged 85% ingress point gate. The checkpoint is `174dddad0db36ac09cc768a1a488401aa073499d407bfa97b1e5da7a3ae888e4`. Training took 94.261 s wall and 91.591 s CPU. This classifier is the input path, not an independent output naturalness assessor.

The existing image/text generator, trained motion head, and video ingress are reused. `runtime.py` exposes a differentiable waveform module and actual waveform reward interface to the separately scoped joint mean-versus-entropic training experiment. Claims about that joint experiment must use its own matched-arm results; waveform distillation alone is not evidence for an NDU training advantage.

## Acoustic diagnosis and changed experimental condition

The earlier acoustic decoder predicts log-magnitude spectra and reconstructs phase using a bounded Griffin–Lim procedure. Its prior fit includes magnitude losses and a frozen mel-classifier reward. The historical independent Whisper result was 22/64 generated pairs versus 55/64 real pairs. Those results remain unchanged. A magnitude/classification objective and approximate phase reconstruction leave acoustic failure modes that the mel observer need not detect. This is a plausible mechanism, not a causal attribution from the current experiments.

The new student directly fits the physical waveform, preserving the teacher signal's phase. It also changes the voice, capacity, and presentation budget. Each output event lasts two seconds, for a four-second output with two digit events; the original input remains two one-second events. Any improvement must be interpreted under this explicitly changed presentation profile. A padded legacy VAE route is available for a same-clock diagnostic, not as a renaming of the old two-second benchmark.

## Data custody and independent roles

The official Speech Commands v0.02 archive was streamed from:

<https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz>

The entire stream was hashed: 2,428,923,189 bytes, SHA256 `af14739ee7dc311471de98f5f9d2c9191b18aedfe957f4a6ff791c709868ff58`. Original LICENSE and README are retained; the dataset is credited to Pete Warden under CC BY 4.0. Every retained recording has its original archive path, byte size, and SHA256. Recording selection used source metadata and fixed hashes, not measured acoustic performance.

The official training, validation, and test split speaker IDs do not overlap. The frozen local allocation is `AUDIO_SOURCE_ALLOCATION.json`, SHA256 `35862507212b97bc02bc1506070a31863f830e3c9e7747e5f3187ab2e6702fe5`:

| Role | Recordings | Speakers | Use |
|---|---:|---:|---|
| Fit | 3,000 | 1,301 | Audio ingress training |
| Initial qualification | 300 | 133 | Ingress qualification; subsequently observer development |
| Media confirmation | 320 | 32 | One recording per digit and speaker; the fixed confirmation is complete |
| Reserved joint | 240 | 24 | Separate speakers, for the joint experiment |

Reserved output tasks require speakers with the complete ten-digit vocabulary, selected from metadata. This restricts the study population. For media confirmation, each of 32 image writers is paired with one of 32 speech speakers, giving 32 independent writer/speaker clusters. The joint experiment has 24 speech speakers; repeated speakers must be accounted for in its inference rather than treating every image pair as independent.

The fresh event-observer qualification excludes **all** 133 earlier qualification speakers. Its frozen source allocation, `EVENT_QUALIFICATION_SOURCES.json`, has SHA256 `2c9aa271394402a21dea81a34f6df4fd3afb9e86bd213f9b2dbd1de1ddabba75`: 300 recordings, 30 per digit, from 98 new official-validation speakers. Their original recording bytes were restored and verified in a second full-archive streaming pass. No source overlap with the fit or reserved test roles was introduced. Unknown overlap with pretrained Whisper training data cannot be ruled out and is not claimed to be absent.

The new image source allocation and exclusion of all original MNIST source identities/writers are owned by `../sources.py` and `../SOURCE_ALLOCATION.json`. The media role reserves 128 pairs from 32 new writers. Existing development images are used for engineering checks; they do not increase independent confirmation sample size.

## Observer development and qualification history

All observers receive only actual audio bytes and a public event clock. Ground truth is attached after observation. Each 8 kHz PCM event gets a fixed 0.2-second zero pad on each side before ASR. There is no target prompt, candidate-digit vocabulary, or label-based transcript repair. The strict parser requires exactly one recognized digit; the generated carrier additionally permits only the fixed words `the`, `digit`, and `is`. Whole-output observations retain event order.

The pretrained models are `Systran/faster-whisper-base.en` at revision `3d3d5dee26484f91867d81cb899cfcf72b96be6c` and `Systran/faster-whisper-small.en` at revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. Each manifest and actual model asset is hashed. They are two sizes from the same model family; statistical or training-data independence is not claimed. Runs use CPU int8, one CPU thread, and one worker.

| Stage | Base | Small | Disposition |
|---|---:|---:|---|
| Event development, 60 recordings / 50 speakers | 50/60 (83.333%) | 46/60 (76.667%) | Development only; both below .85 |
| Fresh qualification, 300 recordings / 98 speakers | 244/300 (81.333%) | 244/300 (81.333%) | Completed; both FAIL .85 |

`EVENT_SELECTION_V2.json` froze base as primary based on the earlier development result, before the new 300 were scored. The new qualification was completed once with no parameter, parser, model-selection, or threshold changes. The process returned zero, with 1,263.981 s wall, 1,624.788 s user+system CPU, and 940,024 KiB peak RSS including imports and final output writes.

A descriptive 5,000-resample speaker-cluster bootstrap gives accuracy intervals of [75.59%, 86.79%] for base and [75.59%, 86.20%] for small. These are descriptive intervals, not replacement qualification gates. Each model's 56 failures were strict abstentions, with zero incorrect accepted digit predictions. The two models were jointly correct on 228 recordings, each uniquely correct on 16, and jointly abstained on 40. A union rule computed after these outcomes would be a new development-selected candidate and would require another untouched cohort; it is not independently qualified by these 300. Recomputed counts, confusion matrices, and cluster details are in `OBSERVER_QUALIFICATION_RESULTS.json`.

Three earlier whole-utterance attempts were interrupted with exit code 137 under concurrent ASR memory pressure. Their completed saved rows (100, 23, and 3 primary candidate rows respectively) and process-failure receipts are retained. They are incomplete development attempts, not successful qualifications. Subsequent ASR execution is serialized. The observed cgroup OOM-kill count was three; no unsupported cause is assigned to other resource anomalies.

## Completed pre-repair development execution

`/tmp/hepta-ndu-next-media-cache/development-001` completed 60 newly generated physical four-modal outputs from the same twelve old-development tasks, plus ten explicit conditional-head cases and all five physical negative controls. The whole process returned zero in 96.775 s wall and 110.840 s CPU, with 1,114,556 KiB peak RSS. It audited eleven distinct actual events with both component models (22 component transcriptions) and made 137 exact-event cache hits. These are engineering/development results, not independent confirmation.

The conditional audio census scored 18/20 events with the registered base primary and 20/20 with small; the only base failure was an abstention for digit five. All 200 conditional video frames were recognized correctly. Both original conditional-head thresholds therefore pass. All five negative controls were rejected nonvacuously: silence, exchanged audio events, exchanged video events, repeated frames, and a physically missing video modality.

| Input route | V2 actual strict joint | V3 fixed-rule recombination of those same actual observations |
|---|---:|---:|
| Image | 7/12 | 8/12 |
| Text | 11/12 | 12/12 |
| Audio | 7/12 | 8/12 |
| Video | 10/12 | 11/12 |
| Audio and video | 9/12 | 10/12 |

The latter column is explicitly post hoc development recombination under the already registered target-free V3 rule. It is not a new source sample, new waveform generation claim, or independent ASR qualification. Both versions still fail the per-route 75% joint gate for image and audio.

The audio error mechanism is identifiable without another model run: prior ingress predictions for exactly the same recording SHA already make all four failed audio-pair mistakes, and the final generated semantic choices match those predictions. The four expected/predicted pairs are [3,8]→[3,3], [8,0]→[8,2], [2,3]→[8,3], and [3,6]→[3,8]. Thus these failures precede codec serialization and output speech generation. In the image route, text/image/audio semantics are correct on eleven tasks; strict video is correct on eight because a few translated boundary frames change the independent image observer's digit decision. `INGRESS_FAILURE_DIAGNOSIS.json` and `DEVELOPMENT_V3_RECOMBINATION.json` retain this decomposition.

A separate `repair/` scope now implements two fixed fit-only ingress seeds, explicitly developmental model selection, and a canonical semantic commitment before output decoding. It preserves every previous frozen source and selection. Its scope deliberately excludes preserving input handwriting style. The completed repaired fits and actual development executions are documented below; independent confirmation is reported in its own section below. The prospective plan is in `repair/PLAN.md`.

## Prospectively registered V3 continuation

After preserving the V2 failure, a new target-free ensemble was registered in `ENSEMBLE_SELECTION_V3.json` (SHA256 `f810b6bfaf5b2e3c33cec3161646ef891076e0281eae4958599ce0910c22658c`). It accepts the common digit when both models return the same nonempty prediction, accepts the sole digit when the other model abstains, and rejects both conflicts and double abstentions. The component ASR model weights, transformations, and strict parsers remain byte-identical to V2. The 121 possible pairs drawn from abstention and ten digits were checked against this fixed rule before new scoring.

Before any new scoring, static review identified a qualification-entry guard that checked frozen asset paths but did not bind the actual `--assets` argument to them. The initial 54-pin selection and its source files are retained byte-for-byte. A 58-pin identity-only amendment, `ENSEMBLE_SELECTION_V31.json` (SHA256 `bf70bd1d69ce42c0f2161eb589b7dcf061d6c7a51f68b16c88a322bfbacdbaaf`), adds new qualifier/evaluation/freeze files. The qualifier now verifies both actual model-manifest paths and every actual model-asset path and SHA before opening qualification source bytes. It changes no ensemble rule, model, transformation, parser, source cohort, or numeric gate.

The V2 300-recording result is development evidence for this new selection and is never rebranded as independent V3 qualification. A fresh official-test allocation freezes 300 recordings from 147 speakers, excluding every previous validation/development speaker and all 56 speakers reserved for media and joint confirmation. The candidate pool contains 185 nonreserved official-test speakers. `ENSEMBLE_QUALIFICATION_SOURCES_V3.json` has SHA256 `df08fa48f9627ab8d828d267599b9bcebb59470d020e4f70a7caff9dfaddb67c`. The 85% point gate is unchanged. A final choice of ensemble, parser, or threshold after seeing this fresh cohort would require yet another genuinely untouched qualification and is prohibited by this registration.

The actual old-development conditional waveform/video probe has met its original 80%/90% gates (90% audio, 100% video). The original whole-route candidate failed; the later early-commitment candidate below has now passed the original development gates. All 300 fresh source recordings have been verified by original SHA, including eleven restored from another complete official-archive streaming pass. The once-only shared-cohort qualification has now completed and is reported below; no candidate choice was changed using its results.

## Repaired candidate: fixed training, a retained failure, and an identified bridge defect

The two additional ingress fits have completed using only the original 3,000 fit recordings. Each ran exactly 2,000 steps under seeds 23179 and 23197. Their whole combined process took 181.346 s wall and 181.772 s CPU with 609,260 KiB peak RSS. The original 300-recording cohort and the exact same twelve old tasks were explicitly used as development selection, with no claim of fresh sample size.

| Registered input-head candidate | Old 300 recordings correct | Old twelve audio pairs correct | Selection eligibility |
|---|---:|---:|---|
| Original seed | 277 | 8 | Failed pair gate |
| Seed 23179 | 279 | 9 | Passed both gates; selected |
| Seed 23197 | 276 | 8 | Failed pair gate |
| Equal mean of all three | 277 | 8 | Failed pair gate |

The selected input head is therefore a **single** trained member, not an ensemble improvement. Its wrapper checkpoint is `5c10b1ca0830879464f5d29219236fe88cb9422f7f630cb8dc7cc7b5844b3bbb`. The independent ASR observer remains a separately defined two-model abstention ensemble. These two uses must not be confused.

The first repaired actual generation run moved output rendering to a canonical state derived from the public predicted semantics. This eliminated the old image-route video errors: image, video, and audio/video routes each scored 11/12 strict joint tasks, and text scored 12/12. Audio nevertheless remained 8/12, so this candidate's whole-route development gate **failed**. Its 60 newly generated outputs, conditions, negatives, and 43.009 s whole-process receipt are retained.

A read-only check localized the remaining discrepancy. On the same physical decoded PCM input, the selected classifier correctly predicts [8,0]. Passing its soft probability vector to the existing `ingress_state` changes the second digit to 2 immediately, before either refinement or coupling. Thus this particular error is introduced by the learned semantic bridge, rather than by PCM quantization or by the selected classifier. The diagnostic preserves every stage's probabilities and verifies unchanged model parameters.

A separate prospective `repair/bridge_v2/` candidate therefore commits the audio/video encoder or fused argmax before entering that core. It also retains the full original component and fused probability vectors in a separate `encoder_belief` field. This fixes the class for the decoding pass and gives up subsequent soft-core corrections. The retained probabilities remain the input-uncertainty information; no calibration improvement from hard commitment is claimed. Image/text encoding retains its existing route. All earlier source bytes, protocols, and failures remain unchanged, and no additional model was trained.

The resulting actual development run completed all sixty four-modal outputs and passed every original sample gate:

| Route or check | Result |
|---|---:|
| Image-input strict joint | 11/12 |
| Text-input strict joint | 12/12 |
| Audio-input strict joint | 9/12 |
| Video-input strict joint | 11/12 |
| Audio/video-input strict joint | 11/12 |
| Conditional speech events | 20/20 |
| Conditional video frames | 200/200 |
| Physical negative controls rejected | 5/5 |

Whole-process cost was 45.559 s wall, 45.548 s CPU, and 565,168 KiB peak RSS. Every WAV/PNG/MP4/caption was generated and physically reopened. ASR observation reuse involved 148 exact-PCM event cache hits and zero new ASR executions; original cold ASR costs remain separate. An unknown waveform hash fails closed. The actual first old-development image-input example is [9,2]; it was selected by fixed case order, not by looking for an especially successful output.

The final fresh qualification protocol, `repair/bridge_v2/QUALIFICATION_PROTOCOL.json`, has SHA256 `cd7be102f8c624caa7bac560866ae00e0f852627927121ba93c328392fad7114` and 411 pinned dependencies. It fixes the selected classifier, the repaired code, the executed development receipts, the V3.1 observer, and all 300 actual new recording paths/SHA values. The input-classifier and ASR qualifications share **one** cohort of 147 speakers and are correlated endpoints of that cohort, not two independent experiments or 294 independent clusters. Metadata-only review also found 298 unique WAV byte identities among the 300 registered rows: two within-speaker duplicate pairs belong to the same speaker. The frozen 300-row denominator is retained, with dependence handled at speaker level; neither endpoint is treated as 300 independent observations. Each has the unchanged 85% point gate. The fixed shared-cohort qualification completed successfully; its scores have not been used to change any rule or model. The final 128-pair media source was opened once under the subsequent frozen confirmation protocol, after both gates passed.

## Dependency continuity addendum before formal source access

An independent static review found an identity-chain omission while the unchanged fresh qualification was already executing. Of 46 recursively imported local Python files (including package initializers), 21 were in the original 411-pin qualification protocol and 25 older helpers were absent. The original qualification protocol and every candidate source file are preserved byte-for-byte; this omission is not retroactively described as an original preregistration.

`dependency_continuity/ADDENDUM.json` (SHA256 `4b24864a87e9d09e22d3b4b0990164a672ddef8ea0214d14cfb5a91dd9c63e46`) records the complete static closure. Twelve omitted tracked helpers exactly match Git revision `7f10e250fada53c63c3e78b1b4817b8e7f1a81fc`, whose recorded commit time precedes both protocol registration and qualification execution. Eleven more exactly match pins in earlier frozen protocols committed at that revision. The two remaining helpers, `v7_media/motion.py` and `v7_media/piper_decoder.py`, match exact members of the retained original media archive. Its whole compressed SHA and internal manifest SHA were independently rechecked against its receipt at the earlier Git revision. No current source mismatch was found.

A separate guard package verifies these 46 files, the original 411 pins, its own source, and historical evidence before importing a formal entrypoint, then repeats identity checks after execution. The unchanged original freezer creates a retained base protocol; a separate final protocol adds only continuity identities and metadata. Original models, scoring, numeric gates, source allocation, and presentation profile stay fixed. A successful no-model identity check and two rejection checks (wrong addendum hash and substituted qualification path) completed without importing candidate modules or opening reserved sources.

This is retrospective source-identity continuity evidence followed by a prospective formal guard. It is not a forensic trace of all instructions executed inside the already running process; local Git dates and filesystem metadata are not independent timestamp authorities. The closure covers local Python source imports, not an entire interpreter/package/native-library operating-system image. No new qualification outcome was inspected to construct this addendum.

## Completed shared-cohort qualification

The frozen run completed all 300 rows, returned zero, and passed an independently implemented, standard-library-only score recomputation. Its observer code, model identities, input head, all source rows, and original 85% point gates remained unchanged.

| Fixed endpoint | Correct / registered rows | Accuracy | Original point gate | Descriptive speaker-bootstrap 95% interval |
|---|---:|---:|---|---|
| Registered V3 ensemble | 259/300 | 86.333% | PASS | 80.14%–91.86% |
| Selected input classifier | 273/300 | 91.000% | PASS | 87.21%–94.68% |
| Base component alone | 249/300 | 83.000% | FAIL | 76.33%–89.00% |
| Small component alone | 243/300 | 81.000% | FAIL | 74.53%–87.14% |

The ensemble made 41 abstentions and no incorrect nonempty predictions. The classifier made 27 incorrect digit predictions. The analysis resampled all 147 speaker clusters 5,000 times using fixed seed 23919 and retained the original 300-row denominator, including the two same-speaker duplicate-byte pairs. These marginal intervals are descriptive and do not replace the preregistered point gate; in particular, the ensemble interval does not establish a population accuracy lower bound above 85%. The two pretrained ASRs share a model family, and neither component alone qualified. This is one qualified composite measurement procedure, not two independently qualified observers or a human-naturalness certificate.

The whole process took 1,164.287 s wall and 1,578.585 s user+system CPU, with a peak RSS of 1,114,404 KiB including imports and final writes. It produced 298 actual distinct ASR event WAVs for 300 registered source rows. Native source collectors and later evidence hashing/asset packaging ran in the background for part of this execution, so its wall time is a measured concurrent execution cost rather than a controlled latency comparison. Every saved prediction was recomputed against its post-observation target, and all exact source identities/order were checked in `INDEPENDENT_AUDIT.json`.

The original freezer produced `dependency_continuity/BASE_CONFIRMATION_PROTOCOL.json`, SHA256 `aa49e5cf512dc32e9eebe331dd1a2c19de3d311e4ab90768357a20a44b74156d`, with 114 pins. The guarded final protocol is `dependency_continuity/FINAL_CONFIRMATION_PROTOCOL.json`, SHA256 `163297a3e210f800a2e7bd6e21aff58708d058f264eab17b5fe56ece3d06eb32`, with 149 pins. A separate exact comparison verified that every original non-identity field is unchanged, every original pin remains, and only the registered continuity pins/metadata were added. Freezing and that comparison did not open the reserved media source.

## Actual output execution and review

`render_state` decodes a public neural state into UTF-8 text, PNG pixels, a physical WAV, and an MP4 with an audio track. `observe_bundle` reopens the actual files, checks the public presentation clock, decodes codec bytes, and gives those bytes to frozen image and speech observers. Two two-second output events correspond to 20 frames at 5 fps and 32,000 PCM samples at 8 kHz. The expected labels are not arguments to generation or observation.

The five ingress routes are image, text, audio, video, and joint audio/video. Benchmark inputs are explicitly constructed aligned digit tasks from real source recordings and image source pixels, serialized, and reopened before model execution. This construction does not represent unconstrained natural multimodal scenes. Negative controls physically zero or swap audio, swap video events, repeat frames, or remove a required modality.

Actual audit memoization is keyed by the exact waveform-event bytes and carrier flag. Each output is nevertheless generated, serialized, and decoded. The finite ten-condition deterministic waveform head can reuse an already-completed observation of byte-identical events; event order is preserved. Cached requests and uncached ASR calls are reported separately and included in measured execution accounting.

Separate reviewers checked target separation, original component selection, the fixed target-free ensemble, actual event ordering, physical clock checks, and confirmation guards. The actual development and qualification result paths, registration files, observer manifests/assets, and selection bytes are bound to the final protocol. A candidate with different development pins is rejected. Required ffmpeg and ffprobe executables are also hashed. Model parameters and source pins must be unchanged at the end of a run.

The original and first repaired development failures are retained above. The early-commitment candidate has passed all development sample gates. Both independent-from-development qualification endpoints have now passed. The fixed final confirmation has now executed once and passed the original finite-task sample gates. Its success comes from the actual generated-file observations below, separately from the earlier qualification evidence.

## Remaining claim limits

No human listener naturalness or intelligibility study was performed. The waveform model represents ten canonical teacher-derived phrases, and video uses constructed moving digit images. These experiments cannot certify arbitrary speech, natural video, or a general multimodal foundation model. A passing finite-task media run would establish its registered finite task only. At the present decision, independent ASR qualification is a measured open blocker.

## Evidence preservation

Old frozen experiment files, protocols, and negative results are unchanged. A retained old evidence archive has SHA256 `53cb30f96e03ced895dd98576b00f147d13c3748b6acdc6418580320a4525e15`. Under disk pressure, 4,452 duplicate historical media/runtime files were checked individually against this archive, and 14 expanded Vosk files against its verified ZIP, before duplicate expansions were evicted. All current/needed model checkpoints, metadata, original source archives, new frozen assets, and new experimental outputs were kept. Two nonmanifest temporary model copies were additionally removed only after the official model SHA and absence of active file descriptors were verified. Complete per-file receipts are retained; these actions did not delete the evidence archive or any unique experimental evidence.

## Completed independent media confirmation

The final candidate was executed once on the allocated 128 new source pairs, with four pairs from each of 32 new image writers. Every writer is matched to one different reserved speech speaker, giving **32 writer/speaker clusters**. All five input routes used the same task pairs and generated all four required output modalities. New source identities/writers are separated from the original MNIST roles by the immutable upstream source allocation. The model, observer rule, gates, clock, and candidate source were unchanged throughout the run.

| Input route | Strictly correct in all four output modalities | Rate | Descriptive 95% writer/speaker-cluster interval |
|---|---:|---:|---|
| Image | 127/128 | 99.219% | 97.656%–100% |
| Text | 128/128 | 100% | 100%–100% |
| Audio | 114/128 | 89.063% | 82.031%–95.313% |
| Video | 117/128 | 91.406% | 85.156%–96.094% |
| Audio and video | 125/128 | 97.656% | 95.313%–100% |

All routes pass the original 75% strict-joint point gate. A total of 105/128 tasks succeed through every one of the five input routes. The interval procedure resampled the 32 matched writer/speaker clusters 5,000 times with fixed seed 23917. Intervals are marginal descriptions, not simultaneous guarantees or replacement gates. The text interval is degenerate because every observed cluster succeeded; it is not evidence of error-free performance on an unrestricted text population.

The four modality-specific correctness counts equal the corresponding strict-joint count within each input route. Thus the frozen canonical commitment produced mutually consistent outputs even on the remaining incorrectly understood tasks. The result does not establish handwriting-style preservation, open-vocabulary speech, natural scene generation, a human perceptual judgment, or a better NDU training objective. The separately scoped matched mean-versus-entropic experiment is required to assess the training question.

The ten explicit conditional cases passed with 20/20 speech events and 200/200 video frames. These cases add no independent source sample size. All five physical counterexamples were rejected nonvacuously: silence, swapped audio events, swapped video events, repeated video frames, and a physically missing video modality. The actual first image-input source task was suitable as the fixed counterexample baseline, without selecting a different successful task. Every actual output satisfied the public four-second presentation profile and lossless readback, including equality between decoded MP4 ALAC audio and the standalone PCM WAV.

The independent analysis verified **3,072 unique task artifacts**, explicitly split into **2,560 actual generated output files (640 bundles × four modalities)** and **512 input materializations (128 tasks × four modalities)**. Inputs are reused across the five routes; 3,072 must not be described as 768 generated media bundles. The conditional and negative-control artifacts are retained separately. Every task artifact SHA matched its observation record, all 640 stored scores were recomputed from target-free observations, and the one-to-one writer/speaker grouping was independently checked. The final identity guard also reverified the source/model/evidence dependencies after execution.

Whole-child execution, including guard checks, imports, model and source loading, input construction, actual generation, codec readback, and final writes, took **329.215 s wall**, **324.745 s user+system CPU**, and **880,044 KiB peak RSS**. Amortized over the 640 generated bundles this is about 514.4 ms per bundle for this run, including shared input/initialization overhead. Per-route generation plus independent cached observation averaged 408.3–412.2 ms per bundle; these narrower row timings exclude shared startup and input materialization. The run made **zero new ASR transcriptions** and **1,308 exact-event cache hits**, using only PCM identities already measured by the frozen cold observers. The earlier 96.775 s actual development process included the 22 cold component transcriptions over eleven distinct events; the fresh observer qualification cost of 1,164.287 s is also separate. These costs cannot be represented as fresh ASR inference per output or as generic open-vocabulary inference speed.

A fixed example index is retained under `examples/fixed-first-confirmation/`, with the actual artifacts under `/tmp/hepta-ndu-next-media-examples/fixed-first-confirmation`: source index 0, image route, with expected digits [1,6], actual caption `left 1 right 6 relation less`, and the actual generated WAV, PNG, and four-second MP4. It is an unchanged byte-for-byte copy of the first confirmation result, chosen by source order rather than observed quality. `EXAMPLE.json` records its source, observed score, clock, original paths, and file SHA values. Actual binary artifacts are retained locally and in the complete evidence archive; the Git source/report publication contains only the small index and explanation.

Complete observations and cost receipts are retained at `/tmp/hepta-ndu-next-media-cache/repair-confirmation-001` and its process directory. `ANALYSIS.json` and `TASK_ARTIFACT_CENSUS.json` document the independent recomputation and exact artifact split. The immutable public ASR assets have already been sealed and fully read back in `hepta-ndu-next-media-asr-assets-20261026.tar.gz`, SHA256 `a53bb47966af62acc57486aec7585d9a5129ff4b519423879b5061b0092c26e4`; the complete research-study archive is sealed separately after all study files are closed. No upload is performed by either packager.

Compact exact copies of the completed qualification, confirmation, independent analyses, physical negative observations, whole-process costs, and identity guards are under `evidence/`. `evidence/ORIGINS.json` links each copy to its exact original execution file and SHA. These copies add no experiments or samples. The complete study archive receipt is published separately after archive closure as `EVIDENCE_RECEIPT.json`.
