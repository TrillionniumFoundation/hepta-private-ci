# Execution and research acceptance — 2026-10-29

**The five engineering work packages are implemented and the registered experiments have executed. Stable portfolio benefit, student quality noninferiority, and natural semantic qualification have not been established.** All negative findings are retained. This is a small four-output restoration research mechanism, not a trained general-purpose multimodal foundation model.

The PR is [#4225](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4225), based on immutable `a50c8974ac23c20c5174f7c3ad542a96e5652854`. Existing v6/unified models, production owner code, and earlier failed research evidence are unchanged.

## Work-package acceptance

| Work package | Executed implementation | Current acceptance |
| --- | --- | --- |
| Joint contract | One frozen profile binds input visibility, required outputs, RNG laws, media/decision/compute clocks, costs, scoring, continuation, and identities across training/planning/execution/evaluation | Contract and actual readback checks pass |
| Trainable Hepta backbone | Learned encoders, shared semantic state, four modality latents, high-dimensional dual recovery/regeneration and real output heads; ordinary parameter-matched control retained | Actual output intervention and score-only gradients pass; comparative benefit not established |
| Dynamic policy | `shared/image/audio/video/text/verify/stop`, feedback-dependent reselection, bounded critic lookahead, delivery critic, actual STOP and continuation | Feedback intervention changes later actions and emitted bytes; global optimality is not claimed |
| Joint training and deployment | Supervised initialization, joint generator/actor/critic learning, planner distillation, actual tensor restoration and unchanged native owner gate | 96/96 native episodes succeed; stable full-cost benefit and student quality noninferiority do not pass |
| Natural tasks and controls | Source-isolated observer development, full seed/width controls, real-media generation diagnostic, frozen fresh-source admission gate | Studies complete; observer development fails, fresh semantic qualification remains closed |

## Exact execution evidence

- **Mechanism:** [run 40834365977](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40834365977), source `5a4a763c0001010c172bcef057e137adc636b477`. All six mechanism matrix jobs completed. The overall run is recorded as failure because its separate first natural jobs lacked ffmpeg; it must not be described as an all-green run.
- **Latest trained-deployment source gate:** [run 40835998756, job 123320806292](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40835998756/job/123320806292), source `8eca54312d46cc8f4eb6e00ba4338007ba366496`: **65 unittest + 28 pytest = 93 passing tests**, plus the six-arm smoke run.
- **Native deployment:** [run 40835998800](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40835998800), source `8eca54312d46cc8f4eb6e00ba4338007ba366496`, job `123320806552`: complete trained candidates, original owner build and lifecycle, 96 actual deployments, and source artifact immutability checks pass.
- **Natural generation and observer:** [run 40835309016](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40835309016), source `86baffaeb8b99c151b2f36fd3824242f301a1580`; jobs `123318581258` and `123318580900` completed, while research gates retain their actual failed values.
- **Independent archived-evidence check:** [run 40838061875](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40838061875), source `451f0454f1d9cd2d7ca6c26f7c66a51b6e2e8dcf`, job `123327459299`: both pinned natural ZIP identities, frozen source files, source allocation, all 2,336 generator trajectories, model file identities, OOF accuracy and majority control were checked. No training or fresh-media access occurred. A second [read-only preservation run 40839118193](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40839118193), source `3e300df4299471436433fecedbd9303a994f7fbb`, retained the original OOF freeze, failed result and frozen allocation byte-for-byte; the measured evidence stayed unchanged.

The requested repository-wide `just fmt` could not run in the local sparse checkout: `just` and the full Rust worktree are absent. No production Rust source was modified. The actual original-owner build and its executed lifecycle were verified in the native CI runs above.

Tests include actual-file score gradients, independent analytic/finite-difference gradient checks, feedback intervention, immutable contract and budget chains, checkpoint corruption and source mismatch rejection, new-OS-process continuation, native build dependency identity, and candidate migration. The native deployment restores tensors within the Python process and independently reopens the owner in a new OS process; it does not claim that those 96 episodes also restarted the Python process.

## Registered mechanism study

Seeds 17/29/43 crossed with widths 32/64 give six configurations. Width 32 has 596,985 parameters per arm; width 64 has 863,161. Each configuration uses two initial cores with 384 supervised updates each, six arms with 64 joint updates × 8 actual draws, and 128 test draws per arm from 64 source identities. Total: **18,432 actual joint-training trajectories and 4,608 primary evaluation trajectories**, plus separate distillation work. Depth is one.

The evaluated quantity is the empirical plug-in estimate of the registered population gamma=2 certainty equivalent, using actual registered serving cost; final audit-seal cost is reported separately. It is not a token likelihood, a single-trajectory utility, or a proof that a global NDU optimum has been reached.

| Seed / width | Risk − mean | Dynamic − fixed | Hepta − ordinary | Joint − actor-only |
| --- | ---: | ---: | ---: | ---: |
| 17 / 32 | +0.002362 | -0.018738 | -0.009213 | -0.000786 |
| 17 / 64 | -0.001732 | -0.003625 | +0.000508 | -0.000193 |
| 29 / 32 | -0.000353 | +0.003234 | -0.003125 | +0.001215 |
| 29 / 64 | -0.000222 | +0.007655 | +0.007409 | +0.001198 |
| 43 / 32 | -0.010295 | -0.034077 | +0.009825 | +0.001116 |
| 43 / 64 | -0.001213 | +0.000435 | -0.000744 | +0.000158 |

A source-paired 95% bootstrap lower bound is positive in **0/6, 1/6, 1/6, and 2/6 configurations**, respectively. The frozen requirement for consistent positive lower bounds across configurations is not met. Intervals are per comparison, unadjusted for multiplicity, and do not include training-seed uncertainty; the same test source identities recur across configurations, so the six rows are not independent statistical replications. Empirical CE also has finite-sample plug-in bias.

Controls are defined in [mechanism_results.json](mechanism_results.json): risk versus mean holds the dual/dynamic generator family fixed; dynamic versus fixed holds dual/mean fixed; dual versus ordinary holds dynamic/mean fixed. Joint versus actor-only additionally differs in generator/critic updates and the declared supervised anchor. It does not isolate a pure reward-only training effect. Parameter counts match within a configuration, but physical compute cost is measured rather than assumed equal.

The complete source-paired intervals, all six arms, distillation outcomes, artifact identities and qualification flags remain in that JSON. The first registered configuration is preserved with its original weights; it was not chosen for the best observed outcome.

## Full native deployment

The registered seed17/width32 teacher, distilled student and ordinary control each executed 16 existing synthetic test sources × 2 draws through the unchanged owner. All **384 delivered media/text files** were independently rehashed against the actual trajectories.

| Candidate / strategy | Episodes | Empirical CE | Mean utility | Mean serving cost | Native ticks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Teacher / planner | 32/32 | 0.8454960824 | 0.8752644062 | 0.0261218976 | 500 |
| Student / greedy | 32/32 | 0.8322824755 | 0.8674150910 | 0.0257809188 | 524 |
| Ordinary / dynamic | 32/32 | 0.7777280423 | 0.8213961404 | 0.0236603894 | 587 |

There were **1,611 native ticks, three actual owner-process recoveries, three tensor-state restores, and zero episode failures**. The first episode of each arm performed both recovery operations. Child CPU was reaped and included without double counting. `DENY_ALL` remains intact; the bounded local research dispatcher performs generation in Python/Torch. The diagnostic native readout neither selects the trained policy's actions nor executes the tensor backbone inside a Rust inference port.

Teacher minus ordinary CE is +0.06776804, 95% source interval [+0.02376890, +0.12268363]. This comparison simultaneously changes operator, training objective and planner; it is not a causal estimate of the Hepta operator contribution. In the original isolated seed17/width32 operator comparison, Hepta minus ordinary is −0.00921315, interval [−0.01909710, −0.00101550].

Student minus teacher CE is **−0.01321361**, interval **[−0.04536667, +0.00578427]**. Student serving cost is lower by 0.0003409788 tariff units, about **1.305%**. Including measured distillation and relative model-loading cost gives a descriptive **cost-only break-even of 116 episodes**. No noninferiority margin was registered, and the interval permits a material utility loss. This is not an NDU break-even or an established low-cost quality-preserving deployment. In the original non-native first-configuration distillation evaluation the student was more expensive by +0.0003197243; cost savings are not yet stable across execution conditions.

The teacher/student output bundles, action sequences and observer utilities are exactly the same as their corresponding original study draws. These are reused inputs and random draws: the added evidence is actual native execution, recovery and cost, not independent new quality samples. Loading cost excludes Python startup/imports; common pretraining, candidate selection and cross-host uncertainty are outside the descriptive amortization calculation. The final immutable audit seal is reported separately as a cost sensitivity.

See [deployment_summary.json](deployment_summary.json) and the preserved full [deployment_results.json.gz](deployment_results.json.gz).

## Natural-task results

### Generator diagnostic

Eight original `generator_train` sources retain that role: four for fitting and four for internal diagnostics. Both dual and ordinary generators ran 256 supervised updates and 32 joint updates at batch size four. **2,304 training episodes plus 32 evaluation episodes were verified, with zero failures.** Both arms have 59/59 recorded nonzero score-only parameter tensors; total joint-loss coverage is 67 tensors per arm. This is evidence of a trainable content path, not evidence of a beneficial learning direction.

| Arm | Fitting four-source CE | Internal four-source CE |
| --- | ---: | ---: |
| Dual | 0.8320046188 | 0.48596499996 |
| Ordinary | 0.8556647722 | 0.45810956222 |

The internal difference is +0.02785543774. Four internal sources and reconstruction/ontology metrics do not establish natural semantic generalization. `semantic_qualified`, `efficacy_qualified` and `never_seen_data_claim` remain false.

The media clock is two seconds: 16×16 images, four GIF frames at 500 ms, and 1,024 audio samples at 512 Hz after anti-aliasing. Text consists of two ontology labels. This bandwidth-limited target is not ordinary natural-language or high-fidelity audiovisual generation.

### Independent observer

Observer training used **64 original observer-training sources, 301 events and 11,264 optimizer updates**, with complete source-grouped five-fold cross-validation. The read-only checker independently recomputed source-weighted accuracy from the complete OOF predictions and original labels.

| Selected task/head | OOF accuracy | Source-weighted majority | Registered minimum |
| --- | ---: | ---: | ---: |
| Action / MLP128 | 15.75521% | 21.08073% | 60%, and strictly above majority |
| Sound / ridge100 | 38.48772% | 36.60900% | 60%, and strictly above majority |

**The observer development gate failed.** Action is below even the majority control. The 64 allocated fresh calibration sources have no consumption marker, prepared receipt or calibration predictions; their media were not opened. Generated-output reliability is not established. The early-stop result lacks that reliability field; the inspector explicitly records absence/null instead of converting it into a pass. Semantic qualification remains closed.

Full compact evidence is [natural_inspection.json](natural_inspection.json). The original complete per-event OOF predictions/labels, failed observer result and allocation are preserved under [observer/](observer/) as deterministic gzip, so source-weighted accuracy remains independently recomputable after the raw artifact expires. The original observer tensor weights and raw media remain only in that expiring artifact. The original complete generator results and frozen allocation are retained as deterministic gzip files. Original observer source roles and the earlier excluded sources were not reassigned to obtain a passing result.

## Preserved deliverables and limitations

[Checkpoints](../checkpoints/README.md) preserve five original, unquantized tensor files with their exact sidecars: first-configuration teacher/student/ordinary plus both natural diagnostic models. [MANIFEST.json](../checkpoints/MANIFEST.json) records archive/run/job/source identity, SHA256, Git blob SHA1, exact byte sizes, original archive member paths and deterministic-gzip mappings. All three locally downloaded ZIPs were independently rehashed against their pinned SHA256 before selection. The first source/draw from each native arm is also preserved under `examples/`, including all four actual output files and its compressed original trajectory, selected by order without quality filtering. Raw Actions artifacts have the recorded 2026-11-28 expiry; the committed weights, selected original results and compact all-configuration evidence survive that expiry.

These artifacts do not imply trained large-model capacity, high-fidelity semantic generation, global dynamic-programming optimality, a value-dependent neuronal free boundary, or exact continuous renewal dynamics. The Hepta operator uses frozen-interval first-passage moments with end-of-interval reset. The implemented preference is the inherited finite-horizon gamma=2 profile; general recursive NDU drivers are not solved. Supervised anchoring and gradient clipping alter the pure-NDU optimizer, and the direct parameter derivative of physical timing is not modeled. Actual timing is charged, but no worst-case physical execution tail bound is proved.

The first natural attempts failed for missing ffmpeg, then for invalid annotation/target-window metadata before allocation was frozen. Dependencies and eligibility validation were corrected with recorded history, without changing source roles, overlap threshold or the evaluation gate. Those infrastructure failures are not scientific evidence against the hypothesis. The final observer failure is a measured scientific result and remains preserved.

The next research gate is improved observer reliability using existing training sources, followed by a new frozen evaluation protocol before any fresh cohort is consumed. Mechanism development should address score variance, conditional critic calibration and controller behavior on the existing development data before another registered replication. Greater scale is a subsequent experiment; this run does not authorize a positive effect claim or automatic promotion to production.
