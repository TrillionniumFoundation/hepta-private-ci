# Bound NDU continuation in the existing System2 executor

Remote parent: `2baa214ce95048ec970a5eab651b58e4e076f553` (PR #1752).
Tested Python commit: `935d1a4ef8adc3d8d21955581057bd1eb7d48e2c`.
Branch: `research/shared-stem-ndu-system2-control-20261014`.
Research-only execution. No main merge, production selection or deployment.

## What is connected, and what is not

`system2_execution.run_reasoning` now has an opt-in bound `ndu_policy` and live
`WorkLedger`. It actually invokes propose, verify, and continuation-estimation
callbacks, and invokes the proposer again with verification feedback when the
new controller admits continuation. This is not rescoring a prerecorded trace.
Omitting the new policy preserves the original tuple-value callback path; its
existing regression tests still pass. There is no new wrapper runner.

This implements the explicitly limited linear-discounted computation-control
case described by docs/learning/NDU_FBSDE_SPEC.md (adaptive computation depth and
continuation semantics). It is a Python FLOAT64, nonnegative continuation profile,
not the native Q32 deterministic reference, general recursive-utility optimizer,
stochastic FBSDE solver, policy-gradient learner, or a proof of emergence.
The selected subject/objective and estimator revision are references, not a new
Neuron subject or authority source.

The nine-arm model-training matrix is unchanged. In particular this increment
DOES NOT enable `shared_421m_sparse_split_ndu` in matrix_runtime, turn a Decision
Head into a text generator, connect the native utility.ndu owner, or authenticate
an external critic. Existing split/retention/consolidation paths remain unchanged.

## The actual continuation comparison

The fixed policy binds objective, subject, critic revision and training cutoff,
expiry and estimate age, numeric utility coefficients, and the complete execution
budget: all phase caps, metering policy/profile, maximum rounds and callback count.
The executor rejects a different budget, depth or meter. The critic cutoff must
precede the public task boundary. Policy validity is checked before callbacks.

Each decision context binds the public task, current candidate, feedback, prior
trace, current boundary time, remaining rounds/calls and pre-critic resources.
A typed estimate names that exact context, the fixed critic and support artifact,
its observation cutoff and expiry. Future observations and substituted contexts
reject. Values and coefficients have explicit finite/type/range checks. Neither
matching hashes nor supplied timestamps prove that the external producer is
truthful, independent, trained or calibrated; arbitrary Python callbacks are not
sandboxed. Public inputs contain no explicit final-evaluation-label field, but this
is not an information-flow proof or a defense against labels encoded in text.

An estimate supplies a stop-value upper support in [0,1] and at most 16 JOINT
continuation scenarios. Their integer probability masses sum exactly to 1,000,000.
Each contains nonnegative value support at the NEXT boundary, a duration upper
bound in nanoseconds, and an upper bound on scalar-equivalent formula work.
The next segment ends after the next propose/verify pair, before another critic.
The value at that boundary must already represent the intended remaining policy,
but must not include this segment's costs/discount a second time.

The implemented lower comparison is

    sum_j p_j * (exp(-rate * dt_j_upper_seconds) * U_j_lower
                 - lambda_work * work_j_upper - lambda_time * dt_j_upper_ns).

Continue only when this exceeds stop_upper plus the frozen positive-or-zero
margin. Nonnegative supported values are essential to using upper duration bounds
conservatively. This profile rejects negative continuation supports rather than
pretending the same monotonic inequality applies. It preserves correlations
between duration and value; discount-at-mean-duration times mean-value is not used.
These are conditional support calculations, NOT statistical confidence bounds or
rigorously outward-rounded interval arithmetic.

Every positive-mass scenario's worst duration/work must fit the resources LEFT
AFTER the critic actually ran. Its already-spent cost is included in the live
ledger but not subtracted again from the marginal continue-vs-stop comparison.
Missing support, expired support, unknown work coverage, insufficient resources
or no supported net gain stop computation. The initial propose/verify pair and
first value request are not themselves chosen by a higher-level value-of-valuation
policy; this is not a globally optimal metareasoning controller.

## Execution measurement and checking the next segment

Proposer, verifier and value have separate components under the SAME online search
budget. `budget_state` reads nonfinal remaining resources without sealing the
ledger or exposing its mutable scope state. Unknown/failed work keeps complete
counts null. Invalid callback outputs are failed ledger calls, not only trace
annotations. No arithmetic formula is added or relaxed by this increment.

After an admitted next propose/verify segment, the actual observed formula-work
and wall-time increments are compared with the declared worst-branch bounds.
Violation records the generated candidate but does NOT return verifier acceptance;
it terminates as continuation_support_violated. Global formula caps still check
before supported ATen dispatch. Time/RSS checks remain cooperative and do not
preempt a running native operation or replace OS resource isolation. Work in an
external process/API, tokenizer/Python scalar arithmetic, independent evaluation
and energy attribution is not certified by this in-process ATen ledger.

The V2 reasoning report retains the fixed policy, exact context and estimate,
post-critic resource state, decision timestamp, computed comparison, actual segment
observations and callback trace. A test reconstructs the decision from serialized
inputs and matches the deterministic output. These reports do not enter the
existing scientific final-panel pipeline as if they were authenticated paired
model runs; independent evaluation/owner integration is still required.

## Observed tests and diagnostic

The unchanged predecessor passed 248 tests. The final source passed 279 DISTINCT
tests twice, zero failures/errors/skips: 248 retained + 12 continuation tests +
19 actual callback/meter/control tests. All six remote Python blobs match the
locally tested bytes. Compileall and scoped whitespace checks passed.

Tests execute real CPU tensor operations in procedural propose/verify/value
fixtures, not a trained reasoning model. They cover branchwise discounting,
correlated duration/value, rare expensive branches, interval uncertainty, stale
or future support, policy/budget replacement, critic cost, unknown operators,
expiry during proposal, changed task/context, actual support violations,
serialized decision replay and preservation of the legacy eight System2 tests.
The retained first serialization-replay failure was a test aliasing mistake;
copying the test input before rebuilding typed branches fixed it. No scientific
acceptance threshold was relaxed.

Five additional diagnostic cases call the actual executor:

| Case | Callback attempts | Result | Observed formula work |
|---|---:|---|---:|
| Supported continuation | 5 | Verifier accepts revised procedural answer | 9 |
| Declared cost exceeds gain | 3 | No-supported-net-gain stop | 6 |
| No continuation support | 3 | Unsupported-continuation stop | 3 |
| Critic consumes remaining budget | 3 | Infeasible-continuation stop | 23 |
| Actual work exceeds declared bound | 5 | Support-violation stop | 6 |

All values, probability support, task and external clock in those examples are
explicit fixtures. The tensor operations and their dispatch counts are real, but
the arithmetic task answer is procedural, not learned; these are not pretrained
model quality, efficiency, calibrated utility, or reasoning-emergence evidence.
Raw reports retain this distinction and all independent-success flags are false.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

The separate installed-HF attempt failed at import with missing Transformers;
zero of its three checks ran and none is counted among 279 passes. This session's
GitHub/model-site/package-site DNS check failed. No real weights, approved tasks,
project cloud, GPU/native, full repository/Rust or hosted-CI success is claimed.
The local workspace is a bounded source slice; just and full codex-rs are absent.

Next acceptance requires actual frozen/cross-fitted critic artifacts and calibrated
joint support, real generator/verifier owner adapters, cost-matched fixed-depth and
no-search controls, independent final task outcomes, complete work/energy/memory
and native ownership/recovery. Multi-generation learning, multimodal generation,
1024/4096-Cell qualification and 10T/100T equivalence remain unestablished.
