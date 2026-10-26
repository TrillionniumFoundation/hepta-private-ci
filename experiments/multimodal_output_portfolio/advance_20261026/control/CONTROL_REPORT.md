# Advance control: registered result and remaining limitations

## Result

The frozen `constrained_paired` candidate passed the registered primary comparison against `masked_teacher` on 85 previously unused writer clusters. Its action-cost-adjusted certainty equivalent improved by **0.0110770263**, with a **98.333333% paired writer-cluster percentile interval of [0.0019457451, 0.0205950221]**. All 5,440 actual requests finished without an operational failure. This establishes a benefit for the complete frozen candidate within this experiment's original five-action, text/image generator and common static admission mask. It grants no production authority. [Evidence: `CONFIRMATION_PROTOCOL.json`, `CONFIRMATION_RESULT.json`, `CONFIRMATION_PROCESS.json`.]

Several research questions remain open. On actual same-state H1 alternatives, the candidate's action-difference MSE did not beat a zero-difference predictor, and its realized feasible regret had a worse point estimate than the teacher. Correctness forecasts made at the initial decision remained substantially miscalibrated against the complete terminal outcome. The candidate changes several mechanisms together, so this comparison cannot assign the gain exclusively to the new constraint-aware backup. These limitations remain part of the result. [Evidence: `CONFIRMATION_RESULT.json`.]

## Frozen question and intervention

The generator, public sensor, private observers and original action family were frozen. The five actions are `stop`, `refine_semantic`, `refine_image`, `refine_text` and `couple`, with a two-decision horizon. Both policies use the same previously frozen correctness predictor and calibration map; H1 semantic refinement remains disabled. An empty feasible set produces an explicit rejection with utility -1 and strict success 0, while retaining already incurred action costs. It is distinct from retaining a draft through an admitted stop. This comparison did not execute the native owner, and it does not model unknown future native resource rejections. [Evidence: `online.py`, `features.py`, `CONFIRMATION_PROTOCOL.json`.]

The candidate combines four changes:

1. Its H2 training backup follows an out-of-fold H1 policy subject to the actual frozen future correctness mask. The backup records the selected actual endpoint, or rejection when no future action is admitted, and includes the first action's cost. It does not use the best realized held-out outcome as its policy target.
2. It fits the stop exponential moment and four signed action-minus-stop moment differences directly.
3. It uses 109 public features, including the frozen admission outputs and H1 public caption/image agreement. That agreement is an observation of the generated output, not independently verified target truth.
4. It deploys a small affine value head in place of the teacher's nonlinear head. The shared public-feature and admission computations remain in the measured execution cost.

Only the preregistered ridge values 0.001, 0.01 and 0.1 were tried on already opened historical fit/selection sources, explicitly reused as development. The fixed selection rule chose ridge 0.1, trained seed 17, before the fresh source panel was opened. All three checkpoints and their backups are retained. The frozen admission predictor had previously used some of those old sources; value-head cross-fitting does not turn them into independent admission qualification data. [Evidence: `DEVELOPMENT_PROTOCOL.json`, `DEVELOPMENT_RESULTS.json`, `SELECTED_VALUE.json`.]

The selected checkpoint SHA-256 is `205940fb455c39459c8d3c7ace1b629c29a5ae88c08248bc9c44088609a4dd97`. The formal protocol SHA-256 is `be0b345d8ad76758292b4c675bc41e28528aaf2bebee6aef3470f3d91461a28d`. Its 75 pinned dependencies were checked before execution and again during the frozen analysis. No candidate was adjusted using these confirmation outcomes. [Evidence: `CONFIRMATION_PROTOCOL.json`, raw `confirmation-001/registration.json`, `analyze_confirm.py`.]

## Sources, information boundary and inference

The panel contains 170 source pairs from 85 previously unused XNIST writers. Each pair is evaluated in all eight registered views, with two future draws and both policies: 170 × 8 × 2 × 2 = 5,440 requests. Both pairs, every view and both draws of a writer remain together during resampling. The two draws share an initial draft and do not count as independent source clusters. The fixed trained seed is also not a replicated training-seed experiment. Metadata, source bytes and previous-role exclusions are audited separately. [Evidence: `../SOURCE_ALLOCATION.json`, `review/SOURCE_REVIEW.json`, `review/SOURCE_BYTES_ADDENDUM.json`, `CONFIRMATION_PROTOCOL.json`.]

The policy receives only the current public observation and remaining horizon. Its action is durably recorded before any subsequent decoder innovation. Paired policies share a future innovation only when their full committed action paths match. The order of the two policies is randomized by the registered driver seed. Every online request finishes before private targets enter a judge. Actual saved output bytes are read back and checked against their SHA-256 identities before scoring. This is an auditable Python data-flow boundary; it is not a hostile-code isolation mechanism. [Evidence: `confirm.py`, `online.py`, raw request, commitment and media records.]

For a terminal utility \(U\) and number of attempted non-stop actions \(N\), the primary outcome is

\[
\operatorname{CE}(U-0.002N)
=-\frac12\log\operatorname{E}\left[\exp\{-2(U-0.002N)\}\right].
\]

The expectation is estimated over the complete registered panel. The frozen observer defines delivered-output utility; rejection or operational failure receives -1. The registered inferential contrast is candidate minus teacher. The analysis uses 16,384 paired writer-cluster resamples with fixed bootstrap seed 202610261803. Three efficacy families share the source panel, so the prospectively allocated two-sided significance level is 0.05/3, giving the 98.333333% interval. Their evidence is correlated rather than three independent source replications. The percentile interval is conditional on this trained candidate and source design; it is not a finite-sample coverage theorem or a claim about variation across training seeds. [Evidence: `../REGISTRATION.json`, `CONFIRMATION_PROTOCOL.json`, `analyze_confirm.py`.]

## Main outcomes

| Measure | Masked teacher | Constrained paired candidate |
| --- | ---: | ---: |
| Registered action-cost CE | -0.6176347549 | -0.6065577287 |
| Raw CE | -0.6161574390 | -0.6051267264 |
| Secondary-observer CE | -0.6162507104 | -0.6050589801 |
| Strict success, including rejections | 0.5235294118 | 0.5297794118 |
| Mean attempted non-stop actions | 1.0117647059 | 0.6069852941 |
| Content rejections / 2,720 requests | 1,231 | 1,202 |
| Operational failures | 0 | 0 |

The registered primary interval excludes zero in the favorable direction and the operational gate passes. Strict success improves by 0.00625, or 0.625 percentage points, as a descriptive result. Secondary-observer CE, rejection counts and strict success have no additional confirmatory alpha allocation. The absolute CE values remain negative because explicit rejections receive utility -1 and the exponential criterion weights poor outcomes strongly. [Evidence: `CONFIRMATION_RESULT.json`, `CONFIRMATION_COMPLETION.json`.]

### Real execution cost

| Measured cost | Masked teacher | Constrained paired candidate |
| --- | ---: | ---: |
| Mean request CPU, ms | 14.2333563 | 12.3502620 |
| Mean request wall time, ms | 17.6297538 | 14.4838642 |
| Mean feature CPU per decision, ms | 1.2876097 | 1.3181907 |
| Mean admission CPU per decision, ms | 2.3890784 | 2.3955329 |
| Mean value-head CPU per decision, ms | 0.1701167 | 0.0300127 |

The candidate uses approximately 13.23% less mean request CPU and 17.84% less mean request wall time in this run, with 40.01% fewer non-stop actions. These are observed point estimates, not separately qualified population timing gains. The affine head is cheaper, but the common feature and admission computations still dominate value-head cost. Fewer executed continuations are another contributor; this experiment does not isolate the head replacement's causal contribution. [Evidence: `CONFIRMATION_RESULT.json`.]

Request timings include initialization, actual generation, shared features/admission, the selected value head, durable action commitment, output persistence/readback, and a diagnostic state clone on candidate H1 visits. Source decoding, resident model loading, private judging and subsequent counterfactual enumeration are accounted for separately within the full process. The full execution took 140.283229 seconds wall time and 104.723782 seconds child CPU, with peak RSS 307,089,408 bytes and no increase in OOM events. The independently measured frozen analysis completed with exit code 0 in 0.698007 seconds wall time and peak RSS 73,183,232 bytes. [Evidence: `CONFIRMATION_PROCESS.json`, `CONFIRMATION_ANALYSIS_PROCESS.json`.]

The cost of 0.002 per attempted action is the preregistered utility charge. It is not a monetary or wall-time conversion. The fixed CPU/wall price grid is descriptive and remains in the result JSON. Its largest wall-price scenario is highly sensitive to the observed long latency tail; it must not be used to claim a calibrated economic break-even point. [Evidence: `CONFIRMATION_PROTOCOL.json`, `CONFIRMATION_RESULT.json`.]

## Direct action-value diagnostics: important negative results

After the paired actual requests had finished, the driver evaluated all five alternatives at each of 1,404 candidate-visited H1 states. There are 7,020 alternative positions; 542 reuse the already executed selected endpoint. The other 6,478 positions execute and persist their registered transitions, which include actions retaining the current sample as well as decoder refinements. They should not all be described as new decoder samples. All alternative-generation failures are retained and their actual count is zero. Rejected or disabled alternatives remain in raw evidence, while regret uses only the exact feasible mask at that parent state. [Evidence: `online.py`, raw `counterfactuals.jsonl.gz`, `CONFIRMATION_RESULT.json`.]

| H1 diagnostic | Candidate | Teacher | Zero-difference baseline |
| --- | ---: | ---: | ---: |
| Action-minus-stop MSE, 959 executable comparisons | 0.0033805511 | 0.0047129409 | 0.0033098055 |
| Mean realized feasible moment regret, 1,404 nodes | 0.0032383964 | 0.0029457942 | — |

The candidate improves action-difference MSE relative to the teacher but does not improve on predicting zero difference. Its regret point estimate is worse than the teacher's. These are descriptive comparisons on candidate-visited H1 states; no confirmatory inferiority claim or global H2-oracle comparison follows. There were 54 states with a realized admitted improvement over an admitted stop. Such hindsight alternatives show realized opportunities in this sample, not the expected value of an attainable policy before the innovation is observed. [Evidence: `CONFIRMATION_RESULT.json`.]

Among 117 selected non-stop actions for which stop was also admitted, the realized action-minus-stop exponential moment averaged **+0.0092130944**. Positive moment difference is unfavorable. The mean prediction-minus-realization bias was **-0.0181586058**, with selected-difference MSE 0.0028011692. The selection bias therefore remains substantial despite the positive end-to-end primary contrast. [Evidence: `CONFIRMATION_RESULT.json`.]

## Calibration must include the future actually taken

| Correctness diagnostic | Masked teacher | Constrained paired candidate |
| --- | ---: | ---: |
| Final-decision ECE among delivered requests | 0.0138853311 | 0.0135974433 |
| Number in final-decision diagnostic | 1,489 | 1,518 |
| Initial-selected forecast versus full terminal outcome ECE | **0.2658792286** | **0.2768514689** |
| Number initially selected | 2,380 | 2,380 |
| Initially selected, subsequently rejected or failed | 891 | 862 |

The initial-selected diagnostic includes later rejection/failure as terminal strict failure. It reveals a major gap that the delivered-only final-decision ECE does not capture. The shared old correctness gate cannot be represented as a qualified forecast of the entire deployed continuation policy's terminal success. A low final-decision ECE does not repair this gap. [Evidence: the prospectively frozen secondary definition in `CONFIRMATION_PROTOCOL.json`; `CONFIRMATION_RESULT.json`.]

The candidate's H2 moment forecasts reflect future rejection substantially better than the teacher's in this sample:

| Initial-selected H2 moment diagnostic, n = 2,380 each | Masked teacher | Candidate |
| --- | ---: | ---: |
| Mean forecast | 0.2673737677 | 2.6348674219 |
| Mean realized moment, including future costs/rejections | 2.8750552116 | 2.7889332230 |
| Forecast minus realization bias | -2.6076814439 | -0.1540658010 |
| MSE | 17.7360653941 | 2.2927361436 |

The remaining candidate error is material. Its H2 training targets used out-of-fold H1 policies, whereas deployment uses the final full-fit H1 head. These residuals include that continuation-policy difference and source-generalization error. The large reduction is consistent with accounting for future rejection, but the combined intervention does not identify that mechanism's isolated effect. [Evidence: `model.py`, `CONFIRMATION_RESULT.json`.]

## What this closes, and what remains open

| Question | Evidence-supported status |
| --- | --- |
| Can this frozen combined controller improve net CE over the same-mask teacher on new writer sources? | Yes, the registered contrast passes with the adjusted cluster interval. |
| Does direct action-value learning reliably identify every worthwhile continuation? | Unresolved: zero-difference MSE, selected bias and feasible regret remain unfavorable. |
| Is the benefit caused specifically by constraint-aware backup? | Unresolved: backup, representation, paired target and affine head changed together. |
| Does it beat every strong fixed/allocation strategy? | Not newly tested in this confirmation; only the registered same-mask teacher is the primary comparator. |
| Does the quality gain coexist with lower measured online cost? | Yes in this run; timing estimates and the utility conversion remain descriptive. |
| Does this certify four-modal native lifecycle execution? | This five-action comparison contains no native owner execution and uses the old text/image generator. |
| Are all dynamic-model assumptions validated? | No. The separate 100-code path has an identified observation-law support error and a failed dynamic selected-ECE qualification. |

The finite Bellman implementation separately checks probability, horizon, stop, rejection and cost semantics on its declared models. It does not supply an unknown owner resource transition law. The 100-code external-audio kernel is exact for its declared stagewise continuation policy under its supplied tables; a generic globally optimal chance-constrained continuation requires a richer feasible-policy treatment. Those scope limits and a counterexample are retained in `KERNEL_VERIFICATION.json`. They must not be promoted to a general Merton-style optimum for an unconstrained all-modal language model. [Evidence: `bellman.py`, `dynamic.py`, `verify_kernel.py`, `KERNEL_VERIFICATION.json`.]

## Separate native and audio evidence

The independent native census audit covers the separate canonical 100-code path. It verifies all 320 ID rows and 1,200 all-input-missing rows, complete identity/route/policy sets, actual owner/output chains and zero request execution errors. The original collector exited 1 while serializing its final report; the complete rows were preserved, and the same frozen analysis was recovered with scalar serialization only. That failure and recovery remain explicit. The independent engineering audit passes without changing any original statistical gate. [Evidence: `review/NATIVE_QUALIFICATION_CENSUS.json`, `review/native_census_audit.py`, native raw `REPORT_RECOVERY.json`.]

The native dynamic policy failed its original selected-action ECE threshold: 0.0373542397 exceeds 0.03. `fixed_late` passed that threshold at 0.0295146364 and passed its other original numerical gates. Each policy rejected all 600 all-input-missing requests, but each had only one distinct numerical input, initial state and RNG state. The nominal one-sided 95% binomial bound 0.0049804434 assumes a corresponding IID-trial model; 600 metadata identities do not create 600 distinct missing-input configurations or certify natural OOD behavior. [Evidence: `review/NATIVE_QUALIFICATION_CENSUS.json`.]

The immutable source metadata also proves a structural error in the frozen audio pair likelihood. For 4/40 ID pairs and 11/170 confirmation pairs, equal digits use the identical WAV twice. A deterministic CNN must return equal observed labels for identical WAV bytes. The registered product law instead puts positive probability on unequal observations in every equal-digit target column: between 0.2387755102 and 0.4885714286 depending on the digit. This is a known support mismatch, not merely unverified correlation. The audit does not establish that it caused any particular qualification or efficacy result. The original candidate and all results remain intact; any repair needs a separate namespace, protocol and independent qualification. [Evidence: `review/EVIDENCE_ALIAS_AUDIT.json`, `review/EVIDENCE_ALIAS_AUDIT.md`.]

## Reproduction and custody

`CONFIRMATION_RESULT.json`, `CONFIRMATION_COMPLETION.json`, `CONFIRMATION_PROCESS.json` and `CONFIRMATION_ANALYSIS_PROCESS.json` are exact copies of the completed raw records. Their SHA-256 values and concise scientific status are recorded in `CONTROL_RESULT_METADATA.json`. The raw control directory retains development registrations, every ridge candidate and backup, actual old audio observations, the old-source smoke, every formal request/commitment, saved output bytes, subsequent counterfactuals, private scores, completion and process logs. The smoke's earlier exact `register_confirm.py` snapshot is retained separately from the final formal source. [Evidence: the named records and `RAW_ARCHIVE_INPUT_SPEC.json`.]

`RAW_ARCHIVE_INPUT_SPEC.json` is an input/custody specification, not a completed archive receipt. Root coordinates final packing, exact member verification and links to previously sealed upstream input archives. No raw upload, CI action, merge or production promotion is part of this control result.
