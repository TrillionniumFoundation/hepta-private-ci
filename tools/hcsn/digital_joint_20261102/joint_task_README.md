# Dynamic belief task contract

`joint-current-at-due-fixed-deadline-v1` is a new finite dynamic task. It does not
reuse the archived static-label task's source-time observation interpretation.

An exogenous hidden state follows the declared 31-active-plus-two-refractory
CTMC over six public intervals. The independent environment implementation is
NumPy/SciPy in `joint_law.py`; it never imports the differentiable Torch kernel.
The finite generator includes boundary exits, exponential refractory recovery
and continuous truncated-Gaussian reset probabilities projected into bins.
Spatial approximation remains explicit; this is not exact continuum dynamics.

The public prior is a balanced two-point distribution at normalized positions
nearest ±0.125, ±0.375 or ±0.75. Every model receives the same prior information.
This avoids a deterministic initial label. The six drives are public and
exogenous, with drift `bias + gain*drive[t]`; drives are independent of the
controller's observed symbols and do not change with its actions. The private
latent trajectory is therefore shared across policies on each world.

Every submission predicts the **fixed boundary-six sign**, even if submitted
earlier. Positive means strictly greater than zero; the center-grid atom belongs
to label zero, lower refractory to zero and upper refractory to one. STOP earns
zero before fees. Correct/incorrect submission earns +1/−1, less all actual
read, repair and public logical-time charges. Stopping cancels pending work
without refunding prior fees. A policy cannot choose an easier target time by
waiting or terminating at a different time.

READ requests have delay one or two. They observe the latent sign at their
**completion boundary**, passed through the public observation reliability and
the actual fixed FullHX content model. Packets/reliabilities at array index `i`
belong to boundary `i+1`, not to request tick `i`. Packets exist beforehand, but
the Owner opens one only when a request is due. `source_tick` records request
time; `observation_tick` records the actual due boundary. Each advancing action
first advances the process, then a due packet completes. Missing packets retain
fees and set broken; REPAIR clears broken explicitly. No private latent state,
fixed target, teacher posterior or teacher Q enters Owner's policy-facing state.

Shared public input has 43 features: the archived public36, six drives, and the
prior distance. Histories retain request time, completion time, observation and
reliability. The convenience 12-feature history vector indexes completed
observations by due boundary; models may consume the full history records.

`Oracle(public, law, confusion)` propagates the full finite state distribution
and conditions at completion time. Its terminal values predict boundary six by
propagating through the remaining public schedule. Its bank has nine endpoint
probabilities: next boundary, next-two boundary and final boundary, each at
strict normalized thresholds −0.5, zero and +0.5. Repeated horizons near the
deadline are intentional. Teacher quantities are targets/reference only.
When confusion is fitted from TRAIN calibration, this DP is optimal for that
declared CTMC/decoder model, not necessarily for FullHX's unknown true law.

`cohort(..., source_commit)` requires a 40-character published source identity.
TRAIN/validation and confirmation have disjoint registered seed namespaces.
Worlds save all six packets' expected hashes, including explicit expected
absence for injected missing packets, public schedules, private evaluator
trajectories and the independent environment law. Formal generation must wait
for the corresponding published source/protocol; a hash string by itself is
not evidence of publication. No formal world was generated during the fixture
audit.

Run the small deterministic semantic audit from the repository root:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_task_audit
```

It checks fixed-target posteriors by independently enumerating 128 two-state
paths, a hand-computable one-read Bellman value, no pre-due content, the
request/completion time distinction, missing/repair/cancellation and complete
fees. These checks establish task semantics, not learned task benefit.
