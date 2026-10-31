# Independent review of full joint learning and deployment

## Assessment

The separately registered full-joint objective is the complete finite-law
expectation of the actual `hard_soft` execution policy. Its internal transition,
action sampling, public successors and current/future event fees use the same
ordering. The saved model restores the intended Brownian kernel rather than
silently interpreting its weights as the older R7 OU/CTMC cell.

All declared inactive parameters remain frozen in all 20 fits. The limited,
predeclared independent replay of 64 new-heldout trajectories passed exactly for
scores, actions, latent states, external transitions and total utility. This is
an implementation and deployment-consistency finding, not evidence of predictive
superiority, a calibrated value function, or native qualification.

The original primary experiment and its freeze were not changed. The new
experiment remains explicitly post-primary; the registration and new candidate
freeze occurred before its new heldout evaluation.

## Identity and scope

- Published candidate commit: `f53e4891b0a66f831c32b6b989367c73f715a62a`.
- Candidate-manifest SHA256: `b7d55711a1c5bcfb025bafbe8379b7a90515eb6bedf6528ab541de018abb91c1`.
- Registration SHA256: `606530930a5033a84e1af7c7cd0cf22b3d6d92f7ac35a6a51d66812dd2fddb7e`.
- Original Round8 freeze SHA256 remains
  `f4edffc4451697fd543bdf0e10dc7242297c13f38f8c96d21bc8d7c68355988e`.

The remote candidate identity above was supplied after publication by the
coordinator. The independent review verifies its local candidate manifest,
registered source hashes, all 40 initial/final model hashes, all 20 training
report hashes, and the original frozen dependency inventory. It does not claim
a second independent GitHub publication operation.

The 600-step gradient/optimizer replay is reviewed separately. This check did
not recompute those gradients or perform additional training.

## Objective versus actual process

Let `s` be a public state, `z` the internal state before the incoming transition,
and `z'` the sampled successor. Let `T` denote the nonnegative row-normalized
kernel, and let `pi` be the legal-action softmax of head-one scores at temperature
0.12. The registered recursion has the form

\[
V_\theta(s,z)=
-c_e\sum_{z'}T_\theta(z'\mid s,z)\,I_{\mathrm{new\ event}}(z,z')
+\sum_{z'}T_\theta(z'\mid s,z)
\sum_a\pi_\theta(a\mid s,z')
\left[r(s,a)-c_d+\sum_{s'}P(s'\mid s,a)V_\theta(s',z')\right].
\]

Here `c_d=0.0005` and `c_e=0.0002`; task action/latency costs are already in
`r`. Terminal continuation is zero. The current event is charged once on the
incoming transition, including when the sampled action is STOP. Every action
incurs one decision fee. Reset, refractory persistence/release, later cell
events, later sampled actions and all legal external successor branches remain
inside the continuation.

`full_joint.evaluate` differentiates the normalized kernel itself, rather than
a separate unnormalized training law. Event expectations are recomputed from
that normalized active-to-refractory mass. This matches `Policy(hard_soft)` from
a one-hot predecessor: normalize the successor probabilities, sample the next
internal state, and count the corresponding realized transition event.

The action distribution is then sampled with a distinct keyed `action` uniform.
The internal transition uses the keyed `latent` uniform. Both use the same
decision counter and registered seed; the counter advances once per decision.
The head receives the realized internal state. It does not receive an averaged
latent state in place of that sample.

The recurrence contains no detached critic target, myopic auxiliary loss,
straight-through estimator, or replacement of expected loss by loss at a mean.
The outputs are policy scores optimized through return. The legacy prediction
field name `q` does not turn them into calibrated Q-star or Q-pi estimates.
Greedy-policy conversion remains a separate evaluation, not the trained
soft-policy objective.

## Loading and inactive parameters

`load_joint` verifies schema `hepta.full-joint-policy.v1` and the mode-specific
kernel version, constructs `BrownianEventDynamics` for every non-direct family,
loads the complete state dictionary, rejects nonfinite parameters, restores
training masks, and uses head one. The registered N=15, temperature=0.12 and
leak-zero non-direct law are preserved.

All 40 checkpoints were checked against their serialized tensors. The parameter
round-trip is exact. All 20 fits satisfy:

| Family | Frozen quantities verified unchanged |
| --- | --- |
| Direct | Every core parameter and both drive tensors |
| Projected continuous | Raw leak, both reset parameters and recovery parameter |
| Clocked | Raw leak |
| First passage | Raw leak |

For the continuous cell, reset/recovery are unreachable under the declared
no-event law. Freezing them avoids counting irrelevant parameter movement as
physical learning. Its boundary parameter still changes the voltage projection
and readout scale; that role is explicitly different from a firing threshold.

The first four output rows of `readout.2.weight` and `readout.2.bias` also retain
their original bytes in every fit. This statement concerns **head-zero output
parameters only**. The shared hidden readout changes during learning, so the
actual head-zero forward scores can change. They are not trained or evaluated
as a second calibrated controller.

The old Rust loader has an explicit schema match in `native/model.rs`: it accepts
the original schema-free R7 model or `round8-fixed-cell-calibrator-v1` and rejects
other schemas as unsupported. Consequently, the new full-joint schema is not
silently accepted under the old R7 semantics. This was checked in source; no
new native performance or recovery qualification is inferred.

## Limited independent trajectory replay

The subset was declared before reading its outcomes: fit seed 11, all four
families, both initial/final stages, and the first eight recorded new-heldout
worlds. This covers the four new configurations twice for each family/stage,
for **64 trajectories**. Only already recorded worlds were reconstructed.

The independent implementation reconstructs both SHA uniforms, categorical
inverse CDFs, normalized transition rows, legal-action softmax, and public
environment steps. It compares these with the saved trajectories without using
`Policy.act` to produce its decisions.

| Check | Result |
| --- | ---: |
| Trajectories replayed | 64 |
| Internal and action sampling steps | 210 |
| Maximum restored-score discrepancy | 0 |
| Maximum total-utility discrepancy | 0 |
| Maximum row-mass defect before normalization | `5.55e-16` |
| Expected-event discrepancy due to normalization roundoff | `4.44e-16` |
| Minimum random draw distance from a categorical CDF boundary | `1.22e-4` |
| Sampled event followed by STOP, with fee correctly retained | 14 |

The replay observed 39 active-to-refractory transitions, 23
refractory-to-active releases, and four refractory persistence transitions,
alongside ordinary active propagation. Thus the checked paths include actual
events, release/reset continuation and event charges on STOP, rather than only
no-event trajectories.

The parameters, candidate manifest, registration sources and original freeze
were verified again afterwards. No candidate, source input, hyperparameter,
selected stage or primary endpoint changed during this review.

## Receipts and limits

- Source: `posthoc/full_joint_deployment_review.py`.
- Machine-readable receipt:
  `evidence/full_joint_v1/INDEPENDENT_DEPLOYMENT_REVIEW.json`.

The receipt preserves all 20 parameter-constraint checks and every replayed
trajectory identity. Its source hash binds the actual review implementation.

This bounded replay complements the separate complete-gradient and explicit
small-graph checks. It does not claim to enumerate every stochastic path of all
new models, establish continuous diffusion accuracy, remove voltage-projection
or tick-level recovery approximations, or qualify the new model for the existing
Rust backend. The small rollout sample is a deployment diagnostic; exact
finite-DAG metrics and the full result matrix retain their stated role.

The necessary independent consistency checks are complete. No further trials,
additional heldout sampling or model selection were performed.
