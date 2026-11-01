# One finite process, several marked operators

## Source and scope

`marked_flow.py` consumes the rates, active outflow, reset weights and Erlang
phase rate returned by the unchanged `hcsn_distributional_v2.make_flow`.
The frozen upstream SHA256 is recorded in `OPERATOR_PROTOCOL.json`. No second
production reset rule is introduced. The audit independently reconstructs the
declared physical jumps with NumPy to check the implementation.

The process is a finite CTMC on active cell centers and refractory phases.
Its lower boundary reflects, the upper boundary fires, and the last phase
returns to the inherited reset distribution. With zero phases, reset is
instantaneous. The spatial approximation is not an exact continuous diffusion,
and Erlang residence is not deterministic residence of the same mean. These
operators are not the full He-Xiong financial equity/default model.

## Generator and firing marks

Use row probability, `p'(t)=p(t)Q`. The firing matrix `R` records upper-exit
transitions, including diagonal marks when instantaneous reset returns to the
same cell. Such an event counts even though its state change cancels in `Q`.
The event intensity is `lambda=R 1`, and `Q0=Q-R` kills at the next firing.
Refractory transitions remain present in `Q0`: a next-event query from a
refractory state includes the wait until recovery and then the next crossing.
It does not replace this wait by an already-active first-hit query.

For a fixed interval `t`, the complete transition is `T=exp(tQ)` and the
no-event transition is `K=exp(tQ0)`. For an initial unit law `p`,

- current state is `pT`;
- no-event subprobability is `pK`;
- no-event survival is `pK1`, and next-event probability is `1-pK1`;
- repeated event expectation is `p integral_0^t exp(sQ)lambda ds`.

The last quantity can exceed one. Active occupancy after propagation includes
paths that already fired and reset; it is not no-event survival. No-event mass
is never normalized into a conditional density by this interface.

The repeated-event integral uses an augmented matrix exponential and never an
inverse of `Q`. Reducible, zero-event and zero-noise finite chains are allowed.
At `t=0`, dynamic transitions are identity and dynamic counts vanish.

## Local values

For discount `rho>0` and firing reward `b-cost`,

`J = (rho I-Q)^(-1) [(b-cost)lambda]`.

The discounted next-event transform is `(rho I-Q0)^(-1)lambda`. The positive
discount gives an invertible finite resolvent in exact arithmetic even when
the underlying generator is singular. Results must still be finite; this is
not a uniform numerical accuracy guarantee as discount approaches zero.
Negative firing rewards are permitted.

This `J` evaluates a local frozen policy. It does not optimize the boundary,
anticipate future inputs, or represent the downstream task's Bellman value.
The existing infinite-domain boundary oracle remains a separate boundary prior.

## Content moments and the count generating function

With `eta` in `[0,1]` and nonnegative decay `gamma`, define

`Q_eta = Q - (1-eta)R - gamma I`.

Then `T_eta[i,j]=E_i[eta^N_t exp(-gamma t) 1{X_t=j}]`.
At zero decay, `eta=0` gives the killed transition and `eta=1` gives the full
transition. The derivative at `eta=1`, multiplied by `1`, gives the repeated
event vector. An independent marked-uniformization polynomial retains every
event-count coefficient up to a declared Poisson tail, including self-marks.
It checks the PGF and a signed state-dependent content first moment.

If `M[state,feature]=E[h_feature 1{X=state}]`, its multiplicative-event
propagation is `T_eta.T @ M`. This is a first-moment closure; it does not retain
the complete joint distribution of neural content and physical state.
Applying nonlinear content updates to expected moments defines the neural
model and is not automatically the expectation of a nonlinear sample-path net.

## Boundary remapping

The inherited physical-overlap remap is `M_full`. Its immediate event vector
and event destination define `M_mark`. Set `M_noevent=M_full-M_mark`.
The full and no-event interval maps are respectively `M_full T` and
`M_noevent K`. Counts include the immediate event plus the subsequent count.
Thus a zero-duration observation can still fire when the new boundary swallows
active mass. Existing refractory mass preserves its phase.

If the content model scales content on every event, its immediate moment remap
must likewise be `(M_noevent+eta M_mark).T @ M`, followed by the interval
tilted transition. This does not imply the operator chooses or optimizes a
new boundary; it evaluates the supplied change under the inherited projection.

## Numerical contract and audit

Production assembly consumes the inherited rate/weight tensors and preserves
autograd. Matrix exponentials are a small-state differentiable reference;
no speed, GPU or energy advantage is asserted. Float32/float64 are admitted,
but the fixed audit here uses float64. No probability clipping or stochastic
renormalization repairs an invalid result. Bounds concern finite values and
registered samples, not a uniform roundoff theorem.

Fixed resource limits are 128 states, 4096 parameter batches and a
rate-duration matrix norm product at most 2048. Negative/nonfinite durations,
invalid mass, nonpositive discounts and out-of-domain tilting are refused.
Reset interpolation knots and the upwind sign knot are only piecewise
differentiable. Gradient cases are interior; no high-order or knot derivative
claim is made.

`OPERATOR_PROTOCOL.json` precedes the first development execution. Its cases
cover two positive refractory models, instantaneous self-reset, zero events,
zero noise, time zero, boundary jumps and a same-mean/different-law witness.
Independent checks use SciPy exponentials, quadrature, Frechet derivatives,
implicit resolvent derivatives and two physical-generator secant steps.
Fixed-generator semigroup tests compare split and whole observations for both
complete and killed transitions and the repeated-event composition rule.

Every audit invocation creates a new output directory, freezes exact sources,
keeps raw operator arrays and all failed rows, and refuses to reuse an output
directory. A formal run additionally records the pre-execution commit supplied
by the parent workflow. The audit does not claim this argument alone verifies
remote Git identity. It separately verifies the actual upstream file hash.

Run from the repository root, after installing the recorded dependencies:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_four_stage_flow_20261031.operator_audit --out NEW_DIRECTORY --stage development
```

Formal execution uses `--stage formal --frozen-commit COMMIT`. Internal clocks
start after imports. The parent process meter supplies complete process cost.
