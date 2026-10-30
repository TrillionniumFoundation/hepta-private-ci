# V2 execution and acceptance report

**The registered development run completed; the overall mechanism, stable student-cost-saving, and natural-observer admission gates did not pass.** The implemented generation/control/owner loop is executable and auditable. These results do not qualify an optimal output portfolio, an open-domain multimodal model, or a production deployment.

The original v1 study and its negative results remain intact. V2 changed the training method and observer development, then measured the declared complete panel without changing its thresholds after seeing the results.

- Registered execution source: `9a0b16a620b4203093268a2a917f76bb99eb61ef`.
- [Complete execution, run 41055922354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41055922354): source gate, four controller configurations, observer, native deployment and evidence publication all completed successfully.
- Original compact evidence was committed at `609bc24ff5ea480339935b2053aecd3efc82933f`, directly after the registered source.
- [Original evidence index](runs/9a0b16a620b4203093268a2a917f76bb99eb61ef/INDEX.json), [execution/artifact identities](EXECUTION.json), [remote publication audit](PUBLICATION_AUDIT.json), [complete-panel statistical analysis](analysis/REPORT.md), [machine-readable statistical results](analysis/SUMMARY.json), [controller/native diagnostics](CONTROLLER_DIAGNOSTICS.json.gz), and [independent observer audit](OBSERVER_INDEPENDENT_AUDIT.json).
- No model promotion, confirmation-source consumption or production merge occurred.

## Five work packages: implemented behavior and acceptance

| Work package | Implemented and executed | Acceptance boundary |
| --- | --- | --- |
| Joint generation contract | One `JointGenerationProfile` binds public input, four required outputs, named action/emission randomness, clocks, budgets, actual costs, terminal readback scoring and executable continuation; training/planning/execution/evaluation use it | Closed for this bounded research mechanism |
| Real Hepta backbone | Learned encoders initialize shared, modality and high-dimensional Hepta states; recurrent Hepta content feeds actual PNG/WAV/GIF/text bytes; ordinary parameter-matched controls remain available | Causal/trainable content path established; stable superiority of Hepta across widths is not established |
| Dynamic multistage policy | Up to six continuation decisions choose shared update, a modality, verification or STOP; learned-checkpoint interventions change later actions and delivered content | Active feedback route established; learned risk actor responsiveness and stopping quality remain weak |
| Joint learning and low-cost deployment | Real-output score training, critic learning, student-state DAgger, greedy actor deployment, actual native owner ticks, STOP, owner restart and tensor restoration | Execution passes; quality/noninferiority development margins pass, but stable serving savings and full lifecycle benefit do not |
| Natural tasks and mechanism/scale controls | Complete two-seed/two-width/eight-arm development, source-aware statistical gates, 128-source observer development and preserved original OOF predictions | Observer fails its unchanged 60% threshold; fresh semantic evaluation stays closed; widths 32/64 are small mechanism scales |

## Scope of the model and objective

The generator remains a small restoration mechanism with approximately 596,985–863,161 parameters. Its delivered outputs are a 16 × 16 PNG, 1,024 mono PCM samples, four timed GIF frames, and two categorical ontology labels serialized as UTF-8. These are genuine emitted/readback files, but they do not constitute unrestricted language, music, image or video generation. The current natural diagnostic also operates at deliberately limited bandwidth.

The implementation follows the inherited finite-horizon, undiscounted population exponential-utility profile at gamma = 2:

```text
R = terminal contract utility - executed registered costs
CE(R) = -log(E[exp(-2 R)]) / 2
training moment = E[(exp(-2 R) - 1) / 2]
```

The policy reallocates discrete continuation actions across shared and modality states. It does not solve a continuous Merton allocation problem in closed form. The bounded one-step learned-critic planner is an approximate improvement rule, not an exact HJB solver. General recursive NDU drivers, task-value neuronal free boundaries, continuous renewal/refractory dynamics and global optimality remain unproved extensions.

Hepta retains the declared dual recovery/regeneration, adaptation, positive diffusion, first-passage probability, killed first moment and content recurrence. Its interval-frozen coefficients and end-of-interval hit-mass reset are approximations. The ordinary control is parameter matched; the production Rust owner and its original permission logic remain unchanged.

## What v2 changed

The registered [controller protocol](../../controller_v2_protocol.json) uses seeds 17/29 and widths 32/64. Each of two initial cores per configuration receives 384 supervised updates. A legal continuation sequence of length 1–6 is sampled for prefix supervision, including its initial state and every prefix of that sampled sequence. This is not exhaustive supervision of every possible action sequence.

Each of eight arms receives 64 joint updates with eight real trajectories per update. The arms retain ordinary/Hepta, fixed/dynamic, mean/risk and joint/actor-only controls. The added ordinary-dynamic-risk and Hepta-fixed-risk arms hold risk preference fixed when comparing operator and allocation. The original v1 mean-versus-mean mechanism controls were already valid; the old native teacher-versus-ordinary comparison mixed additional factors.

Every stochastic action and terminal emission now receives a pre-draw, detached critic control variate. Its risk baseline transforms the predicted conditional suffix moment using already incurred prefix cost. Independent-episode residual leave-one-out correction remains. Exact-enumeration tests check the gradient identity and reject a future-dependent baseline. This identity depends on the stated conditional independence and parameter-exogenous physical-timing assumptions; it is not evidence that variance fell in the actual run.

Three DAgger rounds, each using 12 training sources and 64 actor updates, query the bounded planner at student-visited states. Generator and critic remain byte-identical during distillation. Serving uses the greedy student actor without hidden planner queries. The teacher queries are physically executed and charged.

The joint objective still includes a declared 0.05 supervised anchor and gradient clipping. Consequently joint-versus-actor-only combines generator/critic learning and supervised anchoring; it does not isolate reward feedback alone or optimize a pure NDU objective exactly.

## Executed workload

| Phase across all four configurations | Actual four-output trajectories |
| --- | ---: |
| Joint training | 16,384 |
| Primary mechanism evaluation | 2,048 |
| DAgger training | 144 |
| Teacher/student evaluation | 512 |
| Learned feedback diagnostics | 576 |
| Controller subtotal | **19,664** |
| Actual native owner deployment | 24 |
| Registered development and diagnostic total | **19,688** |

The original CI archive audits verified **78,752 delivered output files** for these trajectories, with zero recorded trajectory failures. There were also 3,072 supervised optimizer updates, which are not counted as actual file trajectories. Separate unit-test and source-smoke executions are outside these registered development totals.

The statistical panel contains the four registered configurations exactly once, 32 development source identities per width, and two draws per identity. Training, development and distillation use separate v2 namespaces. Repeated draws, repeated configurations and the native replay do not create new independent source identities.

All four Hepta risk configurations recorded nonzero score-only gradient norms for 59 of 59 checked parameter tensors. This proves coverage at the tensor level, not that every scalar parameter had a nonzero gradient or that its update improved quality.

The independent complete-panel analysis rehashed original trajectory JSON and compact metadata, and checked source/draw/arm completeness, profile/model identity, action sequences, RNG records, cost rows and output digests against the original archive receipts. It did not reopen all media omitted from the compact archives.

## Mechanism results

The registered statistic first computes gamma-2 CE within each training seed, then averages paired per-seed effects. It does not insert training-seed randomness into the risk utility. Intervals use the frozen crossed seed/source bootstrap with 4,000 resamples and Bonferroni adjustment over eight comparison-by-width endpoints. The gate also requires every seed to have the registered favorable direction.

| Width | Matched comparison | Mean CE effect | Adjusted interval | Individual gate |
| --- | --- | ---: | --- | --- |
| 32 | Risk versus mean training | +0.000556816 | [-0.000645817, +0.002279640] | fail |
| 32 | Dynamic versus fixed allocation, risk objective | -0.002132065 | [-0.028571198, +0.017040092] | fail |
| 32 | Hepta versus ordinary, dynamic risk objective | +0.013633493 | [+0.000051060, +0.038668665] | pass |
| 32 | Joint versus actor-only risk training | +0.000022733 | [-0.000138625, +0.000127001] | fail |
| 64 | Risk versus mean training | -0.001324635 | [-0.002801703, -0.000246197] | fail |
| 64 | Dynamic versus fixed allocation, risk objective | +0.000806455 | [-0.000919566, +0.002668685] | fail |
| 64 | Hepta versus ordinary, dynamic risk objective | +0.001337530 | [-0.006641842, +0.004211283] | fail |
| 64 | Joint versus actor-only risk training | +0.000825710 | [+0.000015940, +0.002211223] | pass |

Two of eight individual endpoints pass. Neither favorable mechanism repeats across both widths, so the overall mechanism admission gate fails. The two positive lower bounds are close to zero. The negative risk result at width 64 concerns this finite training procedure; it does not disprove the mathematical risk objective.

Only two training seeds are available. These bootstrap intervals are nominal, approximate intervals with limited seed diversity, and empirical CE has finite-sample plug-in bias. This is development evidence, not independent confirmation.

## Distillation results

The frozen development margins for both utility CE and audit-inclusive net CE are -0.005. They are study design choices, not established application standards. Strictly positive serving-cost savings are a separate required endpoint.

| Width | Student minus teacher metric | Mean effect | Adjusted interval | Gate |
| --- | --- | ---: | --- | --- |
| 32 | Utility CE | -0.000510152 | [-0.001719972, +0.000096372] | noninferiority passes |
| 32 | Net CE | +0.000128270 | [-0.001927308, +0.001361516] | noninferiority passes |
| 32 | Cost saving, teacher minus student | +0.000674811 | [-0.001179545, +0.001616040] | fails |
| 64 | Utility CE | -0.000126761 | [-0.000492353, +0.000261903] | noninferiority passes |
| 64 | Net CE | +0.000634272 | [-0.004421934, +0.005058829] | noninferiority passes |
| 64 | Cost saving, teacher minus student | +0.000674819 | [-0.004358748, +0.004874248] | fails |

Intervals use the registered six-endpoint family adjustment. Both cost intervals cross zero, and the seed-17/width-64 student actually costs more. The overall distillation admission gate fails despite favorable average cost differences. No deployment promotion or confirmation follows.

## Feedback and stopping diagnosis

Learned checkpoints were probed on the same eight development sources using a forced shared/verify prefix, then bounded low/high feedback interventions and an identical-feedback repeat control. The high intervention is 75% of feasible public-mask-derived error bounds and applies at every verification starting at the second decision; it is not a natural sensor-feedback sample or a single one-time perturbation.

Across four configurations × eight source pairs, the greedy student changed later actions in 22/32 pairs, and both actions and actual output digests in **21/32**. The learned risk actor changed both in only **1/32**. All **192/192** identical-feedback controls had identical actions and content. The fixed-state actor-law probe holds logical budget/state constant; full executions separately retain physical clocks.

This establishes a learned causal feedback route, especially in the distilled student, but not generalization to unseen natural feedback. The 32 configuration/source pairs reuse eight unique sources.

The planner's teacher evaluation contained 514 verification actions. In **416/514**, the shared/core/feedback/modality/generation hashes were unchanged while clock and charged cost advanced. Repeated verification can therefore consume resources without improving this recorded state. At seed 17/width 64, the risk learner's mean continuations rose from 4.469 in the first eight updates to 4.922 in the last eight; verification rose from 0.938 to 1.656 and forced-horizon STOP rose from 57.8% to 65.6%. These are descriptive windows with different sampled contexts, not paired causal estimates.

The new-to-old leave-one-out score-coefficient mean-square ratios were 2.36, 6.50, 6.78 and 5.45 across the four configurations. Coefficient second moments are not gradient-variance measurements, so this run does not establish variance reduction. Aggregate critic calibration is also not a proof of conditional STOP-value calibration.

There is no immediate post-encoding STOP control: the current runtime forbids STOP at decision zero. These results therefore do not establish that encoding alone already supplies the necessary output.

## Actual owner/checkpoint deployment

The native experiment uses the preregistered first configuration, seed 17/width 32, rather than selecting the best outcome. It loads the actual teacher, student and ordinary-dynamic-risk checkpoints from the completed study.

- 24/24 successful episodes and 96 verified delivered files.
- 483 actual owner ticks.
- 27 normally reaped, experiment-owned child processes.
- Three new-OS-owner-process recoveries.
- Three actual tensor restorations in the same Python process, with independently inspected restored tensor identities.
- Actual STOP acknowledgements and unchanged original owner permissions.

Separate existing tests cover new-Python-process continuation. The deployment experiment itself does not claim that stronger restart setting. The trained tensor model runs in Python/Torch under the native guard; it has not been ported into the Rust diagnostic readout.

| Candidate | Serving CE | Audit-inclusive CE | Mean utility | Mean serving cost |
| --- | ---: | ---: | ---: | ---: |
| Hepta critic planner | 0.688952451 | 0.688785917 | 0.737143159 | 0.030107934 |
| Hepta greedy student | 0.689992141 | 0.689825166 | 0.736066762 | 0.027679457 |
| Ordinary dynamic risk | 0.727121149 | 0.726986112 | 0.758114867 | 0.021185465 |

The student costs about 8.07% less than the teacher in this engineering subset. Its serving CE difference is +0.001039690 with a source-bootstrap 95% interval [-0.000606796, +0.002488584]. This small reused subset cannot supersede the complete-panel cost gate. The ordinary candidate is better in both reported mean cost and CE here; planner/student/ordinary differences also change policy behavior, so they do not isolate a pure Hepta effect.

All 24 native actions, output hashes and utilities match the corresponding original development source/draw records. These are new execution and resource measurements, not independent quality samples. Study input files were unchanged before and after deployment. The unchanged native binary has SHA-256 `00c183e2433ba96412c5e248753721a4211c34831ad531f2d5742e9f16f8d3c9`.

## Natural observer: complete negative development result

The observer expanded only the original observer-training prefix to 128 sources and 639 events. It retained the full 63-action/17-sound ontology, five source-grouped folds, train-fold-only normalization/regression, source-uniform weighting, and the original requirement that both modalities reach at least 60% and strictly beat the fold-trained majority.

It executed 42 closed-form ridge fits with frozen pretrained feature backbones; there were zero neural optimizer updates. Selected candidates and all alternatives were independently recomputed from original OOF predictions, labels, source IDs and fold membership.

| Modality / candidate | Source-uniform OOF accuracy | Fold-trained majority |
| --- | ---: | ---: |
| Action: S3D ridge100 | 18.511905% | 10.348772% |
| Action: TSM ridge1 | 17.114025% | 10.348772% |
| Action: TSM ridge10 | 17.973400% | 10.348772% |
| **Action: TSM ridge100, selected** | **22.440476%** | 10.348772% |
| **Sound: PANN ridge100, selected** | **42.450707%** | 35.429687% |
| Sound: temporal PANN ridge1 | 40.072545% | 35.429687% |
| Sound: temporal PANN ridge10 | 40.156250% | 35.429687% |
| Sound: temporal PANN ridge100 | 41.471354% | 35.429687% |

On the same 128-source cohort, the selected TSM improves action accuracy over S3D by 3.928571 percentage points. The best temporal audio candidate trails original PANN by 0.979353 points. Differences between v1's 64-source scores and v2's 128-source scores cannot be attributed solely to feature quality.

Only 42/63 action and 12/17 sound classes occur in this development cohort. OOF labels unseen in their corresponding training fold account for 3.017113% source-weighted action mass and 0% sound mass. Sound labels occupy less than one quarter of the two-second target window for 39.111793% of source-weighted events. These are measured data/representation limitations, not permission to relabel classes or lower the gate.

Both selected accuracies remain below 60%. The run is a complete scientific negative result, not an execution failure. All 64 fresh calibration sources remain unopened, fresh predictions are zero, and generated-output reliability/semantic qualification remain false. Candidate selection and OOF reporting share development data and cannot serve as independent confirmation even if a development threshold were passed.

The independent audit verified 149 compact stored files, 146 preserved original files, 128 source receipts, all 639 events, all 42 fits and both safe NPZ model identities. It matched 2,556 media hashes between receipts and the complete input inventory. It did not download/reopen the 1.2 GB original media; the CI archive hashed those input files before and after preservation.

## Cost accounting

Costs are registered normalized-utility tariff units, not dollars. CPU and wall time are charged at 0.02 and 0.001 units per second. A whole-process meter already contains episode CPU/wall work, so adding full episode bills again would double-charge time. Fixed action, first-encoding and terminal-delivery service fees must instead be added once.

For all four controller configurations:

| Recorded scope | Tariff cost |
| --- | ---: |
| Whole-process time, including active supervisor | 26.372248425 |
| Fixed service fees inside those processes | 375.029500000 |
| Process time plus fixed fees | 401.401748425 |
| Separate post-meter feedback diagnostics | 12.404278401 |
| **Combined observed controller/feedback cost** | **413.806026826** |

The source/trajectory/event reconciliation for every configuration is in [the complete-panel report](analysis/REPORT.md). Terminal delivery records its measured time-tariff total, so no unrecorded CPU/wall split is invented.

The separate observer meter records 2,731.242821 child CPU seconds, 1.168420 active-supervisor CPU seconds, 1,150.946777 wall seconds and 55.799171597 tariff units. The separate native meter records 9.721689 child CPU seconds, 8.922617 wall seconds and 0.203574897 time-tariff units; that number alone is not a full native action-service bill and is not added to a claimed all-in total.

Provisioning, package installation, infrastructure/acquisition fees, repository/artifact transfer, standalone archive/analysis/publication, parent startup before meter entry, and some feedback startup/final-summary work are outside recorded scopes. Unmeasured cost is not zero. The 413.806026826 total is consequently a lower bound for the wider controller research operation, not proof of favorable full lifecycle economics.

No arbitrary allocation of shared development expense to candidates or a chosen serving horizon was used to manufacture savings. The registered 10,000-episode lifecycle confirmation remains unexecuted because its development admission failed.

## Validation and preservation

The registered source passed **134 package tests** plus an eight-arm real-output smoke before training. The final read-only summarizer adds five tests covering incomplete panels, decompressed-original identity, RNG/cost consistency and process-fee reconciliation. The local final package ran **139/139 tests successfully** with the same import mode as CI. Exact-final-commit CI is linked in the PR; no scientific run is repeated by a documentation/analysis commit.

All six compact artifacts were preserved in Git. They contain every trained controller checkpoint and sidecar (32 arm models plus four students), three native intermediate-state checkpoints, two observer NPZ models, original result/OOF/allocation/source/process records, and all 19,688 original trajectory JSON records in deterministic archives. The evidence index retains failed scientific flags. Byte manifests bind stored and decompressed originals.

An independent remote-publication audit checked all six downloaded ZIP digests and every one of their 311 stored file members (218,711,769 bytes) against the remote Git tree at the evidence commit. All Git blob identities, byte counts, stored SHA-256 values and six manifest/audit-to-index bindings matched; the additional INDEX makes 312 committed files at that original publication. The observer freeze retains 5,112 OOF predictions across eight candidates and 639 events. This is an identity/integrity audit, not new semantic or efficacy evidence.

The [native sample bundles](native_samples/README.md) additionally preserve the exact 12 output files from source 0/draw 0 for the teacher, student and ordinary candidate. Selection follows the first registered source, not outcome quality; bytes were copied from the verified original native artifact and matched to raw trajectories, source/RNG/model identity and the original inventory. No output was regenerated or re-encoded. These tiny synthetic restoration examples add inspectable content, not independent quality observations.

The remaining raw output media, pretrained feature files, and the original 1.2 GB observer working directory remain in the run's separate 30-day Actions artifacts; they are not all duplicated into Git. The compact archives support exact trajectory/model/OOF review but cannot independently reopen omitted media after those full artifacts expire. `EXECUTION.json` preserves artifact identifiers, sizes and digests.

No frozen protocol, training source, gate or original evidence was modified after this result. The newly added summarizer and this report are explicitly post-execution analysis products.

## Remaining research work

The next development should focus on the measured failure mechanisms before increasing model scale:

1. Calibrate STOP versus continuation on actual prefix states and separate immediate-delivery, one-more-update and verification values. Register a treatment for repeated no-information verification and an immediate post-encoding delivery control before evaluating it.
2. Measure actual gradient variance and conditional critic calibration on held-out development trajectories. A predictable baseline is mathematically admissible without being statistically useful; the present coefficient diagnostic gives no evidence of improvement.
3. Improve source/class/time coverage and observer representations on observer-training sources, preserving source roles and the untouched fresh set. Establish generated-output observer reliability before using its score for a semantic generation claim.
4. Only after development admission, run the registered new-source/new-seed confirmation with the full six-component lifecycle ledger. Confirm stable quality-adjusted net benefit before model promotion or larger semantic training.

These are identified next experiments, not completed results or permission to reinterpret this run's failures.

