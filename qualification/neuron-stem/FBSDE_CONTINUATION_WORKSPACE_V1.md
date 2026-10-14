# Shared nonlinear continuation and a verified numerical decision workspace

Continuation of #1550 at eb3b2ec34fa75730ed4052388e8a1f7f26afd112. This uses the
same binary tanh FBSDE, original Riccati-Newton kernel, contraction domain and
1e-10 precise-solve target. No current policy, native owner or scientific floor
is replaced. This is a finite NUMERICAL control task, not semantic reasoning.

## What can actually be shared

A bank contains three solved initial-state anchors and their tangent vectors
for one exact coefficient/time-grid/noise profile. At each anchor the existing
node-specific Riccati elimination provides P_i. With initial sensitivity s_0=1,

    dY_i/dx0 = P_i s_i; s_child = s_i + a*h*dY_i/dx0.

A nearby initial state uses Y(anchor) + dY/dx0 * (x0-anchor) as a PROPOSAL. The
Newton affine defect is not reused as a derivative, nor are time-level peers
forced to share a slope. Coefficients, scope, generation, fixed objective and
full artifact bytes bind the bank. Loaded anchors and tangents must satisfy the
original and differentiated equations even if an edited artifact is rehashed.
The bank is immutable after loading; external arrays cannot mutate its tuples.
Scope identifiers are not authorizations. Native checkpoint/CAS is unchanged.

No Taylor remainder guarantee is assumed. Every proposed trajectory is checked
against the ORIGINAL global residual. No out-of-anchor-domain extrapolation,
new target, fictitious zero uncertainty or cross-scope reuse is admitted.

## A decision needs a value-gap bound, not precise solutions for every loser

The public candidate set is fixed before stochastic outcomes. Candidate j means
initial state x_j and a deterministic nonnegative cost c_j; its value is
V_j=Y_0(x_j)-c_j for the same discrete coupled equation. This does not optimize
all continuous-time policies or let the controller select a favorable noise leaf.

For a candidate node vector v_j, let e_j=||v_j-Phi(v_j)||_infinity/(1-q), using
the inherited q<.98. In exact arithmetic the fixed-point theorem gives
V_j in [v_j[0]-c_j-e_j, v_j[0]-c_j+e_j] = [L_j,U_j]. Choose b maximizing L_j.
Then max_j V_j - V_b <= max_j U_j - L_b. The workspace stops only when that
registered gap is <=1e-8. Otherwise it refines the unresolved candidate of
largest upper bound using the original Newton solver, then checks again.

Every proposed hypothesis, original residual, revised value, refinement order,
stop gap and final rendered selection is retained. A budget-exhausted unresolved
workspace returns no action and no text; it does not quietly pick a guessed
winner. Ordinary floats are not outward-rounded certificates. Model/semantic
error and continuous-time error are outside this numerical bound.

## Actual comparison protocol

Two coefficient profiles x three time depths (5/8/10) x eight candidate sets =
48 numerical queries; each has eight choices. Input generation is fixed before
solving. Three controls run in fixed-seed randomized interleaving, three repeats:

- cold_all: solve every choice from zero with Riccati-Newton;
- warm_all: same complete exact comparison, using shared nonlinear proposals;
- verified_search: check all proposals, then refine only choices that can still
  change the epsilon-optimal selection.

All methods have the same 32-refinement cap, objective and decision-gap target.
Search may leave losing candidates numerically coarse ONLY because their error
bounds cannot change the decision at that target. Raw proposal ranking is also
retained as a negative control; it does not satisfy the verification contract.
Bank compilation AND load validation are charged once to actual shared uses.
There is no amortization over imagined requests. Timings cover complete query
functions including all residual checks and decoding, not only Newton updates.
Serialization, independent auditing and host lifecycle are not fully attributed
to each arm; these remain numerical component costs, not full deployment costs.

The independent saved-file checker imports neither bank nor solver. It rebuilds
ancestor states, original/tangent equations, initial proposals, causal refinement
order, final decision gap, complete precise controls, paired timings and charged
preparation. Hashes are integrity checks, not independent execution attestation.
No generated task count or benchmark repetition is an independent real outcome.

## Run and boundaries

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile continuation_workspace_v1 --output /new/workspace-study
```

The existing exact head/merge jobs additionally run this profile and retain its
files. All physical Encoder, risk calibration, acquisition failure diagnostics
and earlier numerical controls remain. The explicit tree is still exponential
in time depth. No new Encoder, learned policy or language decoder is executed
here. Real semantic hypotheses and independent validation remain a separate
capability experiment; CPU tail reliability, risk/retention, production no-change
and native final-use/recovery are NOT established by these numerical results.
