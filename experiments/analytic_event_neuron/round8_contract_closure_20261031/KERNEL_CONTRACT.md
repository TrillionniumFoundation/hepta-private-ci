# R8 Brownian event-kernel contract

## What changed

`kernels.py` introduces `r8-brownian-images-v1`. It preserves the R7-shaped
finite state interface, but the active process is explicitly

\[
dX=\mu\,dt+\sigma\,dW,\qquad -b<X<b.
\]

The input drive is constant during one call. All three comparison modes use
this process, with zero leak. The old `raw_leak` scalar remains loadable for
parameter-copy experiments, is frozen, and has no physical effect. The new
kernel is **not an exact killed OU transition**, and its results cannot repair
the old R7 OU accuracy claims retroactively.

The interface is `BrownianEventDynamics(mode, n_grid=15, image_terms=12,
reference_dt=1.0)`, with the R7 methods `initial`, `transition_matrix`,
`forward`, `physical_parameters`, and `state_features`. `transition_matrix`
returns `[batch,N+2,N+2]` probabilities and `[batch,N+2,2]` event rewards.
State order is active nodes, positive refractory state, negative refractory
state. Event order is positive, negative. Kernels and checkpoints must carry
the new version; the R7 native finite-law implementation is a different
deployment contract.

## Three event contracts

| Mode | One-interval law | Remaining approximation |
| --- | --- | --- |
| `continuous` | Integrate the unbounded Gaussian transition, folding its two tails into edge bins; no events | Projection is bounded and loses tail location; it is only a finite-grid comparator |
| `clocked` | Integrate Gaussian mass inside each voltage bin; the two endpoint tails enter their refractory states | First crossing and subsequent return before tick end do not fire; repeated representative-state projection remains |
| `first_passage` | Integrate the killed Brownian transition density and each boundary's first-exit flux | Analytic image series is truncated; repeated representative-state projection remains |

For the clocked model, the surviving distribution is the **truncated**
Gaussian distribution. The unconditional mean is not `mean * survival`.
The event branch is an atom in its corresponding augmented refractory state;
the stochastic reset distribution is applied on release.

The Brownian image density uses width `L=2b`, shifted coordinates `u=x+b`,
`v=y+b`, and `s²=σ²t`:

\[
p^{\rm kill}_t(u,v)=e^{\mu(v-u)/\sigma^2-\mu^2t/(2\sigma^2)}
\sum_{k\in\mathbb Z}\{\phi_{s^2}(v-u+2kL)-\phi_{s^2}(v+u+2kL)\}.
\]

Completing the square makes every bin integral a weighted Gaussian interval.
Boundary flux integrates to a signed image sum of single-boundary
first-hitting CDFs. The implementation uses log-CDF differences and log-sum-exp
to combine exponential tilting with tiny tails. It does not add a probability
floor or renormalize rows. Only negative cancellation within `2e-11` is
clipped; larger negativity, nonfinite values, or row defects above `2e-10`
raise an error. The tested image-order comparison is a diagnostic, not an
analytic uniform error certificate over arbitrary parameters and horizons.

## Unbounded analytic control and Gaussian/probit identity

`gaussian_propagate(mean, variance, drift, diffusion, dt, leak=0)` carries an
unbounded Gaussian mean and variance with no voltage bins. Nonnegative leak
also supports the exact affine OU Gaussian transition; the small-leak formula
preserves derivatives at zero. Neither endpoint closure supplies a first-hit
or reset law. A nonlinear readout still requires integration or sampling;
evaluating the readout at the mean does not integrate its loss.

`gaussian_events` returns `(put, idle, call)` and handles zero-variance atoms.
`probit_events` writes the same positive-variance partition explicitly as
probit scores. Their equality is a mathematical control, not an independent
architecture win. At the same strike, `put + call = 1` with inequalities
`X <= K` and `X > K`; cash-or-nothing option prices would sum to the discount
factor. Opposite thresholds leave an idle channel and do not satisfy binary
same-strike complementarity. The two first-exit sides also leave survival mass.

## Recovery and causal timing

The learned R7-shaped reference probability maps to a physical rate
`lambda = -log(1-q_ref)/reference_dt`. A call of duration `dt` uses
`q(dt)=1-exp(-lambda*dt)`. The unreleased fraction of an original refractory
cohort after physical duration `T` is therefore `exp(-lambda*T)` on its
observation grid.

An event freezes its path for the remainder of its tick. Newly emitted mass
cannot release in the same tick. Old refractory mass releases only at the end
of a later tick and starts evolving on the following call. Reset jitter is
the inherited explicitly stochastic Gaussian reset, not a deterministic reset.
This is still at most one event per path per tick. Endpoint release quantizes
the observed release delay: its mean is `dt/q(dt)`, not exactly `1/lambda`.
Changing `dt` changes that rounding and the event observation contract. A
cohort check does not establish a fully continuous regenerative process.

## Independent evidence

The current CPU audit uses Torch 2.8.0, NumPy 2.3.5 and SciPy 1.17.0; the
machine-readable runtime record is authoritative. It is not the R7 runtime.
`evidence/kernel_audit.json` records source hashes, cases, gradients and all
diagnostic gates. These checks are development validation, not preregistered
task-performance claims.

| Check | Measured result |
| --- | ---: |
| Killed-bin probabilities vs SciPy quadrature of an independent sine-series density | maximum absolute error `4.03e-16` |
| First-exit probabilities vs independent spectral boundary flux | maximum absolute error `2.23e-16` |
| Low-noise corner, drift 1, sigma .05, b 1, time .8 | `4.3218260067306315e-6`; independent one-sided error `5.93e-21`, competing lower correction bounded by `exp(-800)` |
| Normal tails at -8, -9, -10, -20, -30 vs SciPy | maximum relative error `1.75e-13` |
| Gaussian/probit and same-strike complement probes | exact equality in the checked FP64 cases |
| Three-step complete-path sums, 343 leaves per mode | maximum expectation difference `5.56e-17` |
| Full nonlinear path-loss gradients, including reset, release, drive and readout | maximum central-difference error `5.12e-10` |

The path-loss audit augments the state with event count and sums the nonlinear
loss over complete paths. Its loss-of-mean-feature substitutes differ by
`0.000355`, `0.037019`, and `0.039694` in continuous, clocked, and first-passage
fixtures. Those differences demonstrate why the surrogate cannot certify the
sampled process's expected loss.

Spatial and temporal sensitivity remains visible. With four subintervals,
the first-exit error falls from `5.60e-4` at grid 15 to `4.24e-5` at grid 127.
At fixed grid 31, using 16 subintervals increases the error to `1.70e-3`;
smaller time steps alone do not remove projection error. This subinterval
probe keeps the boundaries absorbing and excludes reset/recovery, so it does
not confuse discretization with a changed recovery law.

The initial development audit found a maximum `6.11e-9` full-path mismatch caused by
an integer event-count tensor implicitly promoting arithmetic to FP32 in the
audit payoff. It was fixed with an explicit FP64 payoff tensor. The initial
failure is retained as `evidence/kernel_initial_audit.json`; the kernel law
was not changed to make that comparison pass.

Run from the repository root using the supplied Python environment:

```sh
python -B -m unittest experiments.analytic_event_neuron.round8_contract_closure_20261031.test_kernels -v
python -B -m experiments.analytic_event_neuron.round8_contract_closure_20261031.kernel_audit --output experiments/analytic_event_neuron/round8_contract_closure_20261031/evidence/kernel_audit.json
```
