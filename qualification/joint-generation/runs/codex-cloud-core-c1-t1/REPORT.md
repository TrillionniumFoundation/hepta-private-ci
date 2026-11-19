# Core-c1 t1: pre-training calibration construction failure

The first actual core-c1 TRAIN/validation build exited **1**. Source
`893a13fd165ae530531687933133fbbe2f9f58b4`, frozen execution
`a80b6b6e23e7259d83e402c40d70db44c470d167`.

The original error is retained verbatim:

`ValueError: training source/target matching failed: source class 4, target 3`

TRAIN/validation construction occurred, but calibration selection failed before
native compilation, shared decoder/pretraining, or any candidate. The source
order and absence of a build/model artifact establish that boundary. No score,
selected model, readiness pass or qualification is claimed. Both core-c1 and r2
formal test markers remain absent. No formal fold was constructed.

The old class-wise matcher correctly enforces its additional cyclic joint-cell
pattern; that particular pattern is infeasible for this fresh TRAIN metadata.
The declared balanced-margin requirement does not require those exact joint
cells. A prospective global source-class/physical-source/target-class flow can
preserve all 72 unique sources, six of each source/target class and interleaving
without imposing unavailable individual cell pairs. Its implementation, hand
proof and new protocol/source freeze are still required; it is not a result
from this failed build. Do not change data seeds, relax margins/budget/gates,
relabel this outcome, or retry this identical source.

Complete child process CPU was 0.553682 seconds, launcher own CPU 0.000561187,
wall 0.554564063. The failed helper never returned a completed shared ledger;
no per-arm completed cost or phase-specific reconstruction is invented. Outer
cost includes startup, imports, data work and failure/telemetry serialization.

The pre-build source suite passed 216 independent tests and 49 root tests.
Initial/corrected evaluator tests, the binding fixes and final suite logs are
retained separately. Those tests did not exercise a real new split, so they
are not substituted for this actual construction failure. This is the exact
failure and the allowed TRAIN-side implementation blocker; formal test remains
sealed while the repair is reviewed.
