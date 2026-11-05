# Encoder-initialized, budgeted multimodal generation: review contract

Status: proposed implementation and acceptance contract, prepared during source review.
This document records no new training, performance, native execution, or deployment result.
It specializes NDU to a finite-horizon entropic objective; it does not implement general endogenous-preference NDU/FBSDE.

## 1. Existing implementation boundaries

The following are historical claims in the inspected repository files, not reruns in this review.
The delivery manifest must pin the exact source SHA of those files and of every new experiment.

| Existing source | Established scope in its own documentation | Boundary to preserve |
| --- | --- | --- |
| `experiments/multimodal_output_portfolio/v6/README.md` | Real MNIST source images plus public text; neural PNG and autoregressive caption output; frozen model/forecast identities | Constructed digit-pair benchmark, not natural full-modality generation |
| V6 `neural.py`, `control.py`, `distribution.py` | Two training profiles, real latent transitions, finite deterministic lookahead, conditional terminal forecast | Work units are declared operation tariffs; finite residual scenarios do not certify conditional risk |
| V6 documented full-002 | Improved bounded joint generation; no established dynamic-inference advantage over strong controls after costs | Previously observed results cannot become fresh confirmation by replaying or renaming them |
| V6 native adapter and owner sections | Post-hoc Rust receipt, actual feature execution, explicit calibration rejection and engineering record replay | Receipt is not online NDU control; rejected Neuron admission is not production qualification |
| `joint_hepta_20261029/v3/README.md` and `RESULTS.zh-CN.md` | Historical 13,056 final trajectories; same-model encoder-only beats dynamic at 6/6 endpoints | No stable positive effect; finite synthetic media; arbitrary output-modality selection was not learned |
| V3 `critic_calibration.py` | Source-disjoint proper exponential-moment fitting with actor/content hashes frozen | Aggregate calibration is not statewise calibration or policy improvement |
| V3 `native_generation/INTEGRATION.md` | Complete small-model Rust inference, immutable research prefixes and new-process recovery | Existing Agentd owner adoption, natural audio/video and learned streaming consistency remain open |

V6 and V3 are different experiment families; their numbering does not define one linear upgrade history.
V6's `future` is a held-out MNIST source split, not a collection of chronologically future observations.
The current V6 four slots explicitly leave audio/video unsupported; schema bits do not establish decoder capability.
V6's documented training axis changes both the base risk surrogate and plan-gate objective; that axis does not separate these contributions.
V3's parent pin is `7db3b8347080326ded0cba037fc770df76c94a6a`; its original native-owner inspection pin is separately documented.

## 2. Model and information boundary

Merton motivates dynamic allocation under preferences and constraints; its closed-form portfolio assumptions do not transfer to this generator [1].
The implementable formulation is budgeted metareasoning plus output generation, with an explicit stopping option [2].
Define the visible filtration `F_t` from actual inputs, paid observations, public metadata and measured execution history.
Targets, corruption labels, future noise and audit-observer labels are outside `F_t`.

`z_0 = Encoder_theta(text, image, observed_mask, source_identity, time_metadata)`.
Use text+image first; reserve typed audio/video slots and a presentation-clock adapter without filling unsupported slots with fake values.
The sufficient state is the full visible history or a justified information state; a compact neural vector is only a learned approximation.

| State component | Required information |
| --- | --- |
| Content | Shared latent, each modality latent, recurrent state, decoder/sampler state and candidate versions |
| Belief | Posterior or calibrated forecast of uncertain task facts, candidate validity and future action effects |
| Evidence | Observation IDs, source hashes, acquired segments, validity/unknown flags and verification results |
| Budget | Remaining CPU/GPU work, money, memory limits, deadline and terminal-output reserve |
| Residency | Loaded weights, KV/features, cached candidates, eviction state, reusable prefix and recomputation requirement |
| Pending work | In-flight actions, completion events, retries, cancellation and recovery phase |
| Delivery | Immutable committed-prefix frontier, uncommitted deltas, required modality set and synchronization obligations |
| Identity | Encoder, generator, controller, forecast, calibration, objective, cost, schema and owner-generation digests |

With partially observed accumulated costs, a plain posterior over task labels may be insufficient; include the required joint information state [4].
For the first prototype, make incurred costs observable and preserve all hidden-world uncertainty needed by the terminal predictor.

## 3. Actions and terminal semantics

| Action | Exact effect |
| --- | --- |
| `READ(source, segment)` | Acquire an observation that was previously unavailable; bill acquisition and encoding |
| `WAIT(event, duration)` | Advance time or receive pending work; no invented information on repeated waits |
| `REPAIR(candidate, operation)` | Execute a real candidate modification with a new version |
| `GENERATE(modality, quantum)` | Execute a declared content-update quantum |
| `SUBMIT(bundle)` | Deliver an existing feasible bundle with the precise required modality set |
| `STOP` | Apply the declared terminal rule: deliver the initial/current valid bundle or explicit abstention |

Reject unavailable modalities, invalid inputs and impossible hard budgets before initiating paid work.
An abstention may be the safest terminal action but is not successful completion of a mandatory text+image request.
Measure actual modality budget shares after execution; do not equate a softmax allocation weight with memory, time and money shares simultaneously.
STOP is legal at the initial encoded state, including before any refinement.
Terminal actions stay legal through a reserved envelope sufficient for decoding, persistence and the declared output operation.

## 4. Entropic terminal value and continuation-only learning

Fix risk aversion `gamma > 0`, a bounded outcome reward `G(y, world)`, a cost profile and a finite horizon before fitting.
`G` scores delivered artifacts, factual errors, contract violations and synchronization under a frozen evaluator.
Do not learn the reward scale or use the audit evaluator as an online observation.

`R = G(delivered_bundle, world) - sum(actual_in_scope_costs)`.
`CE_gamma(R | F_t) = -log E[exp(-gamma R) | F_t] / gamma` [3].
The optimization target is this declared criterion within the feasible finite model; an implemented learned policy need not attain its maximum.

For each terminal action, compute its fixed rule from current public evidence:
`M_T(s, a) = E[exp(-gamma * (G_a - C_terminal)) | F_t]`.
`g_gamma(s, a) = -log(M_T(s, a)) / gamma`.
`g_best(s) = max_{feasible terminal a} g_gamma(s, a)`.

Known terminal semantics do not mean known hidden-label correctness: terminal quality still depends on a separately fitted belief/forecast.
If reward is fully observable and deterministic, `g_gamma` reduces to that reward minus terminal cost.
Do not introduce a freely trained STOP/SUBMIT Q head that can override this rule.
Only learn continuation values whose outcome or value is uncertain; compute deterministic known branches directly.

For a frozen suffix policy `pi`, define the conditional exponential moment:
`M^pi(s, a) = E[exp(-gamma * R_suffix) | s, a, pi]`.
Represent `ell_theta(s, a) = log M^pi(s, a)` and `Q_gamma^pi = -ell_theta / gamma`.
A proper moment loss is `exp(ell) - exp(-gamma * R_suffix) * ell`, with source-uniform weighting.
The population minimizer satisfies `exp(ell) = E[exp(-gamma * R_suffix) | features, action]`.
This is a moment objective, not squared-error regression to individual sample returns.
It gives a value conditional on the supplied features; aliasing may remain when features omit relevant state.

For known deterministic next-action cost `c`, the Bellman moment is `M(s,a) = exp(gamma*c) * E[M(S') | s,a]`.
For random correlated costs, retain `E[exp(gamma*C) * M(S') | s,a]`; subtracting `E[C]` outside CE is generally wrong.
Use the same gamma and a sufficient state throughout; arbitrary mean-variance or CVaR substitutions do not inherit this recursion.
Report `A_gamma(s,a) = Q_gamma(s,a) - g_best(s)` and prefer STOP on ties.
This is `CE(action) - CE(STOP)`, never `CE(action_return - stop_return)`.
Distinguish `Q^pi` from `Q*`; repeated replanning requires new policy evaluation or fresh on-policy evidence.
Use stable log-sum-exp, a declared risk-neutral limit, and explicit nonfinite rejection; silent clipping changes the objective.

The initial additive continuation patch may fit a simpler paired moment-improvement head:
`D_gamma(s,a) = E[exp(-gamma*R_STOP) - exp(-gamma*R_action_fixed_suffix) | F_t]`.
For `gamma > 0`, its positive sign and action ordering match improvement over the common STOP CE, but its magnitude is not a CE difference.
For `gamma = 0`, use `E[R_action_fixed_suffix - R_STOP | F_t]` explicitly; substituting zero into the exponential difference gives no signal.
Finite paired rollout labels are noisy samples; linear regression approximates their conditional expectation, not exact statewise Q.
Bind gamma, target kind, fixed suffix, feature order and every cost component into the checkpoint identity.
Its support box is a conservative operational check, not statistical conditional coverage or proof that feature aliasing is absent.
The std-only Rust comparison covers this exported standardization and four-output linear map only; STOP is fixed at zero.
It does not qualify the complete Encoder/decoder, terminal forecast, production owner or on-device lifecycle.

## 5. Information value and causal diagnostics

READ/verification can improve selection or enable abstention without changing content bytes.
REPAIR/generation changes the candidate set or content, so its benefit is not merely information value.
From each frozen visible prefix, execute paired STOP, one content update, one observation and action-plus-suffix branches.
Use identical allowable information, budgets and coupled future noise, while keeping each executed branch's real cost.
Separate content improvement, information improvement, action-selection improvement and their combined net effect.
For the entropic profile, compute paired differences between conditional CEs; do not transplant a risk-neutral VOI formula unmodified.
Repeated READ with unchanged evidence must not be counted as fresh information or an independent evaluation sample.

## 6. Cost and resource contract

Record raw measurements separately from the utility tariff; model-operation units are not FLOPs, joules or monetary prices.
Bill observations, encoding, controller inference, hypothetical candidate work, execution, decoding and validation exactly once.
Also bill cold starts, candidate bytes-times-residence, cache eviction, recomputation, reuse lookup and cross-modality coordination.
Include actual failure, retry, cancellation and restore paths; bind every charge to a semantic operation ID.
Peak memory is a hard constraint; bytes-times-residence is a distinct occupancy cost.
Parallel wall latency is the observed critical path; CPU/GPU service times accumulate across workers.
Unavailable energy or GPU measurements remain `unmeasured`, not zero.
Keep online cost, offline training/calibration/search cost and deployment-count amortization separately visible.
Historical incurred cost remains in episode accounting; action comparison uses future incremental costs without deducting the past twice.
If a searched successor is reused, verify its exact state/model/input identity and charge retention/reuse; otherwise charge execution again.
Export both physical-resource feasibility and abstract-tariff utility, so a convenient tariff cannot conceal actual overruns.

## 7. Baselines and oracle separation

| Arm | Information and computation contract |
| --- | --- |
| Encoder-only | Same encoder and initial outputs; no later content transitions; decode/validation costs retained |
| Static quota | Validation-selected modality allocation, including zero continuation where legal |
| Fixed steps | Strong validation-selected action sequence/prefix; same executor and resource ceilings |
| Lightweight control | Public-state threshold, linear advantage or small router; bill its inference |
| Exact finite DP | Exhaust the declared finite belief/state/action model with the same visible information |
| Dynamic learned policy | Same input, executor, budgets and permitted observations; explicit fallback |
| Clairvoyant oracle | May inspect hidden labels or realized future outcomes; diagnostic upper bound only |

DP is exact only for its enumerated transition/forecast model; compressed-state or residual-model error remains.
An incomplete tree is `truncated`, not exact DP; V6's deterministic lookahead is not a general stochastic DP certificate.
If DP is given the true environment law unavailable to learned policies, report that model-information advantage separately.
Count DP planning/table storage and query costs, with an explicit offline amortization convention if applicable.
Neither oracle outputs nor test-set outcomes may choose a deployment action, hyperparameter or promotion threshold.
An oracle's positive opportunity does not establish that an affordable causal policy can realize it.

## 8. Training/execution factorial and calibration

| Training / execution | Fixed execution | Dynamic execution |
| --- | --- | --- |
| Fixed-policy training | `J_FF` | `J_FD` |
| Dynamic-policy training | `J_DF` | `J_DD` |

Report execution effects `J_FD-J_FF` and `J_DD-J_DF`, training effect `J_DF-J_FF`, and interaction `J_DD-J_DF-J_FD+J_FF`.
Rows require independent training with matched data, initialization schedule, update and wall-time budgets.
One checkpoint with its controller disabled is execution ablation only.
Freeze the common encoder first; test encoder changes as a separate factor before assigning gains to NDU or an analytic core.
If base-generator training and policy training change together, label their combined effect rather than claiming identification of each.
Calibrate belief probabilities with Brier/NLL and reliability plots; temperature scaling is a baseline, not an OOD guarantee [5,6].
Calibrate continuation moments/advantages by visited state-action strata, selected-action error, false-positive continuation and realized net return.
Population calibration does not imply conditional calibration; include budget edges, missing/conflicting modalities and rare costly failures.
Measure coverage under the final deployed policy, not only under random-state or initial-state sampling.
Keep unknown-input false acceptance separate from normal-input false rejection; malformed-input tests do not establish semantic OOD detection.

## 9. New data, promotion and recovery

Freeze source/checkpoint/configuration, training/calibration/dev/confirmation partitions and selection rules before opening confirmation data.
Partition by original source identity and derived pixel/content identity; correlated views and repeated rollouts stay in one cluster.
New seeds are unseen-seed evidence; new independent generators/worlds are distinct evidence; real future observations require post-freeze collection.
Do not label a held-out historical MNIST split as temporal validation, or a historical replay as a new scientific sample.
For the entropic objective, recompute candidate CE and baseline CE within every paired source-cluster bootstrap resample.
Report their difference, uncertainty across training seeds, weighting convention and any multiplicity adjustment.
Finite-source bootstrap intervals are empirical diagnostics, not guarantees under arbitrary future distribution shift.
Promotion requires a preregistered positive lower bound versus the strongest chosen baseline and all feasibility/risk/quality/recovery gates.
Otherwise retain the previous active manifest/fixed policy as `no-update`; save the rejected candidate and evidence without activation.
Low-support state-action fallback can follow baseline-bootstrap principles [7], but no external theorem is claimed without its assumptions.
An invalid baseline output must still abstain/reject; preserving a baseline never overrides hard output requirements.
Version model, policy, forecast, cost and calibration together; restore the same manifest, RNG, pending work, ledger and output frontier.
Torch/Rust equivalence must cover real forward state and actions, terminal values, bytes/semantic decode, invalid inputs and fresh-process restore.
A production writer must atomically commit generation state and output progress; two independent durable owners are not an integration shortcut.
Already committed/delivered prefixes cannot be erased by a model rollback; reconcile outbox acknowledgments before new actions.

## Primary sources actually read

[1] Merton (1971), original paper PDF and MIT working-paper record: https://www.sfu.ca/~kkasa/Merton_71.pdf ; https://dspace.mit.edu/entities/publication/45b93de3-551e-475d-9d42-4724ecd84484
[2] Hay et al. (2012), original paper, especially definitions 2-3 and stopping/budget formulation: https://people.eecs.berkeley.edu/~russell/papers/uai12-meta.pdf ; https://proceedings.mlr.press/r10/hay12a.html
[3] Howard and Matheson (1972), publisher abstract read (not full paper): https://pubsonline.informs.org/doi/10.1287/mnsc.18.7.356
[4] Baeuerle and Rieder (2017), authors' abstract read, including required extended information state: https://arxiv.org/abs/1504.03530
[5] Guo et al. (2017), original proceedings abstract: https://proceedings.mlr.press/v70/guo17a.html
[6] Ovadia et al. (2019), original proceedings abstract on dataset-shift limitations: https://papers.neurips.cc/paper_files/paper/2019/hash/8558cb408c1d76621371888657d2eb1d-Abstract.html
[7] Laroche et al. (2019), original proceedings abstract on baseline bootstrapping: https://proceedings.mlr.press/v97/laroche19a.html

Equations and acceptance requirements above are this review's explicit proposed contract; these sources do not certify the Hepta implementation.
