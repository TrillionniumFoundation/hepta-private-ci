# Bounded readout training and policy feedback

This development stage freezes every fit's initialized physical cell parameters and trains the shared neural readout. The physical initialization still varies with the independent fit seed. All compared cell factors in a fit share those initial parameters. This is an explicit change from the previous joint physical/readout fit, made to study belief, continuation values, and policy-state supervision under a measurable CPU contract. It does not establish joint-dynamics learning or a continuous free-boundary result.

## Learning objective

The structured head continues to enforce

\[
Q_{\mathrm{STOP}}=0,\qquad Q_{\mathrm{SUBMIT0}}=1-2b,\qquad
Q_{\mathrm{SUBMIT1}}=2b-1.
\]

The same objective applies to free and structured heads: legal continuation-action mean squared error, legal terminal-action mean squared error, posterior-target belief cross entropy, and a pairwise teacher-best-action margin penalty. The margin target is capped at the registered margin and ignores teacher ties. The protocol specifies each loss weight. Terminal identities concern the head's own belief; neither an identity nor a small supervised loss establishes calibration or actual task utility.

The posterior and Q labels are training-only outputs of the inherited fitted observation-law teacher. The deployed `FactorRuntime.predict` receives public causal inputs and the realized cell state. It receives no teacher posterior, teacher Q, unread payload, or evaluator label.

Fixed physical parameters allow all independent-behavior features and exact conditional prefix distributions to be encoded once inside the candidate CPU budget. Subsequent updates train both neural layers. For an independent-behavior row the loss sums over its exact finite latent-state probability mass. For a policy-collected row it uses the actual recorded latent state with one-hot mass. Conditioning an on-policy row a second time with an unconditional prefix distribution is prohibited.

This is supervised data aggregation. It is not a policy-gradient method. No return-optimization claim is inferred from these detached occupancy records. Any future direct-return optimization must include action probabilities in the joint task/cell path distribution and validate that different objective separately.

The optimizer implements the ordinary AdamW equation with beta values 0.9 and 0.999 and epsilon 1e-8. Its small explicit implementation avoids charging a lazy optimizer-module import to whichever candidate happens to run first. A numerical check compares nine nontrivial updates against `torch.optim.AdamW` with tolerance 1e-13.

## Multiple feedback rounds

`feedback_round_fractions` specifies at least three distinct, increasing fractions of the candidate's CPU budget. At each threshold, the current complete model is snapshotted and its full artifact hash is recorded. The runner processes one complete training-world episode at a time and records the attempted world, execution seed, completed episodes, complete causal rows, snapshot identity, optimizer-update count, and CPU boundaries.

Multi-round and single-snapshot arms share the registered total number of requested feedback worlds. Multi-round arms divide them across the registered thresholds; the single-snapshot arm requests the same total at half the CPU budget. The sequence of training worlds and cell-sampling seeds is shared. Different policies can visit different states and consume different real CPU. A candidate reaching the memory or CPU limit retains its unfinished collection receipt and is not silently given a completed-feedback label.

After collection, subsequent mini-batches mix behavior and accumulated realized-policy rows according to the registered fraction. All completed prior rounds remain available. The final optimizer update is selected without validation checkpoint selection. The last feedback policy can differ from the final fitted policy; final-policy diagnostics must therefore inspect fresh states after fitting and may report uncovered states. Collection history is not a proof of complete final-policy support.

`behavior_rows_with_support` retains the declared strictly positive conditional-mass latent indices of rows that participated in at least one complete optimizer update, along with numerical public inputs and the complete observable state. Update-use counters are committed atomically with the model state. `visit_rounds` retains all collected rows and a separate `supervised_rows` subset with positive committed-update use. A collected but unused row is not admitted as actual supervised support. These records permit the separate final-policy audit to compare its declared full state representation against the actual supervised support. Coarse occupancy keys remain labeled diagnostics over available data.

## CPU and transactional updates

The matched candidate scope is model/optimizer setup, feature encoding, policy-visit collection, optimization, rollback if necessary, model export, and receipt assembly. Shared cohort generation and content-model setup are measured in the worker's complete cost. Serialization and storage after the function returns are also measured outside the candidate interval. Those costs must not be omitted from a complete-cost claim or added twice.

The implementation requires a platform with `ITIMER_PROF` and uses a process CPU timer. It reserves the registered small finalization interval and spends the remaining budget on actual work; it never sleeps or spins to fill an underused arm. A pending signal can only be delivered after some native library calls return. Therefore the timer is a containment mechanism, and the measured per-candidate tolerance is the acceptance test. An observed under-run or overrun beyond tolerance fails the CPU contract even when the timer behaved as designed.

After each complete optimizer update the model state is copied and committed with its update number. An interruption during an optimizer write cannot publish partially changed weights. On any interruption or exception the returned state is restored to the last complete committed update. Interrupted moment estimates are discarded because this function never resumes a partial fit. All completed update records, interruption reasons, failures, collection attempts and parameter changes remain in the receipt.

The outer candidate function explicitly enables autograd before entering the timed body and explicitly restores its caller's observed mode after the timer is disarmed. This also applies when the body raises. An asynchronous interruption during a nested `no_grad` context's entry or exit must not leave the following candidate unable to construct a backward graph. Each returned receipt records incoming, training-entry, and restored modes. The wrapper's measured CPU is included in the candidate CPU gate. This safeguard changes neither the objective nor successful optimizer update equations.

`training_valid` requires at least one complete optimizer update, no scientific/program exception, and completion of all registered feedback rounds. `cpu_compliant` independently requires the measured candidate CPU interval to lie within the registered two-sided tolerance. Every fit/arm remains in the experiment; accepting only successful or under-budget fits would change the estimand. Missing or invalid registered arms must block the associated formal inference under the protocol's failure rule.

## Verification

Run the focused checks with the installed CPU runtime:

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime:. python -m tools.hcsn.digital_feedback_20261101.budget_checks
```

The checks interrupt an unbounded collection call, interrupt a partially written second optimizer update and verify exact rollback to the first, preserve an injected numerical failure, exclude collected but unused rows from supervised support, restore signal ownership, compare AdamW equations, and verify that realized-state supervision is not reweighted by an unrelated prefix mass. The timer checks are explicitly platform-dependent research tests. They do not certify latency, energy, production ownership, or cross-architecture determinism.
