# Weight-space programming: current research decision

## Overall decision

Continue bounded, evidence-producing weight-space research. Do not replace
training or admit a production candidate on the current evidence. The native
execution/recovery and arithmetic layers have useful qualified components;
the primary task-value result for direct weight editing is still negative.

The original MIT source is a November 2, 2026 research report with released
experiment artifacts, not a confirmed archival paper. Its GPT-6 Astra Qwen
intervention is relevant to a localized repetition failure. It is not evidence
that an agent identifies arbitrary neural circuits from raw numbers or finds a
global neural optimum. See `literature/RESEARCH_REFRESH_20261105.md` for pinned
primary references, exact update, budgets and newer November 4 follow-ups.

## 1. What the new diagnosis actually establishes

Newer Hepta drafts #4830 through #4833 add exact online references, four-arm
attribution, pinned pretrained backends and a real multimodal execution canary.
Here real dual means text plus image generation, not financial Call/Put heads.
The exact-head #4833 execution succeeds, but its retained semantic inspection
is negative and independent semantic acceptance remains open. Those records are
reviewed in `literature/LATEST_HEPTA_RESEARCH_SCOPE.md`; no new image evaluation
is claimed here. The five checkpoints below do not represent all current Hepta
research, and this limited check cannot establish what is absent elsewhere.

The new event study is in `../wsp_event_semantics_20261105/`. It uses five
existing research checkpoints and 320 existing TRAIN initial public states,
without new labels, weight edits or efficacy samples. The full independent
review is `independent_semantic_review_r3/REVIEW.md`; failed reviewer attempts
are preserved separately and do not constitute successful replications.

| Requested component | Actual finding | Consequence for a possible edit |
| --- | --- | --- |
| State representation | Research input is 43 public + 33 mass + 9 endpoint-bank coordinates, followed by 48 tanh features. Pocket4 is a different 321.9M-parameter encoder model. | Bind the actual encoder, action decoder and target before naming a weight. No production-to-research semantic equivalence has been proved. |
| First-Passage / Reset | All 2,880 tested endpoint conditions differ from strict first-hit probabilities. The generator already has boundary-to-interior reset rates. REPAIR repairs the sensor and its READ legality; it does not command a latent-process reset. | A first-hit channel is a new target-dependent representation, not an automatic correction of a fixed-deadline sign task. Preserve initial-hit and renewal history conventions. |
| Call / Put | The research terminal decoder shares one belief, not two independent financial-value heads. Finite-grid equality mass is nonzero; two-sided first-exit also has a survival event. | Specify endpoint payoffs or competing first events before enforcing parity. Strict greater and strict less do not exhaust a distribution with atoms. |
| Belief | Same-tick REPAIR leaves mass/bank equal, but public features and the learned belief change in all 320 controls. | Do not infer full-network invariance from one unchanged latent subvector. Test calibration and task value independently. |
| Continuation Q | A terminal-anchored, occupancy-weighted direct head fit failed its IID/OOD efficacy gate. A retained post-hoc state shows the edit changing a valuable READ into WAIT. | Diagnose the action margin and reachable-state coverage. Lower quadratic loss is insufficient; useful partial edits remain possible. |
| NDU control | Complete own-law finite Bellman planning improves synthetic utility more than the learned-head edits. | This isolates a modeled planning opportunity; it does not establish a global optimum under unknown market dynamics or net compute costs. |

For horizon six and threshold zero, mean endpoint probability is 0.4950646459
and strict first-hit probability is 0.8880236537. First hit includes time zero;
the initial hit mass at threshold zero is 0.5. The difference is not solely a
reset effect. Mean equality mass is 0.0410237708, so `P(>0)+P(<0)` is below one.
The lower-first, upper-first and neither probabilities are 0.2902845008,
0.3107928399 and 0.3989226593 respectively. These are event identities on the
stored finite-state law, not improvements in forecasting accuracy.

All 320 same-tick WAIT/REPAIR controls have identical mass and bank; all 320
also change public features, Q, belief and future READ legality. Changes in
these outputs were counted, not graded for direction, calibration or benefit.
Independent transient-submatrix, flow-integral and fixed ODE checks agree
within 1.315e-13. This is numerical cross-checking, not outward-rounded
certification of continuous diffusion first passage.

## 2. Direct editing versus gradient fitting

The completed terminal-anchored experiment and all retained raw outcomes live
in `../wsp_native_value_20261105/value_edit/`. These are prior frozen results,
not new efficacy runs performed by this diagnostic package.

The incumbent C has 147 editable continuation coefficients and 49 protected
belief coefficients. E solves a fixed-feature trust-region quadratic directly;
G uses matched projected gradients with the same data, target, radius and
finite alpha path. The target is

    Y_a(s) = T_pred(s) + Q_C(s,a) - T_own(s).

It aligns one-step incumbent advantages with the unchanged terminal decoder.
The state weights mix 90% incumbent occupancy with 10% uniform legal support.
Candidate alpha is selected from 0, .25, .5, .75 and 1 using complete TRAIN
own-law value, including exact no edit. This is supervised parameter fitting
without backpropagation, not a reproduction of MIT's reported Qwen discovery
procedure; it is not complete neural retraining.

| Frozen arm | Raw IID utility | Raw OOD utility |
| --- | ---: | ---: |
| C: unchanged incumbent | 0.2265222410 | 0.1275367079 |
| E: direct anchored occupancy fit | 0.2490640804 | 0.1253259548 |
| G: matched gradient fit | 0.2491925890 | 0.1253259548 |
| EU: remove occupancy weighting | 0.2265222410 | 0.1275367079 |
| EA: remove terminal anchoring | 0.2392931169 | 0.1282890385 |
| M: earlier full-optimal-Q MSE fit | 0.1992900979 | 0.0883703817 |
| R: matched-norm random edit | 0.1551832559 | 0.0801422551 |
| P: analytic posterior program, no edit | 0.2280377088 | 0.1419144077 |
| J: full own-law Bellman program, no edit | 0.3654721430 | 0.3128199855 |

Only fit23 E/G passes validation. After the frozen gate, E-C is +0.0048376514
IID, interval [-0.0120719041, 0.0217472070], and -0.0024837919 OOD, interval
[-0.0111656527, 0.0061980689]. Both predeclared lower bounds must exceed .005;
both fail. The intervals use five existing fit means, df=4, and correction for
the two primary comparisons. Extra worlds do not increase the number of
independent trained models. Eight rejected artifacts restore byte-for-byte;
two accepted artifacts stay isolated research outputs. No production cutover
or new Hepta A/B/C/D D-minus-B interaction is established.

E's solver takes 0.216800 CPU seconds versus G's 4.370660. Including the common
feature/teacher work, candidate path and serialization, measured candidate
construction is 167.378052 versus 173.693328 seconds, a ratio of 1.037731.
The complete scientific child takes 535.948697 CPU seconds; independent replay
takes 332.887897. Recorded preparation, runs, verification and reporting sum to
875.455436 measured child CPU seconds. Nested costs must not be added twice.
Unknown editor, acquisition, old training and energy costs stay unknown.
There is no demonstrated equal-useful-quality speedup over full training.

## 3. Native Rust subsystem: qualified parts and missing parts

HeptaRuntime #92, #93 and #94 already form a concrete draft stack. This package
independently reviewed their current identities and the exact #94 build/CI and
certificate records; it did not invent a new Rust patch where no violation was
found. See `runtime_audit/AUDIT_REPORT.md` for complete scope and evidence.

The exact #94 head is `bc38fb82244b946907886704b3c677bf00761cb9`. Official run
[41966037157](https://github.com/TrillionniumFoundation/hepta-runtime/actions/runs/41966037157)
passes 1,816 tests with 41 skipped under all features and 1,796 with 29 skipped
under no default features. The prospective-merge job is skipped; the PR remains
draft. A fresh readback matches all 270 relevant source files and the retained
binary; an independent arithmetic review checks 21,458 witness rows, 735 center
binary64 encodings and 21 RPC controls. Software correctness is not efficacy.

| Stage | Existing native capability | Remaining contract |
| --- | --- | --- |
| Identify | Content-bound artifact/profile/tensor inspection | Verified production encoder and semantic tensor map |
| Reproduce | Bounded tensor and linear forward execution | Full architecture/dtype/source execution binding |
| Diagnose | Input evidence and bounded mathematical controls | Causal circuit localization; preserve parameter symmetries |
| Reject infeasible targets | Exact continuation certificate | Source-authenticated or reexecuted features/teacher |
| Plan | Ridge/trust-region and finite Bellman planners | Conditional optimization, including no edit and complete costs |
| Edit | Expected-byte/mask/norm checks and separate artifacts | Model-specific admissible transformations and representation changes |
| Validate | Guarded validation and immutable records | Fresh sealed task-value and retained-capability evaluation |
| Recover | Durable intent, rejection restore and matching-request recovery | Qualified unattended recovery, power-loss tests and live pointer cutover |

The certificate proves a bounded fact. With center C, radius R, ordering rows A
and nonnegative witness y, let v=A^T y and d=-v^T C. If d>0 and
`d^2 > R^2 * ||v||^2`, the original ball cannot satisfy all supplied necessary
orderings. Rust checks exact finite binary64 encodings with integers and treats
the F64 rounding relaxation separately. All five frozen fits are infeasible for
that full-copy target. This does not rule out a useful partial edit, larger
radius, changed representation, new task or another planner.

Bellman optimality applies to a supplied finite risk-neutral additive DAG, not
the full neural parameter space or arbitrary NDU/FBSDE objectives. Hashes bind
content but do not authenticate a teacher's law. A recovering artifact journal
does not imply a deployed background repair daemon. Process-kill recovery has
evidence; power-loss recovery and distributed live activation remain open.

A production patch intent should bind schema, target event, inequality,
initial-hit convention, endogenous/action reset semantics, time index,
checkpoint, tensor map, source program and a target-contract digest. Agent
interpretations remain hypotheses until controlled interventions distinguish
them. Exact-byte rollback and a retained no-edit candidate are mandatory
outcomes of the workflow, including when all candidates fail.

## 4. MIT replication status and the next valid experiment

The retained predecessor evidence includes 768 MinAtar episodes, exact
published Qwen edit reconstruction/loading, and 36 short CPU/F32 forwards
checking 18 cached/full-prefix pairs. It does not reproduce the complete
MATH-500/GSM8K/IFEval generation and grading protocol, native BF16/vLLM behavior
or a fresh Astra discovery. The full original agent/forward-server harness is
not released. No new full MIT benchmark was run in this package.

A future complete comparison needs two separate levels: published-edit replay
and blinded independent discovery. The replay should cross edited/unedited
weights with original/strong zero-edit generation configurations, preserving
all outputs, errors, grading and prompt/tokenizer/dtype identities. Discovery
must not expose the published layer, direction, column and scale solution.
Count editor inference, failed requests, batching, target tokens, activations,
search, evaluation, serialization and recovery; a nominal request is not one
example or a complete cost measure.

For Hepta, the next efficacy protocol should be frozen before any new holdout
is opened. Include no edit, code/semantic correction, a same-information analytic
solver, an agent-guided edit, matched random/sham edits, matched head-gradient
fitting and an affordable full-training baseline. Preserve the ordinary versus
analytic-core and light versus value-control factorial where that is the stated
Hepta claim. Report D-B and its interaction separately from prediction loss.

First define the actual first-passage/reset and Call/Put task contract. If the
task remains fixed-deadline sign, endpoint banks are semantically appropriate;
an alternative first-hit representation is an ablation. If the target becomes
path-dependent, add survivor/event/reset history to the sufficient state and
independently verify its filter before optimizing weights. New exposed samples
cannot be recycled as a fresh final test. Source freshness and original
admission must recover for any prospective Trader evaluation.

The present result is a concrete engineering advance plus a sharper negative
scientific diagnosis. It supports avoiding one proved-infeasible fitting
objective and distinguishing semantic changes from parameter repair. It does
not justify claiming that gradient training is obsolete or that model quality
has improved.
