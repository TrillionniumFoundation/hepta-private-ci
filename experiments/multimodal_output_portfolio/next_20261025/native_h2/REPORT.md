# H2 native teacher: development and integration evidence

The frozen H2 teacher has now executed inside the unchanged original owner on a new 64-writer panel: 708 decisions, 397 actual emitted outputs, causal public feedback, four successful recovery probes and 54 rejected invalid cases. New 100-writer calibration and 1,000-writer verification of its separate correctness admission head passed the original four gates. **The native comparison did not establish a quality gain, and the observed public request cost was higher:** NDU minus same-admission correctness CE was +0.011367, with original nominal writer-bootstrap interval [−0.087290, 0.106950]; public request cost was +5.613517 ms, interval [2.611169, 9.315001]. These are nominal intervals on the fixed observed ordered streams, not validated population or universal causal-effect intervals. Authority remains `deny_all`.

The two earlier 64/64 pilot failures remain failures. The larger historical feasibility stage used the second predictor's exact weights, normalization, cuts and three-bin rule; it did not retroactively replace either result. Selection-conditioned correctness calibration also remains a limitation: selected NDU ECE was 0.011891 in the 1,000-writer resource-free diagnostic, but 0.057746 in actual native execution. These are correctness-probability diagnostics, not calibration of NDU moments or paired action-value differences. Neither the favorable qualification diagnostic nor the earlier positive unrestricted-teacher control result transfers automatically to this constrained native policy.

One native owner per policy persists across all episodes and writers. The generator state resets per episode; native state and the NDU projection do not. Original admission can read persistent sparse-state and sequence fields as well as actual resource measurements. Moreover, the teacher's original H2 backup does not incorporate these new future admission constraints or terminal rejection penalties. Per-step masking is therefore not a solution of the new constrained Bellman problem. The NDU projection digest is causally bound into subsequent ticks, but this port does not apply it numerically to the value head or a plasticity update. Actual new output affects H1 through the public frame and encoder. These limits are part of the main result, not claims of a particular cause of the negative comparison.

## 1. What is implemented

The exact evaluated seed-17 teacher is preserved. It estimates five conditional exponential moments for the remaining one or two steps, with gamma 2 and the original nominal .002 charge per non-stop action. The model service computes its fixed public first layer. Rust loads the final moment layer and chooses the minimum value on the original owner's admitted feasible action set. This is not a correctness-argmax substitution for the NDU objective.

The new correctness head is separate from the teacher and controls admission. Its target is the **immediate emitted output** after each candidate action at the H2 root and all four reachable H1 children. A semantic investment whose current draft is poor can consequently be excluded even if its continuation has value. The resulting constrained policy is not functionally identical to the unrestricted teacher. Numerical head tolerance, raw floating-point teacher action parity on the same admitted set, admission changes to the unrestricted choice, and actual quality gains are reported separately.

The public ABI has 103 Q24 coordinates: four absence features, two action flags, remaining horizon, 32 teacher activations and 64 correctness activations. Encoder work belongs to execution cost. Native layers, original resource ceilings, durable pre-RNG action commitment, episode continuation, and NDU projection feedback are implemented without changing product sources or the previous H1 experiment.

An H1 continuation must bind the preceding actual result's public-state digest and native outcome digest. Wrong episode, parent, state, horizon, duplicates and unfinished decisions are rejected before a native tick. Actual recovery probes covered interruption after an H2 decision and restart after its observed output before the H1 continuation, for both policies, first on old development and then on the independent native panel.

Online feedback reads only emitted media through the existing public sensor. Its bounded proxy is `1 - invalid_caption - image_text_disagreement`; a consistent wrong answer can score well. This proxy is not ground-truth utility or global NDU. Private truth scoring starts only after all owners have closed. Task construction already holds targets in the trusted Python host; the reviewed data flow excludes them from the public encoder, online observer and native requests. Rust verifies receipt identity, bytes and causal fields, but does not independently rerun the sensor against a malicious host. See [METHOD.md](METHOD.md).

## 2. Both original pilots failed

Both pilots used the existing forecast-fit data to train correctness heads and the fixed 128 historical forecast-calibration pairs to form even/odd 64-pair calibration and held subsets. Repeated views, draws, states and actions are not additional independent sources. These are old source-pair diagnostics, not new writer qualification.

| Fixed candidate and stage | Held pooled ID ECE | Held all-row ECE | ID acceptance | OOD false pairs | Old feasibility |
| --- | ---: | ---: | ---: | ---: | --- |
| 330-parameter teacher-hidden heads, 64/64 | 0.046508 | 0.038809 | 0.969750 | 0/64 | FAIL |
| Full-public 763→64→5 heads, 64/64 | 0.045482 | 0.037954 | 0.793813 | 0/64 | FAIL |
| Same full-public weights/cuts, separate 400/400 stage | 0.017188 | 0.008944 | 0.625600 | 0/400 | PASS, development only |

The 64-pair zero-error one-sided 95% bound is 0.045730, well above the eventual 0.004999 writer bound. It was retained rather than reinterpreted as sufficient qualification. Near-zero in-calibration ECE is a consequence of estimating bin means on those same calibration rows and is not generalization evidence.

The first pilot's selected diagnostic combined pilot-calibration and held rows: NDU ECE 0.051089 and correctness ECE 0.046578. Its scope is explicitly developmental. The second pilot reports held-only selection: NDU ECE 0.082031 and correctness ECE 0.102228. Neither selected result passes a 3% interpretation. The exact original reports and executed source snapshots remain in the raw development directories; byte-exact small reports are indexed by [evidence/MANIFEST.json](evidence/MANIFEST.json).

## 3. Why a separate larger old-data stage was justified

The saved second-pilot predictions showed a substantial source-level frequency shift: pooled ID correctness was 0.883813 on the 64 calibration pairs and 0.834750 on the 64 held pairs, a difference of −0.049063. The individual calibration bins contained only 42–61 distinct source pairs. Their exposure-weighted Kish counts were approximately 28.2–46.1; these are diagnostics of repeated exposure weights, not independent sample counts or guarantees about intrapair dependence.

On held ID rows, raw continuous Brier was 0.108327, the fitted three-bin predictor 0.118241, and diagnostic held-bin means 0.114601. The latter is an oracle decomposition only, never a deployed calibrator. Both frequency transfer and the fixed coarse bins contributed to lost accuracy. The evidence did not justify claiming the earlier failures were solely caused by a small calibration sample.

The new stage was frozen in [EXPANDED_OLD_PROTOCOL.json](EXPANDED_OLD_PROTOCOL.json), SHA `893625ee94b3549c5f91ceb9c91815148b3fb1bb0278b0f4142fe592ee056cf4`, before any of its generated outcomes. Metadata inspection confirmed the exact historical fit and pilot source identities. Of 1,000 pairs in the original forecast-calibration role, the 128 prior pilot pairs were excluded. A fixed hash ordering assigned 400 of the remaining 872 to calibration, 400 to held validation, and left 72 unused. The fit role and calibration role are disjoint.

The predictor SHA remained `2ea073f7de0cf0a134c94cb0a683e3924733dd7206cf619264e370bbce2f37f8`. No retraining, new cuts, bin changes, threshold changes or additional sample search occurred. Each pair received one fixed cycling ID view and one absent view, with one future draw and all 25 state/action outputs. This differs from the pilot's repeated-view/draw exposure. Therefore the observed improvement is evidence of feasibility on this separately registered larger old panel, not a controlled estimate of the effect of changing sample size alone.

All 20,000 calibration outputs were physically generated, written, reopened and scored before the calibration frequencies were persisted. Only then were the 20,000 held outputs generated. An independent structural audit checked all 80,000 retained PNG/text file hashes, source assignments, complete five-state by five-action censuses, pre-RNG commitments and temporal ordering. All checks passed. The frozen source closure contains 62 source files, preserved by exact SHA in the executed-source snapshot.

The held results passed the existing development gates: pooled ID ECE 0.0171883096, all-row ECE 0.0089440748, acceptance 0.6256 and zero absent-input false accepted pairs. The 400-pair OOD upper bound is still 0.007461, so this stage does not grant the eventual writer-level qualification. It also does not make every horizon/action calibrated: held H1 image ECE is 0.032911, H2 couple 0.039917 and H2 text 0.031144.

| Larger held panel, selected actions | Steps | Selected ECE | H2 selected ECE | H1 selected ECE |
| --- | ---: | ---: | ---: | ---: |
| Admission-masked NDU teacher | 645 | 0.057179 | 0.074196 | 0.029395 |
| Same-head correctness argmax | 508 | 0.085477 | 0.086801 | 0.080573 |

These 400-source-pair diagnostics use Python choices on actual generated trees; they do not substitute for the original owner's resource or admission execution. They show why the later selected-policy ECE must remain separate from the pooled qualification gate. No native quality or cost superiority follows from them.

## 4. Actual build and unqualified-start rejection

Repository `just fmt` completed before build. H2 build-001 compiled successfully in 2.364427 seconds using the verified original owner and existing dependency artifacts. The executable SHA is `bf08b491479b1eb68de03f88b62ea0031704f7f024cfb63afea78f25e04af442`. The original owner source SHA remains `4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf`. Build commands, source snapshots, binary and warnings are retained. This builds the real owner adapter, not the complete `agentd` daemon.

Two actual process probes supplied truthful existing evidence that is not H2 qualification: the previous H1 verification report and the failed second H2 development report. Both exited 1 with `Frozen complete study qualification rejected`, before creating any owner state. The probe descriptors explicitly declare their negative-test purpose. No successful qualification was fabricated. Their child wall times were 2.967 ms and 1.527 ms. This verifies rejection of these two unqualified inputs; it does not verify successful qualified H2 execution.

The independent static review found no remaining blocking issue in the reviewed code version. Qualification now mechanically binds the actual new 100-writer output census to the calibrator, the fixed qualification protocol, actual models and encoder dependencies, the package, and execution. The reviewer also checked the original thresholds, absence mask, immediate-output target and target-free feedback. Static review is not qualification, action parity or effectiveness; see [CONTROL_STATIC_REVIEW.md](CONTROL_STATIC_REVIEW.md).

## 5. Complete measured development costs

| Actual child | Wall seconds | User CPU seconds | System CPU seconds | Peak RSS bytes |
| --- | ---: | ---: | ---: | ---: |
| First pilot fitting/evaluation | 6.448203 | 5.920670 | 0.610892 | 485,011,456 |
| Second pilot fitting/evaluation | 11.410137 | 12.474127 | 0.679216 | 535,711,744 |
| Larger old-stage 40,000-output collector | 182.967420 | 168.234334 | 8.626022 | 443,785,216 |

These are complete child-process measurements, including imports and retained output work, rather than inference-only timers. Linux `wait4` peak RSS is a peak, not a sum across separate processes. The separate structural audit took 11.2102 seconds wall and 7.9730 CPU seconds; it did not rerun models. A first shell launch using absent `/usr/bin/time` exited 127 before training and remains recorded. Compilation, repeated formatting and the two rejection probes are recorded separately. These costs are not a native latency or economic-gain result.

## 6. Completed fixed stages and remaining limits

The separate new roles remain 100 calibration writers, 1,000 qualification writers, and 64 execution writers with two pairs each. Metadata-only exclusion checks are recorded in [SOURCE_STATIC_AUDIT.json](SOURCE_STATIC_AUDIT.json). Each phase requires its own actual candidate and data freeze before opening outcomes. The original four admission gates remain unchanged.

All three fixed stages completed: 30,000 calibration outputs, 50,000 qualification outputs, and the independent original-owner execution panel. Candidate identities were frozen before each phase. The qualification passed; the native effectiveness comparison did not establish a gain. Neither the unused 72 old pairs nor 85 unallocated new writers was used to expand toward a pass.

The measured study resolves local model execution, original-owner admission, causal feedback and recovery within this bounded research task. Selected-state correctness calibration and an effective quality/cost tradeoff remain unsupported in the actual native comparison. Production trust material, authenticated outcome ownership and the complete daemon/model-service lifecycle remain outside this research owner execution. This owner experiment generates text and images; it does not by itself certify the separate full audio/video pipeline. No CI status is used.

## 7. New calibration, retained API failure and versioned repair

The first new calibration launch loaded the registered source pixels and then failed before generator or observer loading: the caller incorrectly tuple-unpacked `SourceCorpus`. Its directory contains only its access registration, with zero generated or scored outputs. It exited 1 after 5.403906 seconds, with user/system CPU 5.468831/0.325486 seconds and peak RSS 305,020,928 bytes. The original `CALIBRATION_PROTOCOL.json`, source and failed process evidence remain unchanged. This role must not be described as never accessed; the precise claim is that the first attempt had no generated quality outcomes.

The repair is limited to three new versioned files. `collect_qualification_v2.py` and `run_v2.py` read the returned corpus and its verified `manifest`; `prospective_v2.py` binds the new calibration-protocol filename. The source reader itself is unchanged. It validates the actual XNIST metadata, pixels, role and writer census before returning `SourceCorpus(..., record)`. [SOURCE_CONTAINER_AMENDMENT_V2.json](SOURCE_CONTAINER_AMENDMENT_V2.json) records the exact diffs, original and new hashes, first failure, prior pixel access, zero outputs, and unchanged source list, models, cuts and gates. [CONTROL_SOURCE_CONTAINER_V2_REVIEW.md](CONTROL_SOURCE_CONTAINER_V2_REVIEW.md) independently checked this chain.

The retry used the same 100 writers under `CALIBRATION_PROTOCOL_V2.json`, SHA `c06e77687dcd7215edabcd41235e5e7383dcb739d05e045b086f20f710482a76`. It completed 30,000 actual outputs in 148.930434 seconds, user/system CPU 135.889178/7.001371 seconds, and peak RSS 304,906,240 bytes. A separate audit checked all 60,000 PNG/text hashes and the equality of score rows, stored arrays and public pre-generation commitments. The complete calibration audit process took 13.213442 seconds and peaked at 110,145,536 bytes.

The frozen calibration has ID acceptance 0.68, absent-input false acceptance 0/100, and in-calibration pooled ID ECE approximately 0.000000620. The near-zero ECE is the expected bin-frequency fitting property, not a new generalization result. Its 100-writer OOD upper bound is 0.029513 and does not itself grant qualification. The unchanged final gate is assessed on the separate fixed 1,000 writers.

`QUALIFICATION_PROTOCOL.json`, SHA `a1c539b539d9b39a1e2f757d52748cb1d1b32ceb490ee47fd3febe753a3dcd39`, bound the actual calibration collection, fixed calibrator, source allocation and candidate dependencies before qualification outcomes. Calibration and part of qualification overlapped one separately recorded ASR qualification process. Their complete shared-environment costs are retained. The actual native comparison waited until the ASR process had exited and the other study collectors had paused. No additional OOM event or kill occurred in these H2 phases.

## 8. Independent 1,000-writer qualification

The complete fixed census contains 50,000 actual outputs from 1,000 writers, with one cycling ID view and the absent view per writer. Pooled verification ID ECE was 0.015368763, all-row ECE 0.007844381, ID acceptance 0.6824, and absent-input false acceptance 0/1,000. The writer-level one-sided 95% OOD upper bound was 0.0029912495. All four original gates passed. These are bounded-task, pooled point ECE gates; they do not certify a population ECE bound, general semantic OOD detection, every action, or an NDU value-error bound. H2 image-refinement ECE was 0.033882 and therefore remained above 3% as an individual diagnostic.

The resource-free selection diagnostic on the same frozen actual counterfactual trees gave NDU selected correctness ECE 0.011891 (H2 0.015943, H1 0.005674). Same-head correctness argmax gave 0.048431 (H2 0.051841, H1 0.042309). The larger qualification cohort is separate from the subsequent native panel, and this diagnostic does not substitute for native execution.

Qualification generation took 250.959422 seconds wall, 227.512163 user CPU seconds, 11.843252 system CPU seconds, and peak RSS 305,278,976 bytes. Independent reconciliation checked all 100,000 PNG/text hashes, registered writer identities, all state/action entries, and exact row/array/public-commit equality. Its complete process took 21.027171 seconds and peaked at 167,055,360 bytes. The fixed verification analysis took 3.189935 seconds and peaked at 339,230,720 bytes. Original raw data and all process receipts remain retained.

## 9. Actual native H2 comparison

`NATIVE_PROTOCOL.json`, SHA `88e2785e85c55496c41e039b36d01380138686d34de7d61cdad8b4cf2c79dc44`, froze the actual qualified package, binary, successful old-source recovery smoke, independent 64-writer source allocation and statistical plan. Each writer contributes two pairs; each policy receives one cycling ID view and an absent-input view per pair. There are 512 total policy episodes. Primary quality and cost estimates below use the 128 ID episodes per policy; the original bootstrap resamples 64 writers, retaining both pairs and both policies together, for the fixed 4,096 draws. The owner is continuous across writers, and this resampling does not replay its state under a different order. The resulting 95% intervals are nominal descriptions of the fixed observed streams; the design did not establish independent restarted-policy trials, stream-order invariance or population coverage.

| ID metric | Native NDU | Same-admission correctness | NDU minus correctness | Nominal fixed-stream writer-bootstrap 95% interval |
| --- | ---: | ---: | ---: | --- |
| CE, gamma 2, after nominal action cost | −0.268273 | −0.279640 | +0.011367 | [−0.087290, 0.106950] |
| Raw terminal utility | 0.512696 | 0.517106 | −0.004410 | [−0.095203, 0.082774] |
| Joint correct | 90/128 (0.703125) | 92/128 (0.718750) | −0.015625 | [−0.070313, 0.031250] |
| Complete public request cost, ms | 40.553962 | 34.940445 | +5.613517 | [2.611169, 9.315001] |

The nominal interval does not establish a CE gain. The observed public cost difference and its nominal interval are positive, but they do not establish a universal causal cost effect for arbitrary stream histories or environments. This experiment does not establish that quality benefits cover execution cost. The primary CE retains the original nominal .002 charge per actual non-stop action; the measured wall-clock cost is a separate observed quantity.

The NDU policy selected 205 actual emitted steps and correctness selected 192. Their actual selected correctness ECE values were 0.057746 and 0.092386, respectively. NDU H2/H1 ECE was 0.057953/0.057401; correctness H2/H1 was 0.099467/0.078223. The 1.19% NDU diagnostic in the separate 1,000-writer census does not certify the 5.77% result in this actual execution panel. These ECE values concern immediate-output correctness, not NDU moment or paired-value calibration.

Admission changed the unrestricted teacher choice on 78 of the NDU policy's 232 ID decisions. Twenty-seven NDU ID episodes and 28 correctness ID episodes reached a rejected H1 decision; the fixed terminal rejection utility of −1 is retained. The constrained policy is thus materially different from the unrestricted teacher. This observation does not identify admission as the sole cause of the unsuccessful quality comparison; source, future-draw and finite-sample variation also remain.

Every NDU choice matched the original floating-point teacher's argmin on the **actual admitted set**. Maximum native-versus-NumPy moment error was 8.88e−16; maximum deviation from the original teacher was 5.86e−7; native-versus-Python raw correctness error was 3.33e−16. These numerical results do not imply equality with the unrestricted teacher policy.

All 708 actual decisions preceded their possible future generation. The 397 actual emitted outputs were written, reopened, observed by the public sensor, committed into NDU projection history, and bound to any subsequent H1 decision. The two policies together performed 196 H1 continuations. Fifty-four invalid requests/outcomes were rejected without changing the owner state; four recovery probes preserved native anchors and episode continuity. The complete private truth audit occurred only after every owner had closed. The fixed independent journal/media/projection/source audit passed and took 2.119240 seconds; it reran no models.

The complete native process took 18.970721 seconds, with 14.395898 user CPU seconds, 1.658809 system CPU seconds and peak RSS 305,164,288 bytes. Request cost includes public initialization, encoding, candidate native ticks, generation, actual output persistence/readback, public observation and feedback. Deliberate negative/recovery probes are separately timed and excluded from the comparison interval, but retained inside complete process cost. Private truth audit and final row serialization remain outside the public request timer and inside that complete cost.

## 10. Resource summary: four measured processes, two N/A recoveries

The original `AUDIT.json` is retained unchanged. Its `all_process_resource_summaries_pass=false` field results from applying `all()` to two `true` values and one `null` per policy. The middle process performed observation/recovery and zero native inference ticks; the original native API correctly returned no resource summary. It is **N/A, not PASS**, and it is not an observed resource-limit failure.

The separate [resource status addendum](evidence/confirm-001-resource-status-addendum.json) reconciles every one of the 708 decisions and all 3,540 timed candidate ticks. Candidate sequences are contiguous and unique: NDU 1–1,800 and correctness 1–1,740. Process frontiers allocate every tick exactly once. Each zero-tick process has frontier 5→5 and unchanged native anchor across both recovery receipts, with unchanged request count and exactly one new observed outcome. This proves no unaccounted inference tick is hidden by its null summary.

An independent reviewer separately reconstructed these intervals and quantiles from every candidate journal row. The [resource status review](review/RESOURCE_STATUS_REVIEW.json) confirms all 3,540 ticks are covered exactly once, four measured summaries pass and the two zero-tick processes are N/A. It leaves the original `AUDIT.json` and effectiveness results unchanged.

For the four processes with actual native ticks, the addendum independently reproduces the original nearest-rank p95/p99 and all three maxima from the candidate receipts; each matches the native summary and passes the unchanged ceilings. The two zero-tick processes remain N/A. The final NDU process has p95/p99 672/1,218 microseconds; correctness has 665/1,452 microseconds. Maximum native-model transient allocation is 768 bytes, checkpoint size 1,568 bytes and write amplification 530,613 ppm. Maximum measured owner transient allocation is 32,988/32,996 bytes. These native scopes do not include the full external encoders or generators and must not be confused with complete process RSS or public request latency.

No original raw result, confidence interval, resource threshold or qualification gate was changed by this classification. The negative effectiveness result, the earlier pilot failures, the initial source-container failure, and the original resource-aggregation field are all retained.

Passing those process quantiles does not mean every individual tick met its ceiling. The complete [single-tick census](evidence/confirm-001-individual-tick-resource-census.json) retains one actual exception: NDU tick 546, case 38's H1 `stop` candidate, took 60,038 microseconds against the original 8,000-microsecond per-tick limit and was rejected. Its confidence was 0.953893, so the confidence gate alone would have admitted it. The other 3,539 candidate ticks had no recorded resource-ceiling violation. The outlier's time and rejection remain in all original observations; no cost trimming or replacement was performed.

## 11. Persistent-stream and feedback interpretation

The [persistent-stream addendum](PERSISTENT_STREAM_ADDENDUM.md) identifies the relevant source paths and reconciles the existing logs. Both policies have 256 episodes spanning 63 writer-boundary transitions. Every logged step inherits the preceding observed modulator without an episode reset. Native temporal state, activity, thresholds, eligibility, sequence and NDU projection persist; the original owner adapter has no separate metabolic subsystem. This makes the nominal-bootstrap limitation above explicit without altering the original calculation.

The frozen numerical drive is constant, and the teacher/correctness heads consume only current public features. The modulator digest is used for identity and durable causal binding, not numeric head modulation or a plasticity update. The actual H2 output-to-H1 public-feature path remains real. These facts support a causal execution and recovery claim, but not an independently measured benefit from numerical NDU projection feedback. The same source-level persistent-owner limitation also applies to the earlier H1 panel; that already sealed study is left untouched and is annotated only in this separate addendum.
