# H2 native teacher: development and integration evidence

The native H2 adapter compiles against the unchanged original owner. A separately registered, larger historical development experiment has passed the original pooled feasibility limits after 40,000 actual generated and reopened outputs. **Independent H2 qualification and successful native H2 execution are still pending.** No model outcome from any of the three reserved XNIST H2 roles has been opened as of this report. Authority remains `deny_all`.

The two earlier 64/64 pilot failures remain failures. The larger experiment uses the second predictor's exact weights, normalization, cuts and three-bin rule; it does not retroactively replace either result. Selection-conditioned calibration also remains a material limitation: the larger held panel's selected NDU ECE is 0.057179 despite pooled ID ECE 0.017188.

## 1. What is implemented

The exact evaluated seed-17 teacher is preserved. It estimates five conditional exponential moments for the remaining one or two steps, with gamma 2 and the original nominal .002 charge per non-stop action. The model service computes its fixed public first layer. Rust loads the final moment layer and chooses the minimum value on the original owner's admitted feasible action set. This is not a correctness-argmax substitution for the NDU objective.

The new correctness head is separate from the teacher and controls admission. Its target is the **immediate emitted output** after each candidate action at the H2 root and all four reachable H1 children. A semantic investment whose current draft is poor can consequently be excluded even if its continuation has value. The resulting constrained policy is not functionally identical to the unrestricted teacher. Numerical head tolerance, raw floating-point teacher action parity, admission-masked action parity, and actual quality gains are separate measurements in the planned native execution.

The public ABI has 103 Q24 coordinates: four absence features, two action flags, remaining horizon, 32 teacher activations and 64 correctness activations. Encoder work belongs to execution cost. Native layers, original resource ceilings, durable pre-RNG action commitment, episode continuation, and NDU projection feedback are implemented without changing product sources or the previous H1 experiment.

An H1 continuation must bind the preceding actual result's public-state digest and native outcome digest. Wrong episode, parent, state, horizon, duplicates and unfinished decisions are rejected before a native tick. Planned recovery probes cover interruption after an H2 decision and restart after its actual output before the H1 continuation. These recovery paths have not yet been exercised with a newly qualified H2 model.

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

## 6. Next fixed stages and remaining limits

The reserved new roles remain 100 calibration writers, 1,000 qualification writers, and 64 execution writers with two pairs each. Metadata-only exclusion checks are recorded in [SOURCE_STATIC_AUDIT.json](SOURCE_STATIC_AUDIT.json). Their prospective sequence is now permitted by the larger old feasibility result, but each phase still requires its own actual candidate and data freeze before opening outcomes. The original four admission gates remain unchanged.

The next stages are: collect 30,000 actual calibration outcomes from the 100 new writers; freeze the resulting calibrator; collect 50,000 actual qualification outcomes from the fixed 1,000 new writers; and only after all gates pass, run the independent native panel with same-admission correctness argmax, causal feedback, recovery probes and writer-cluster analysis. Any failed gate stops that path and is retained. Neither the unused 72 old pairs nor 85 unallocated new writers is used to expand toward a pass.

Outstanding conclusions require those measurements: H2 qualification, selection-conditioned calibration, actual constrained-policy gains, complete owner resource compliance and recovery behavior. The previous unrestricted teacher's independent positive control result does not transfer to this masked native policy. Production trust material, authenticated outcome ownership and the complete daemon/model-service lifecycle remain outside this research owner execution. No CI status is used.
