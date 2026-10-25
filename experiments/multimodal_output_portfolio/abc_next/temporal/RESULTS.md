# C-next: genuine text/speech continuation with delayed shared semantics

## Result and scope

The complete frozen experiment generated new text and speech through a fixed pretrained Piper acoustic backend, measured terminal audio with an external Whisper observer, and retained actual generation, observation, serialization and training costs. It executed 64 held-out fact combinations, four public-noise scenarios per combination, and five actual continuation paths per case. The 1,280 paths are repeated potential outcomes within 64 fact groups, not 1,280 independent samples. There is one template family and one voice.

The registered shared-state contrast **passed** its positive-evidence gate: external-observer net-CE gain +0.1203 [+0.0789, +0.1628] (nominal 97.5% crossed fact/seed interval). The learned-feedback contrast against the fit-selected fixed policy **did not pass**: +0.0036 [-0.0278, +0.0334]. A nonpositive lower interval endpoint does not become a successful feedback claim because the execution pipeline worked.

This closes the artifact-realization gap left by the earlier transport-only C witness: the new waveform bytes come from actual pretrained neural synthesis of the current shared-state text, rather than replay of a source recording. It does not establish end-to-end acoustic/text co-training, general language generation, an audiovisual model, continuous-time Merton control, or an optimal native multimodal portfolio.

## Registered design and identities

| Artifact | SHA-256 |
|---|---|
| Final evaluation protocol | `9d74cc54fec42e9828b1b5bc110e861456d1d3bec1d0634507dd207cee038c2b` |
| Active 15-critic policy bundle | `bdd0e423b67d4618fd639df427beb18e4964544ddfad7f1cbf1d737bc19ad1cb` |
| Aggregate `SUMMARY.json` | `f057d83ba0d373782bf530a8781822906a695217be479e3b0f92d0fa4c1b7633` |

The source-role manifest and qualification/final protocols are in `freeze-v1/`. The final protocol pins the generator, both observers, parsing, public-state/action interfaces, trained policy identities, statistical implementation, two primary contrasts, all secondary analyses, candidate census and timing design before evaluation begins. No evaluation group selected a template, observer, threshold, controller hyperparameter or fixed policy.

The 128 unique number/color/direction combinations were frozen into 16 development, 32 fit, 16 qualification and 64 evaluation groups. Vocabulary and templates are shared across roles. Fact-group intervals therefore condition on one fixed construction and voice; they do not represent independent natural-source, lexical-family, template or voice replication.

Only the action-value interface is trained here: a 24-unit tanh hidden layer with four positive softplus outputs (floor 0.001), regressing `exp(-2 × net utility)`. Initial-only, feedback and probe-masked variants use five fixed seeds each (17, 29, 43, 59, 71), 1,200 Adam steps, learning rate 0.01 and weight regularization 0.001. The 32 fit groups supplied 128 actual contexts and 512 actual candidate paths. Their Vosk-based risk selected `fuse_slow` as the fixed comparator. Whisper was not run on fit data. The categorical fusion operator, text templates and pretrained acoustic weights are fixed; this is conditional-value training, not new joint text/acoustic generator training.

### Actual causal sequence

The semantic source is a controlled noisy-fact environment. Its owner pre-samples both initial and later cues when constructing the episode; the initial-only feature adapter ignores all later fields, and the executor releases them after the actual draft observation. This is a tested nonanticipating information interface, not acquisition of a new live sensor signal. The new synthesized waveform and draft ASR are real operations.

1. An initial-only gate sees only initial public features. The episode owner alone uses hidden facts to sample declared noisy cues.
2. The generator actually synthesizes a neutral prefix and commits its text and PCM with durable writes before any later observation is released.
3. A fresh, uncommitted draft is synthesized from the initial shared semantic state. Vosk observes the actual audio without a custom grammar, intended text or target.
4. Later public evidence and the draft observation become available. Feedback decisions are durably recorded before any future candidate waveform or terminal quality score exists.
5. Each candidate forks the already committed prefix, then synthesizes and commits two future chunks. Exact text/PCM spans and final wave bytes are checked against the original prefix.
6. Independent Whisper measures the complete final WAV offline. Its scores never enter policy features, critic fitting, best-fixed selection or hyperparameters.

The four lawful generator actions are keep/fuse × normal/slow. Fixed and initial-only gates have the same fusion operator, lawful fresh evidence, action family and generation budget. Initial-only means the action gate, not denial of later conditioning inside a selected fusion operator. The fifth path requests fuse but clamps the shared state. It pays the same declared fuse penalty, isolating content propagation from an artificial cost advantage.

The strong public reference enumerates all eight correctness masks under the declared factorized posterior and the same gamma-2 exponential-risk objective, while assuming perfect acoustic intelligibility. It is not asserted to be optimal for actual recognition errors or for a finite held-out subset. The realized full-information oracle is computed only after all real candidates exist and remains an offline diagnostic upper bound.

### Frozen utility and statistical unit

Utility is `0.6 × (text fact accuracy + audio fact accuracy)/2 + 0.2 × nonmissing fact agreement + 0.2 × joint exact success`. Net utility subtracts 0.02 for fuse (also for the clamp) and 0.01 for slow synthesis. These fixed proxy penalties do not stand for measured milliseconds, CPU, money, energy or a deployment cost price.

Completion requires physically complete output and all three unambiguous facts in both text and independently decoded speech. Incorrect but complete content can satisfy completion and must fail exact task success. Silence and truncated outputs cannot pass merely because a file is present. ASR-measured task success is an imperfect external content metric, not a human listening score.

The five critic seeds are crossed with 64 fact groups; all four scenarios and policy replays stay within their fact group. CE is evaluated within each trained seed and then averaged across seeds. The two registered primary contrasts use nominal 97.5% paired percentile intervals with 4,000 common bootstrap draws. All other intervals are descriptive 95% intervals. Few-seed coverage is not guaranteed, and finite-scenario CE is not claimed to be an unbiased population-risk estimate.

## Independent observer qualification

| Frozen observer | Speed | Fact accuracy | Exact success |
|---|---|---:|---:|
| external | normal | 0.9792 | 0.9375 |
| external | slow | 0.9792 | 0.9375 |
| online | normal | 0.8958 | 0.6875 |
| online | slow | 0.9792 | 0.9375 |

All predeclared qualification gates passed on the 16 qualification groups. External fact/exact thresholds were 0.90/0.75 at both speeds; online thresholds were 0.85/0.65. Intentionally wrong numbers failed exact success, and actual silent/truncated PCM failed semantic completion. Repeated silent controls are not independent population-level false-positive-rate evidence. The actual `south → self` and `four → for` errors were retained. No homophone-to-target repair was added.

Whisper and Vosk have separate weights and different recognizer implementations. Their possible pretraining-corpus overlap is unknown, and their recognition errors are not assumed statistically independent. Target-independent normalization of digits 1–8 into words was frozen before qualification. Neither observer received a target prompt, candidate-fact list, hotwords or custom vocabulary grammar.

## Held-out external quality

| Policy | Net CE | Exact success | Required completion | Text facts | Speech facts | Agreement |
|---|---:|---:|---:|---:|---:|---:|
| fixed/keep_normal | 0.6257 | 0.3516 | 0.8008 | 0.7422 | 0.6849 | 0.9310 |
| fixed/fuse_normal | 0.7260 | 0.5508 | 0.7969 | 0.8789 | 0.8125 | 0.9245 |
| fixed/keep_slow | 0.6354 | 0.3906 | 0.8867 | 0.7422 | 0.7122 | 0.9622 |
| fixed/fuse_slow | 0.7446 | 0.6289 | 0.8672 | 0.8789 | 0.8411 | 0.9557 |
| fixed/best_fit | 0.7446 | 0.6289 | 0.8672 | 0.8789 | 0.8411 | 0.9557 |
| initial_only | 0.7443 | 0.6125 | 0.8695 | 0.8729 | 0.8357 | 0.9565 |
| feedback_no_probe | 0.7453 | 0.5922 | 0.8891 | 0.8638 | 0.8302 | 0.9630 |
| feedback | 0.7482 | 0.5984 | 0.8891 | 0.8672 | 0.8331 | 0.9630 |
| public/assumed_prior_reference | 0.7329 | 0.5508 | 0.7969 | 0.8789 | 0.8125 | 0.9245 |
| mechanism/clamped_fuse | 0.6057 | 0.3516 | 0.8008 | 0.7422 | 0.6849 | 0.9310 |
| oracle_offline | 0.8392 | 0.7266 | 0.9141 | 0.9258 | 0.8997 | 0.9714 |

For feedback versus the fit-selected fixed policy, the mean gross-utility change is `-0.010573`, and the mean declared proxy-penalty change is `-0.009461` (negative means a smaller penalty). This separates observed content changes from the chosen proxy pricing. These mean differences are not an additive decomposition of the nonlinear CE contrast, and a lower proxy penalty is not a measured CPU saving.

The oracle row selects a realized outcome after scoring every candidate and cannot be implemented by the online controller. Fixed policies are repeated along the seed axis only to preserve paired comparisons; those repeats add no information. A learned gain over one globally fixed action alone would not demonstrate that real generated-state feedback is needed; the initial-only and draft-masked diagnostics remain explicit.

All 1,280 paths physically completed both text and nonempty speech and passed exact committed-span readback. The table's required *semantic* completion additionally requires recovery of all three facts by the external audio observer; its failures do not mean that the waveform file or speech modality was absent.

| Registered/descriptive contrast | Net-CE gain [interval] | Exact-success difference (percentage points) |
|---|---:|---:|
| shared_state_effect | +0.1203 [+0.0789, +0.1628] | +19.92 |
| learned_feedback_increment | +0.0036 [-0.0278, +0.0334] | -3.05 |
| initial_gate_increment | +0.0038 [-0.0183, +0.0260] | -1.41 |
| probe_increment | +0.0029 [-0.0032, +0.0094] | +0.62 |
| declared_prior_reference | +0.0153 [-0.0129, +0.0424] | +4.77 |
| oracle_vs_fixed | +0.0946 [+0.0724, +0.1175] | +9.77 |
| oracle_vs_feedback | +0.0910 [+0.0708, +0.1130] | +12.81 |

### Mean and tail loss

These are descriptive empirical losses `1 - utility`, before proxy action costs. CVaR uses the worst 10% with exact fractional boundary mass. Values below are per-seed output-distribution statistics averaged over seeds, not a relabelled population tail certificate.

| Policy | Mean loss | P95 loss | Worst-10% CVaR |
|---|---:|---:|---:|
| fixed/best_fit | 0.1671 | 0.6000 | 0.6096 |
| initial_only | 0.1736 | 0.6000 | 0.6103 |
| feedback | 0.1776 | 0.5950 | 0.5920 |
| feedback_no_probe | 0.1808 | 0.6000 | 0.5973 |
| public/assumed_prior_reference | 0.1975 | 0.6000 | 0.6177 |
| oracle_offline | 0.1128 | 0.4000 | 0.4560 |

## Observer transfer and value diagnostics

Vosk and external Whisper disagreed on parsed audio facts on 269 of 1,280 actual candidate paths (21.02%). This is a descriptive path count; repeated facts/actions do not make it an independent-sample estimate.

| Policy | External net CE | Online-Vosk net CE |
|---|---:|---:|
| fixed/best_fit | 0.7446 | 0.6958 |
| initial_only | 0.7443 | 0.6990 |
| feedback | 0.7482 | 0.7104 |
| feedback_no_probe | 0.7453 | 0.7078 |
| public/assumed_prior_reference | 0.7329 | 0.6737 |

| Value interface | Observer target | Realized-target MSE | Mean predicted Z minus realized Z |
|---|---|---:|---:|
| feedback | external | 0.014526 | +0.041348 |
| feedback_no_probe | external | 0.014332 | +0.041129 |
| initial_only | external | 0.022500 | +0.048460 |
| feedback | online | 0.010935 | +0.019395 |
| feedback_no_probe | online | 0.011049 | +0.019176 |
| initial_only | online | 0.019678 | +0.026506 |

The following are the first retained examples of text versus external audio-observer disagreement, not a selection of favorable cases. They distinguish measurement disagreement from a semantically wrong but faithfully spoken shared state.

| Action | Actually committed text | External transcription of actual WAV |
|---|---|---|
| fuse_clamp_normal | I will check the details. The number is two. The color is yellow. The direction is south. | I will check the details. The number is two. The color is yellow. The direction is self. |
| keep_normal | I will check the details. The number is two. The color is yellow. The direction is south. | I will check the details. The number is two. The color is yellow. The direction is self. |
| fuse_clamp_normal | I will check the details. The number is four. The color is blue. The direction is south. | I will check the details. The number is for, the color is blue, the direction is south. |
| fuse_normal | I will check the details. The number is four. The color is blue. The direction is south. | I will check the details. The number is for, the color is blue, the direction is south. |

These diagnostics compare a predicted conditional positive value with one actual exponential-utility outcome per candidate. They include irreducible outcome variation and are not direct measurements of the true conditional expectation, a calibration bound, or a hidden-information oracle. Whisper targets are evaluation-only; the critics were fitted to Vosk targets on the 32 fit groups.

## Real compute and latency

The evaluation executed 3,072 synthesis API requests, yielding 220 distinct complete-WAV hashes. Duplicate hashes are expected under deterministic synthesis of the same facts; every candidate still performed its real synthesis call. An API request can contain multiple sentence-level acoustic forwards, so the request count is not an acoustic forward-pass count.

Evaluation used two spawned processes with static source-index-parity assignment; all scenarios for a fact stayed on one logical worker. Each worker was bound to one CPU and used single-thread ONNX/Whisper plus OMP/BLAS limits. Vosk's default native threading was also bounded by one-CPU affinity. The final selected-policy timing study ran sequentially on one CPU. Global wall time is one monotonic elapsed clock; per-case wall sums are occupancy and are not added to form global elapsed time.

| Stage | Actual wall seconds | Actual process/child CPU seconds |
|---|---:|---:|
| Observer qualification | 130.381 | 179.578 |
| Fit data: 128 cases / 512 real paths | 855.314 | 850.917 |
| Evaluation: all 1,280 real paths | 1501.450 | 2968.627 |
| Critic fitting, both identical-weight builds | 3.965 | 3.961 |
| Terminal external scoring, sum across workers (included above) | 887.727 | 887.527 |
| Terminal online scoring, sum across workers (included above) | 1323.625 | 1323.338 |
| Timing-run fresh-process generator/online-observer load (included in timing-run total) | 1.778 | 1.758 |
| Full timing child process, separately pinned outer wrapper (includes internal run) | 392.066 | 390.146 |
| Dedicated selected-policy timing, 256 executions | 390.173 | 388.272 |

| Selected policy | Wall mean / P50 / P95 ms | CPU mean / P50 / P95 ms | First durable output P50 ms | Audio duration P50 s |
|---|---:|---:|---:|---:|
| feedback/17 | 1510.04 / 1501.74 / 1632.89 | 1502.87 / 1495.04 / 1627.25 | 137.97 | 5.683 |
| fixed/best_fit | 1521.51 / 1510.29 / 1652.33 | 1514.72 / 1503.86 / 1644.14 | 138.05 | 5.782 |

Timing host load averages began at `[0.599609375, 1.60498046875, 2.4462890625]` and ended at `[1.35205078125, 1.41845703125, 2.06005859375]`; measured process affinity was `[8]`. This is a shared container, not an isolated deployment benchmark. All rounds and outliers were retained. Timing repeats added zero independent quality samples. Exact final-WAV hashes matched their corresponding quality-matrix outputs on 256/256 timing executions; raw timing report SHA-256 is `d1be5a1bd7512861152a41a167ebdb839216450390f1efbaadd93cf15801d5d7`.

The independent stdlib-only outer wrapper recorded full child-process launch through exit, with peak child RSS `469916` KiB (458.90 MiB). It includes Python startup/import, CLI/freeze checks, all model loads, all sequential episodes, measurement receipts and final report serialization. It excludes the outer wrapper's own startup/preparation and receipt write, later post-audit/rescoring, other host work and actual audio-device playback. `TIMING_PROCESS_RECEIPT.json` SHA-256 is `3130f79f6f1ff1cb208479e0cfd3381aeef5e6646a6186b39a8ab56e800c1fb3`; its pre-timing launch plan is `8dd82547f51337f461dada802fcf77b73c04b5d522158afb564f7d1b2774d6f9`. The wrapper, child source, executable, command vector and explicit thread environment were pinned before timing; the frozen timing implementation was not changed.

The separate closing audit independently recomputed all 256 media identities: stored audio-identity flag false count `0`, actual audio mismatches `0`, and actual text mismatches `0`. `TIMING_AUDIT.json` records this audit (SHA-256 `bd9e422c4d523ceb88b72c12799edd816e951bc155fe8d863e9d04b4585d5fd8`).

Every timed artifact has the exact text and audio bytes of its corresponding quality-matrix output, so the frozen content measurement applies to those identical outputs.

The per-execution latency table uses already loaded models; model loading is separately reported and included in the timing-run total. Fresh-process model construction does not imply cold filesystem, OS or hardware caches after the preceding study. The actual online timer includes prefix TTS/commit, draft TTS, online Vosk, the selected gate, both new future chunks, durable writes, final WAV serialization and exact readback. Final content ASR is offline and separately charged. The endpoint is a durable complete WAV/text artifact, not speaker playback or network delivery. Both policies pay the common draft/probe; a deployment-specialized fixed policy could omit unused probing and be cheaper. That optimization was not measured.

Timing covers the first 16 predeclared evaluation fact groups, all four scenarios, two counterbalanced rounds, and two policies: 128 executions per policy. Feedback uses the prospectively chosen seed 17, not a post-result seed selection. Main quality summaries average five critic seeds over all 64 groups, so the narrower timing sample is not presented as a five-seed latency estimate or a matched full-cohort economic dominance test.

The timing-run clock begins after CLI parsing, frozen-input verification, affinity configuration and output-directory creation; it includes model/policy loading, matrix index reads and every selected episode, and ends before final report serialization. The per-episode measurement-only timing receipt is written after its episode timer stops but remains inside the run clock. The evaluation runner begins its clock after CLI parsing, includes both spawned workers' startup, and records parent plus terminated worker CPU. Parent Python/import startup and final report writing are outside these code-defined internal clocks. The separate outer receipt adds full child-process launch/import/exit coverage; neither measurement resets filesystem/hardware caches or measures full machine energy consumption.

The compact `component_cost_ms` arrays are aligned on five policy seeds. Fixed/clamp measurements repeat on that axis; their `sum` and `n_rows` fields are not unique actual executions or total measured resource use. The main total-cost figures above use the evaluation's single global elapsed clock and actual parent-plus-child CPU. `matrix_total_case_cost.wall_ns` is summed worker occupancy, not global elapsed time.

For independent cost reconciliation, preliminary critic bundle `0338e2bc7d31968729968e423c362c11f5e3003948594c7f587d045429c52bed` recorded 2.071523821 s wall and 2.067833171 s CPU. The active bundle `bdd0e423b67d4618fd639df427beb18e4964544ddfad7f1cbf1d737bc19ad1cb` recorded 1.893659428 s wall and 1.893600648 s CPU. `SUMMARY.json.value_fit_cost` contains the active build only; the two-build total above additionally includes the preserved preliminary build. These are actual critic-fitting clocks, not acoustic generator training costs.

Fit-data generation and both critic builds are included above. The second build kept exactly the same learned arrays and fit-selected fixed action after the public analytic baseline was made explicitly risk-sensitive; both builds' actual costs are counted. Public-model download, development/qualification and model loads are preparation costs, not free pretrained-model training. The original training cost of Piper and Whisper is unknown to this experiment. No claim that measured control benefits cover a deployment's economic or full foundational-model training costs is made.

## Integrity checks and remaining claims

All eight targeted unit/invariant checks passed before the evaluation freeze. Real development streaming and two-process execution were also exercised before evaluation. The final analysis verified the complete registered census, exact original prefix and committed spans, actual ASR input hashes, decisions matching frozen public models, and prefix/release/decision ordering under the frozen decision-before-generation executor. Qualification failures and actual recognition errors were preserved rather than corrected using hidden facts.

The positive claims are bounded by the registered numerical gates above. Actual new speech, delayed shared-state propagation, independent terminal observation and cost-accounted executable control are now directly testable. A learned-feedback advantage must stand on its own primary and ablation results; the existence of a large hindsight oracle gap does not make it attainable from public observations.

Outstanding scientific scope includes learned generative text rather than templates, joint acoustic/semantic generator training, multiple online decisions with delayed temporal dependencies, fresh natural sources and voices, human perceptual validation, missing-input multimodal robustness, video and audiovisual synchronization, and native admission/proposal integration of this specific speech backend. This Python output journal is not presented as the native admitted-tick journal/proposal chain. A genuine global-portfolio optimality or foundation-model superiority claim remains beyond this experiment.

## Reproduction and retained evidence

`README.md` documents the runnable sequence, public primary sources, models, licenses, frozen interfaces and dependencies. `SUMMARY.json` is the full compact aggregate evidence, including every fixed action, all registered contrasts, observer disagreement examples, per-seed risk results, tail summaries and cost accounting. `freeze-v1/` preserves the small source-role and protocol artifacts. Source code and this detailed report are the publication deliverable. Generated waves, raw fit/evaluation rows, downloaded model weights and critic checkpoints remain outside Git as requested.

## Freeze and Git publication chronology

This was a **local prospective freeze**, not a claim that the protocol was publicly committed to Git before testing. The source/protocol Git publication began after evaluation had already started. Local artifact timestamps below are filesystem mtime observations from the actual written records; they are not an independent external timestamping certificate.

| Event | Recorded time |
|---|---|
| qualification_local_freeze | `2026-10-25T06:06:58.053255+00:00` |
| evaluation_local_freeze | `2026-10-25T06:32:31.144328+00:00` |
| evaluation_start_receipt | `2026-10-25T06:32:46.450291+00:00` |
| First local source commit | `2026-10-25T06:57:28+00:00` |
| Last local source/protocol commit | `2026-10-25T06:57:29+00:00` |
| evaluation_complete_receipt | `2026-10-25T06:57:47.896262+00:00` |

The six local source stages run from `510ef8d79de2d1a004f5f6f4db339cb308493fbe` through `cd478e0a5aa9bdcd51c68602371a1984b205b2e2`. The parent verified remote source publication through `e04569d18504a4274d2df7ba98872f0240293d55`. Exact remote-server publication time was not independently sampled by this child. `PUBLICATION_CHRONOLOGY.json` preserves these identities and the distinction between the local freeze and later Git publication.

The original v1 full-process timing wrapper and launch plan were subsequently published through remote `cce41f8c4b856bf01576cff942b407a79ec66dd0` before timing execution began. That wrapper rejected its launch after observing nonzero cumulative `RUSAGE_CHILDREN` values, before `Popen` and before any timing output existed. The origin of those prior cumulative counters was not directly established. `TIMING_WRAPPER_PREFLIGHT_FAILURE.json` preserves the failure without counting it as a discarded timing execution.

The non-CORE wrapper was corrected to use `os.wait4` for the exact new child PID, with `Popen.returncode` assigned from its exit status. The unchanged timing child then ran under locally pre-pinned v2 wrapper `68c19154706939ef2ce7c7e5a8b3720dcdbf7cd4e72c7c64e584cfc3ac6668dd` and plan `8dd82547f51337f461dada802fcf77b73c04b5d522158afb564f7d1b2774d6f9`. We do not assert that the corrected v2 source was publicly published before that actual child launch. Neither this metrology correction nor the earlier v1 publication makes the original primary-quality run a publicly preregistered Git test.
