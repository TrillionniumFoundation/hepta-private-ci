# V5 actual peer aggregate candidate: separate trial and cold scopes

**Source proposal only. Both protocol templates are inactive.** Preparation used
text reads, SHA-256 calculation, JSON generation, and AST inspection. No model,
project test, numerical solve, physical forward, or candidate export was run.
Root must register each execution separately before activating its protocol.

## Why another candidate must actually be evaluated

The direct peer round operates on two distinct retained observation rows from
the original V4 failed sensitivity record. Each host forms its own sufficient
statistics, exchanges them through the admitted SSH path, solves the exact
six-coordinate ridge equation, and agrees on one complete step identity.
This establishes a different provenance from the earlier central SVD proposal.

The peer solver uses exact `Fraction` arithmetic on the original binary64 input
values and applies the ridge once to the aggregate. It then converts each exact
solution coordinate to the nearest binary64 value. The central V4 proposal used
an augmented least-squares SVD. Close numerical agreement between their steps
does not transfer a physical trial, an exported checkpoint, or a cold result.

This entry point therefore uses the **actual received peer delta** to construct
a new full tensor state, runs its own fresh physical prediction, applies the
unchanged V4 actual-reduction gate, and exports a new complete checkpoint only
if that gate passes. A second, separately admitted invocation verifies that
new checkpoint through the original strict numeric runner in a fresh child.
Neither mode reads the old central candidate file or inherits its acceptance.

The original parent remains the full checkpoint
`0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f`,
profile `4a8feafa490224f0ad14d318835f51d1147b8b6b93c7a56e9f9eb3ddc3d43d77`,
and tensor state `136026bde0867265b040f679e60fb991b131b6d8403127fa7b2a94237da5f907`.
The retained original failed result is
`15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105`.
Its smooth gate remains `FAILED`. A result at a different accepted parameter
point does not change this original-parent classification.

## Bound inputs and peer admission

Both modes require the same content-pinned `common.json`, complete `ai395`
result, and complete `pocket4` result. Root fills the three hashes only after
the single admitted peer round has produced retained evidence. The common
record also binds the exact peer source files, row identities, original parent,
layout, source linearization, and binary64 ridge.

The consumer requires all of the following before loading a model:

1. Both results identify the same common record, report the expected physical
   hosts, cross-reference each other's complete node identity, and confirm one
   step. The sent frames of each host must equal the other's received frames,
   including each frame's hash and byte count. Each direction has exactly three
   frames: hello, contribution, and step.
2. The two complete step objects and their hashes must agree exactly. Approximate
   equality or similar delta values do not satisfy this condition.
3. The actual direct connection receipt identifies the source `10.77.0.2`, peer
   `10.77.0.4:22`, bound `br-usb4` interface, strict SSH host verification, and no
   controller relay of contributions. The peer source versions are checked
   against their registered hashes.
4. Each contribution's `G`, `h`, and residual-square scalar is recomputed exactly
   from the corresponding row of the original frozen Jacobian, original base
   output, and fixed target. Merely asserting a row hash or a rank-one PSD shape
   would not establish that the statistics came from these observations.
5. With `G = JᵀJ`, `h = Jᵀ(target - base)` and
   `λ = Fraction.from_float(0.001)`, the **received** exact vector must satisfy
   `(G + λI) delta = h`. This verifies a solution; it does not solve the system
   again. The code has no elimination, least-squares, or optimizer call.
6. The received float vector must equal the componentwise conversion of the
   exact vector. Its hexadecimal values, binary64 array hash, reported
   quantization errors, half-ulp bounds, and rounded stationarity are checked.
   The stationarity limit remains the peer protocol's `1e-12` bound.
7. Predicted reduction is independently recomputed at the received **rounded**
   vector, including the one global ridge penalty. The exact aggregate identity,
   norm bound, and rational/float objective fields must agree.

The two original rows have exact row rank two; a nonzero two-by-two minor is
checked. Thus data rank is two and data nullity four, while the positive-ridge
system has rank six. The record explicitly preserves this distinction.

The `learning_receipt_sha256` in the physical edit is the SHA-256 of the entire
actual `ai395` peer result. The trial and edit records additionally bind the
other peer result, common record, and complete agreed step hash.

## Unchanged physical objective and gates

The same six coordinates are used, at scale one: `raw_cost[4]`,
`input_drive.weight[0]`, `input_mark.weight[0]`, `recurrent.weight[96]`,
`readout.weight[0]`, and `readout.bias[0]`.

The targets remain the original retained two scalar base margins plus
`[0.0001, -0.0001]`; both observation weights remain one. The ridge is `1e-3`,
and the Euclidean step norm must not exceed one. There is no clipping, target
change, coordinate selection, or re-solve. The original fixture's byte hashes
are checked before rebuilding the complete initial population and running its
four ticks with initial margins `0.59` and `0.73`.

For the rounded received step `d`, the trial evaluates

\[
\Phi(d)=\tfrac12\lVert f(\theta_0+d)-y\rVert^2
       +\tfrac{10^{-3}}2\lVert d\rVert^2.
\]

Its surrogate prediction uses the retained matrix `J`, with exactly the same
objective evaluated at `base + Jd`. There is no new derivative computation.
The code checks consistency with the peer's exact rounded-step prediction
using the original receipt-arithmetic tolerance, `atol=1e-20`, `rtol=1e-12`.

Acceptance retains the V4 rule: `pred > tau`, `ared > tau`, and
`ared / pred >= 0.1`, where
`tau = 1e-12 + 1e-6 * max(abs(Phi0), abs(Phi_trial))`.
The original pre-forward prediction floor and unit norm cap also remain.

This is a guarded nonsmooth-surrogate trial. It does not certify a classical
Jacobian, a Clarke Jacobian, or a semismooth Newton algorithm. Successful
nonlinear reduction is measured anew; it is not inferred from equation
agreement or a central candidate's earlier result.

## Restoration, export and independent cold identity

The trial reuses the original `restored_forward` physical path. An additional
outer guard snapshots complete state, trainability, preexisting gradients,
config, every module mode, and diagnostics. It checks non-diagnostic invariants
after the original cleanup and restores them again in `finally`, including
the original gradient objects. An unexpected mutation fails the run even when
restoration succeeds. No extra physical forward is needed for these checks.

The `diagnostics_restored=true` field records completion of the saved deep-copy
assignment. Both the pinned original helper and the outer guard restore
diagnostics this way; neither runs a separate deep-value equality assertion for
that field. The explicit pre/post assertions cover tensors, trainability,
gradients, config, and modes. This distinction is part of the static audit and
must not be reported as an additional diagnostics test.

Only an accepted trial produces `EDIT_RECEIPT.json` and
`aggregate_candidate.pt`. The original strict exporter checks that only the
declared parameter elements changed and writes all tensors, buffers, config,
constructor, trainability flags, source identity, parent identity, and edit
receipt hash. This is a research artifact; no active model pointer is adopted.

Cold verification has its own inactive template and requires root to pin the
new aggregate `RESULT.json` after the trial. It validates the new trial/edit/
export chain, recomputes its actual gate, creates a profile pointing to the new
complete checkpoint, and invokes the unmodified `numeric_runner.py` through
the original bounded child-process helper. The cold driver itself imports no
numerical framework or model.

The child loads the complete model from that profile and makes one prediction
from a newly built initial population. Candidate bytes, full tensor state,
source binding, task, clock `0→4`, and saved population are checked. Its two
final margins must match the new aggregate trial using the original cold
tolerance, **`atol=1e-12`, `rtol=1e-11`**. No comparison to the old central trial
can satisfy this gate.

## Separate bounded execution ledger

| Operation | Aggregate trial | Independent cold |
| --- | ---: | ---: |
| Model loads | 1 original parent | 1 new candidate in child |
| Full fresh physical forwards | At most 1 | 1 |
| New solves / VJPs / FD calls | 0 | 0 |
| Historical training matrices / optimizer updates | 0 | 0 |
| Candidate exports | At most 1, after acceptance | 0 |
| Child invocations | 0 | 1 |
| Retries / backtracking | 0 | 0 |
| Time cap | 120 s wall / CPU, 121 s hard CPU termination | 55 s child / 90 s outer wall |

Exact rational arithmetic verifies received statistics and solution identities;
it does not consume a new equation solve. The cold child uses the original
process-group cleanup helper. On a child exception, unknown model/forward
counts are `null`; the fixed maximum remains one each. No unobserved successful
operation is fabricated.

Any invalid identity, source, arithmetic check, nonfinite value, time or budget
limit, restoration failure, or cold mismatch is terminal for its registered
scope. A completed negative nonlinear trial is retained as
`COMPLETED_SINGLE_PEER_TRIAL` with `decision=REJECTED` and no export; this is a
negative observation, not an accepted candidate. Consumers must require both
accepted decision and exported artifact. A cold run requires the accepted
aggregate's new, pinned result. No rejected or failed result authorizes a retry.

The exhausted old experimental budgets and the original failed record remain
unchanged. Root records these scopes in a new admission ledger before execution.
The scripts use exclusively created new output directories/files. Cross-output
single-use authorization is enforced by that external ledger, not inferred from
an output path.

## Invocation contract

`aggregate_candidate.py --mode trial` and `--mode cold` share required flags:
`--protocol`, `--protocol-sha256`, `--failed-result`, `--parent-profile`,
`--peer-common`, `--ai395-result`, `--pocket4-result`, `--peer-code`, `--materials`,
and `--output`. Cold additionally requires `--trial-output`.

Place this directory beside the original pinned `native_profile_v4`,
`sensitivity_v4`, and `nonsmooth_trial_v4` directories. `--peer-code` supplies
the exact retained peer source directory. Use the original numerical interpreter
and freeze `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS` to one.
The templates have null runtime-evidence hashes and `ready_for_execution=false`;
they cannot run until root registers and fills the concrete hashes and writes a
separately hashed active protocol. Bootstrap refusals must be retained in the
process log; ordinary admitted-run failures produce `RESULT.json`.

These retained rows are not independently collected new-user tasks. Passing
the complete chain would establish actual two-host contribution agreement,
actual aggregate parameter materialization and nonlinear reduction, and cold
reuse of that exact candidate. It would not establish arbitrary decentralized
training, cross-user task adoption, scaling, or newly learned representations.
Frame byte counts describe this protocol only; they do not measure bandwidth
or prove a reduction in total training time.
