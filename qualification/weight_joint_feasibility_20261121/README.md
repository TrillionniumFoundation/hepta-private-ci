# Fixed-hidden joint policy feasibility research

This source-only qualification studies whether one fixed hidden representation
can support a set of prescribed policy decisions through a small affine
readout edit. It is an isolated research implementation. It does not include
checkpoints, private data, scientific execution records, production routes,
network access, trading operations or a deployment owner.

The main problem has three continuation readout rows with 49 coordinates each.
For a state with augmented hidden vector `H`, own-law target action `t` and
legal competing action `j`, a continuation-row displacement `d` must satisfy

```text
(d_t - d_j) · H >= original_score_j - original_score_t + margin
```

Only editable continuation terms appear on the left. STOP and the two terminal
scores are fixed in the principal Q147 problem. When two fixed terminal
actions have the wrong order, that particular state cannot be repaired by
editing continuation rows. Such states are recorded explicitly, with their
support and weight, before any narrower repairable-subset question is solved.

The solver minimizes `0.5 * ||d||²` without imposing the norm budget inside the
QP, then compares a numerical radius bracket with the original budget.
Lowest-index action ties are part of the contract. A finite lower-index safety
margin is distinguished from the closed problem and from the infimum of a
strict-policy problem. A strict infimum need not be attained.

## Source and semantic boundary

The private-input workflow expects existing source-bound original checkpoints,
cached complete TRAIN inputs and scores, complete state-order metadata, and a
previous own-law Bellman teacher. It verifies model and data identities and
the original teacher's per-world hashes. It does not treat the older training
dataset's `best`, `goals` or `own_Q` fields as the own-law optimal policy.

Original hidden activations and scores are recomputed with the declared
ordered FP64 reductions. Original scores must match the cache bit-for-bit.
The independent reader reconstructs those values from the original inputs;
it neither imports the solver nor trusts a saved hidden array or result summary.
It does not independently regenerate the earlier CTMC teacher or establish
external label custody.

Full structural support, incumbent positive eligible occupancy, and
occupancy-times-action-gap mass are separate quantities. Incumbent occupancy
does not predict the occupancy of an edited policy. Matching actions on
incumbent-occupied states is not an end-to-end utility evaluation. All earlier
DEV/CONF data remain exposed; this workflow creates no new holdout set.

## Numerical evidence and its limits

For nonnegative multipliers `lambda`, the dual expression is

```text
D(b, lambda) = b · lambda - 0.5 * ||A.T @ lambda||²
```

The same multipliers can be evaluated against the closed right-hand side
`b0`. A subset of valid constraints provides a lower bound for the complete
problem; a candidate upper bound requires a complete support scan and actual
FP64 action checks. The reader checks primal violation, dual signs,
stationarity, complementarity, objective gaps and radius labels.

Infeasibility vectors are retained as numerical Farkas indications. They are
not exact certificates. Time limits, iteration limits, failed residual checks
and incomplete constraint generation produce UNKNOWN where the evidence is
insufficient. No alternate solver or automatic technical retry follows.

The optional closed-dual audit evaluates the necessary radius condition
`b0 · lambda <= R * ||A.T @ lambda||₂` using the same saved multipliers. Its
ordinary IEEE dot-product sensitivity allowance is explicitly separate from
an outward-rounded interval proof and from errors in the original hidden or
teacher construction. An epsilon-only indication is not promoted to a
closed-radius exclusion.

## Finite related questions

The predeclared sequential diagnostic first changes the belief row to satisfy
terminal sign/margin constraints, then solves the continuation problem with
that belief fixed. Its combined norm is a constructive upper bound only when
the complete declared constraints pass. Failure of this sequential procedure
does not exclude every possible joint belief/readout choice.

The post-result continuation-only diagnostic restricts both target and
competitor to the three continuation actions. It is a necessary subproblem
for any belief-head choice at fixed hidden features. Its success does not
establish joint feasibility, and its finite-margin result remains distinct
from a closed-radius result. Its separate protocol records any authorized
recovery of original hidden values and charges that recovery inside its cap.

Exact-input and saved-hidden alias audits group exact bytes together with the
same complete legal mask. They distinguish exact target disagreement from
strictly positive own-law regret; a policy tie is not automatically a value
loss. They do not silently treat different masks or different checkpoints as
the same deterministic-policy problem. These audits are marked post-result.

## Files

| File | Role |
| --- | --- |
| `joint_solver.py` | Affine constraints, bounded Clarabel calls, residuals and numerical dual diagnostics |
| `run_study.py` | One fixed real-input study and original-byte preservation |
| `verify_records.py` | Independent original-input reconstruction and result arithmetic |
| `common.py` | Private-input paths, identities and own-law teacher source contract |
| `freeze_protocol.py` | Zero-neural-forward preflight and create-only protocol seal |
| `supervise.py` | Separate main and reader CPU, wall, address-space and affinity limits |
| `closed_dual_addendum.py` | Saved-dual closed-radius diagnostic without optimization |
| `alias_audit.py` | Exact X-plus-mask metadata audit |
| `continuation_only.py` | One explicitly authorized necessary-subset diagnostic |
| `hidden_alias_audit.py` | Saved checked-H-plus-mask metadata audit without new forwards |
| `supervise_posthoc.py`, `supervise_continuation_only.py` | Separate single-use audit resource limits |
| `test_synthetic_controls.py` | Offline synthetic controls requiring no private inputs |

## Offline qualification

Use Python 3.12 and the pinned numerical packages in `requirements.txt`, then
run from this directory:

```bash
python -m unittest -v test_synthetic_controls.py
```

The controls cover actual solver sign conventions and known optima, impossible
synthetic inequalities, fixed-terminal tie order, complete-support residuals,
epsilon versus closed separation, the physical belief-score guard, and the
independent reader's mismatch rejection. They are not a replay of private
model experiments and cannot establish model quality.

For an authorized private-input reproduction, set `HEPTA_WSP_INPUT_ROOT` to
the root containing the three earlier research input directories, and set
`HEPTA_WSP_PREVIOUS_ROOT` to the previous continuation study's Neuron directory.
Original receipt paths must still resolve to their authenticated bytes.
The source-only public copy replaces only the original local input-root
constants with environment configuration; the experiment's frozen files are
kept separately and unchanged.

Real-input execution requires its own static review and protocol seal. CPU
and address-space limits are local research process controls, not production
resource guarantees. Unknown future workload, quality value and cost bounds
retain `KEEP_ORIGINAL_AND_STOP`; this project supplies no production adoption
or financial payoff claim.
