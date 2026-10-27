# Independent design review: six-arm field/neuron bridge

Scope: prospective experimental-design advice. This file is not execution evidence. The R45 source reviewed is the frozen `research_inputs/r45_main.tex` and `r45_recursive_detail.tex`; its scalar FBSDE identification remains separate from its finite-step optimizer/control implementation.

## Implementation-design update received from lead

The lead has selected a feasible bounded experiment: the original approximately one-million-parameter generator is frozen, with shared rank-four local low-rank adapters in image/text output modules; ordinary fixed-schedule adaptation and empirical field MPC share a training-only action-rollout bank. The field includes behavioral probes, effective operator displacement, and momentum summaries. Runtime control observes two public previews (raw and after a universal first `couple`) and chooses among stop/image/text/semantic/couple continuation actions. Native two-tick state and raw two-observation history receive the same information. Mean hard-output utility minus a declared refinement charge is primary; whole-cohort entropic CE is secondary. A common frozen reward observer defines the formal metric; a held-back audit observer checks robustness.

This choice avoids the previous conditional/global CE planning mismatch. It should be described as empirical finite-horizon field control, not as an implementation of an unverified scalar FBSDE or exact Riccati certificate. It studies local adapter training, not joint updating of every original encoder/transition/decoder parameter.

Specific checks for this implementation: initialize one low-rank factor randomly and the other at zero (both zero cannot learn); verify exact base-output parity and eventual changes to both factors; keep complete adapter/momentum state in rollout-bank clones; include both public previews and all native budget/timing inputs in the history comparator; charge the extra transition and final decode for non-stop decisions; preserve a truly held-out predictor audit at the trajectory level; add ordinary-adapted plus native control as an attribution supplement.

## 1. Primary question and attribution

The experiment must separately identify (a) adaptation, (b) a particular training controller, (c) a runtime state representation/controller, and (d) interaction between training and runtime control. A stronger full system alone cannot identify all four.

Recommended canonical six arms, subject to the already agreed user table:

| Arm | Model training | Runtime deployment |
|---|---|---|
| A | Original frozen model | Strong fixed policy selected on development data |
| B | Ordinary local adaptation | Same fixed policy class and selection budget |
| C | Field-guided local adaptation | Same fixed policy class and selection budget |
| D | Original frozen model | Actual native sparse_tick state controller |
| E | Field-guided local adaptation | Actual native sparse_tick state controller |
| F | Same field-trained checkpoint as E | Lightweight history controller with the same input events, action set, and tuning budget |

Required attribution supplement: B plus the runtime state controller. E versus D combines any adaptation with field guidance; E versus this supplement isolates field training under dynamic deployment. Ordinary adaptation plus history is useful if cheap. A model-independent fixed policy may be frozen globally; model-specific policy tuning is also legitimate if every arm receives the same class/data/budget. Declare which one was used.

## 2. One exact objective for training labels, planning, deployment, and reporting

Define externally observed episode return before outcomes:

`R = terminal_task_quality + sum(actual_intermediate_rewards) - sum(declared_real_action_costs)`.

The terminal quality must come from ground-truth digit/sequence/image outcomes, not a model's own confidence or hidden activation. Specify the weights/units and report each component alongside the scalar objective. Do not call squared intervention norms wall time or energy. Report measured computation separately unless it is explicitly priced in the objective.

For fixed risk coefficient rho > 0, use the deployment functional:

`CE_rho(pi) = -log(E[exp(-rho R_pi)])/rho`.

The finite test estimate is a numerically stable log-mean-exp of complete actual episode returns. Do not substitute the average of per-state conditional certainty equivalents. For rho = 0, use expected return.

The dynamically consistent finite-horizon backup for the same entropic objective is the exponentiated-return recursion:

`W_t(h) = min_a E[exp(-rho r_t) * W_(t+1)(h_next) | h,a]`,

with terminal `W_T = exp(-rho g_T)`. Hard deployment chooses the minimizing action with a fixed tie break. This is exact only under the declared transition/outcome law. Estimated laws require held-out calibration and policy-value error checks; enumerable true outcomes must not be made available to a non-oracle controller.

Candidate checkpoints and policy hyperparameters are finally scored using the same hard rollout objective. A differentiable proxy may generate proposals, but proxy gains are not deployed gains. A soft mixture policy is legitimate only if deployment samples that exact mixture and costs every sampled branch; it is not the same policy as argmax deployment.

## 3. Information, actions, and costs

At each decision boundary save the allowed input-event manifest, action, transition, observed outcome, costs, state hash, and model/policy hash. Only pre-boundary events enter runtime features. Unrevealed modality outputs, terminal labels, future admission decisions, and post-action cost realizations are excluded unless the action has already purchased/revealed them.

E and F receive exactly the same observation history and feasible actions. If sparse_tick uses an outcome, a budget field, confidence, a task identifier, or cumulative feedback, expose that raw input to F too. The fixed policy baseline can condition on publicly declared ex-ante task class if that is the intended fixed policy class; label it clearly.

Charge native state update, history update, planning, extra model queries, acquisition, generation, delivery, and adaptation candidate search separately. Cached counterfactual model outputs may accelerate offline evaluation, but their use must be masked and priced exactly as real deployment would require. Computation-only padding does not make a baseline stronger; provide equal optimization/tuning opportunities as well as a common resource cap.

## 4. Honest field-guided training

Declare a field H of the complete optimizer state before evaluating outcomes. Example: fixed text/image probe losses, function-space output summaries, per-group parameter displacement, and momentum/moment projections. Fit all normalizers and anchors on training/calibration data; keep them frozen. Include carried optimizer moments in saved candidate state. Do not silently reset them on candidate restoration.

Select a small fixed set of training interventions: ordinary update, lower learning rate, group mask, or replay fraction. Every adaptive comparator receives the same action set. Gradient directions can be generated normally; action selection is the control intervention.

A scientifically useful minimal controller fits next-field and exact hard-deployment-return predictions from training-only exploratory trajectories, freezes the prediction rule, and selects actions by a two-step lookahead using H. Its rollout labels use the exact objective from Section 2. A simple affine predictor is acceptable, with its residual/error measured; no Riccati or FBSDE claim follows merely from using two steps.

Useful supplements use (i) a generic equally sized summary and (ii) a richer optimizer/history state under the identical training actions/budget. Audit whether H changes selected actions, whether richer state predicts residuals, and whether field return prediction transfers to held-out trajectories. Comparing only to fixed SGD cannot separate a useful field from generic adaptive hyperparameter search.

Directly scoring every candidate checkpoint on labeled panels and choosing the best is an objective-aware candidate search. It is not evidence that a reduced field is sufficient unless the action-selection dependence on that field and its comparison to richer-state alternatives are explicit. If the implemented method uses a hand-written field heuristic, call it that and report its result without relabeling it as the paper's Riccati solver.

## 5. Splits and repeated measurements

Split underlying MNIST image IDs before constructing image pairs/episodes; otherwise many nominally distinct episodes share source images. Keep train, controller-calibration, policy-development, primary-test, and retention-test manifests disjoint at the claimed independent unit. If reuse of pretraining images is unavoidable, distinguish adaptation-unseen from pretraining-unseen.

Field construction and action-model fitting use only train/controller-calibration. Policy/hyperparameter selection uses only development. After freezing all choices and code identities, run primary test and retention once. Retention labels cannot both select a checkpoint and certify independent retention unless a separate retention-selection panel is declared.

Use paired episodes and paired stochastic marks across arms. Report each original model seed separately. Three pretrained/training seeds are three independent model units, regardless of episode count. Episode bootstrap intervals are conditional on those frozen models. For a cross-seed mean, show the seed-level paired differences and a clearly labeled very-wide small-n interval or descriptive range; do not claim population significance from thousands of correlated episodes.

For CE differences, recompute both log-mean-exps within each paired bootstrap replicate rather than averaging episodewise CEs. Cluster by all shared source-image IDs or by an explicitly independent episode construction. Also report mean return, task accuracy/quality, tail loss, action cost, and adaptation/deployment compute.

## 6. Acceptance criteria (freeze thresholds before test)

Execution integrity: every arm produces real model outputs; native sparse_tick is invoked in D/E; field/history arms use their recorded state, no label leakage; all declared arms, seeds, costs, and failures are retained.

Adaptation: B-A under fixed deployment, with independently measured retention.

Field training: C-B and E-(ordinary adaptation + state control), using the same adaptation action/search budget; positive paired effect with declared uncertainty and retention threshold.

Runtime state control: D-A and E-C under matched checkpoint, action space, outcome law, and total cost. A state change or changed action count alone is causal/execution evidence, not incremental value.

Neuron-specific value: E-F under same information/action/tuning budget, including state-update overhead. Equality or loss means no incremental neuron benefit established, even if both beat a fixed policy.

Interaction: [E-C]-[D-A], clearly conditioned on the actual choice of frozen/ordinary training in D. Report rather than infer synergy from E being numerically best.

Robustness: preserve adverse seeds and action regimes; measure low-effort/high-effort and tail-risk regimes without retuning outcomes. Do not manufacture risk sensitivity from objectives for which every action has identical risk/return structure.

Scope: a successful MNIST-pair bridge establishes that specific multimodal controlled system. It does not identify scalar shared Brownian drivers, full nonlinear HJB hypotheses, LLM-scale training gains, or production promotion.

## 7. Concrete review blockers to check in code

1. Conditional-CE/global-CE mismatch or reward normalization depending on the evaluated arm.
2. Soft policy during selection and argmax at deployment.
3. Hidden state or future labels in controller features, including cached unrevealed outputs.
4. Shared source images across train/dev/test despite unique pair IDs.
5. Carrying model tensors but dropping optimizer moments when restoring candidate states.
6. Claiming field guidance when field values never affect an action.
7. Comparing field search to ordinary training while ignoring extra candidate compute and label queries.
8. Calling generated decoder likelihood an independently observed external reward without reporting actual decoded quality.
9. Adaptive use of the primary test/retention panel.
10. Counting paths/rows as independent trained models or conflating a one-future-path interval with expected-value inference.
