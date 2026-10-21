# Independent execution and fairness review

This review covers the continuous-latent experiment implementation before
registered heldout execution. It does not certify scientific superiority or
execution in the requested dedicated cloud. The development audit is bound to
the exact file hashes in `execution_audit_results.json`.

## Findings resolved before freeze

| Finding | Resolution verified |
|---|---|
| A single random stream diverged between flow-only and controlled continuations because they consumed different numbers of noise draws. | Separate batch, flow-matching, and rollout streams now pair the common updates. The audit compares actual minibatches, contexts, facts, styles, and flow-matching RNG states. |
| Continuation-specific encoder updates contradicted the same-context and same-public-predictor comparison. | Every continuation freezes the common Encoder after foundation training; every returned Encoder tensor matches the stored foundation. Decoder weights are also shared and frozen. |
| Nonfinite text logits could obtain a finite argmax and near-zero factual loss. | The codec review added modality/head finiteness handling, explicit failure loss and invalid flags. The separate codec audit exercises malformed outputs. |
| Global style entropy could conceal deterministic style collapse for each input. | Evaluation now computes lawful-mass-weighted entropy within each world across its four draws, plus lawful two-style coverage and lawfulness/consistency. |
| The heldout lock covered selection metadata but not the trained model or its validation evidence. | Checkpoint, training receipt, validation report and selection are hashed into the lock; replacement is rejected before heldout starts. |
| Source changes during training could have been captured as a new lock instead of rejected against the registration. | Production preparation rechecks the original source freeze at completion; heldout rechecks it again, in addition to the selection lock. |
| A stale environment flag could incorrectly label local execution as dedicated cloud. | The main entry checks the complete expected repository/branch/runner fields and source SHA. Local mode no longer inherits a true dedicated flag. Prepared and evaluated execution tiers must agree. |
| In-process mathematical audits changed the PyTorch thread count and needed their own module search path. | The main entry now inserts the script directory and restores arguments, module search path and thread count after each audit. Training seeds are explicitly reset before training. |

## Executed integration audit

`execution_audit.py` runs a deliberately separate, tiny development fixture:
24 generated worlds, world seed 9900919, training seed 919, and two updates per
stage. It uses no registered heldout namespace and does not assess model quality.

All eleven checks passed in the recorded local run:

1. All continuation encoders equal the frozen foundation encoder.
2. All continuation encoder parameters have gradients disabled.
3. Minibatches, context tensors, facts, styles and flow-matching RNG states are paired.
4. NDU and free-controller rollout noise is paired.
5. Equal-update training is bitwise reproducible on the tested CPU runtime.
6. Saving and loading a checkpoint preserves inference output bitwise.
7. Mutating hidden truth, target style and output targets cannot change generated output.
8. A lone stale cloud-verification flag is rejected before execution setup.
9. Replacing a locked checkpoint is rejected before heldout begins.
10. Changing locked source is rejected before heldout begins.
11. The reviewed files did not change during the audit.

Run with the experiment's pinned PyTorch interpreter:

```bash
python experiments/ndu_latent_riccati/review/execution_audit.py \
  --output ABSOLUTE_OUTPUT_PATH/execution_audit.json
```

The audit changes its process-local PyTorch thread count. The main experiment
should run it in isolation or restore the original thread count, as for the
other audits.

## Additional control verification

An independent direct check of the implementation agreed with a separately
constructed full-horizon quadratic objective: first control error
3.11e-15, analytic joint-drift Jacobian error 5.55e-17, and through-rollout
finite-difference gradient relative error 2.62e-10. The more comprehensive,
persisted `oracle/local_control_audit.py` is the canonical numerical evidence;
these development checks do not substitute for semantic evaluation.

The reported work counts now reflect the actual controller: each local NDU/MPC
step evaluates the Flow twice, once for the local model and once for the actual
drift. Each backward Riccati step performs two batched linear solves. The count
of backward steps is the sum of `min(lookahead, steps - i)` over outer steps.
The rank-three arm additionally performs eigendecompositions; those operations
are included in measured end-to-end time. These descriptive counts are not a
total FLOP measurement.

## Interpretation and remaining gates

- The free controller retains both an equal-update checkpoint and a separate
  continuation stopped by the measured NDU training wall-time budget, capped at
  1000 updates. The latter stopping count depends on runtime speed and load.
  The actual count, duration, budget ratio and checkpoint must be retained;
  this review makes no bitwise-repeatability claim for wall-time-adaptive
  stopping. A cap reached before the time budget is exhausted cannot be called
  equal training compute.
- Inference selection uses the registered CPU process-time ceiling, the same
  validation worlds and sampling noise, and requires an eligible free joint
  controller. It chooses from the declared candidate grid; it does not prove
  optimality over all possible controllers under that cost ceiling. Report
  both wall and CPU time and recheck the selected comparison's heldout cost.
- Warmup and repeated timing overhead are recorded separately. The timed model
  path includes Encoder, generation/linearization/feedback and Decoder work;
  independent semantic scoring is outside inference time.
- The nonlinear controller remains a local Gauss–Newton/Riccati approximation.
  Fixed lookahead measured in steps changes its physical horizon when the
  outer step count changes; the 4/8/16-step curve is not purely an integrator
  convergence curve.
- A failed registered efficacy or diversity gate is a scientific result. It
  must remain visible and cannot be repaired by retuning on heldout outputs.
- Dedicated-cloud completion still requires an actual assigned-runner and
  source-pinned execution receipt. Local audit success does not close that
  external execution requirement.
