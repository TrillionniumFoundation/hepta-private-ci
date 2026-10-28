# Free-boundary numerical operators

These are research reference operators and an engineering oracle. Their checks
do not establish learning superiority, lower measured hardware energy, or
production readiness. `PROTOCOL.json` fixes numerical checks and tolerances;
`PROFILE.json` specifies the native-owner numerical MDP before its final run.

## 1. The model and the distinct objects

Between events, `dX = mu dt + sigma dW`, with `sigma > 0`. A fixed barrier is
an automatic first-passage contract. A learned barrier is a policy parameter.
An endogenous free boundary additionally solves an optimal stopping or impulse
control problem. Smooth fit is a property of an eligible optimal value, not a
condition one can impose on an arbitrary one-touch probability.

`rate` in the roots and hitting operator is a Laplace rate. A physical independent
zero-recovery killing hazard and a utility discount add inside this transform,
but they have different observable meanings. `hit_readout` consequently returns
both the probability using killing alone and the value using killing+discount.
A silent reset, including restart at the same state, is a different process.
The solution objects expose boundary derivatives, initial-state derivatives,
and whole-value parameter sensitivities. `hit_sensitivities` supplies a slower
scalar oracle from analytic score integrals for drift, noise, rate, horizon,
and initial state. These explicit derivatives can inform a future tensor
adapter; numpy calculations themselves do not preserve a higher-order PyTorch
graph, so no automatic meta-learning claim is made by these reference APIs.

Let `Delta = sqrt(mu^2 + 2 rate sigma^2)`. The backward root is
`kappa = (Delta-mu)/sigma^2`; forward roots are
`gamma_plus = (Delta+mu)/sigma^2` and `gamma_minus = -kappa`.
Rationalization avoids subtracting nearly equal positive numbers. The root
derivatives are `kappa_mu=-kappa/Delta`,
`kappa_sigma=-sigma*kappa^2/Delta`, and `kappa_rate=1/Delta`.
They are singular at zero drift and zero rate; finite-time hitting values can
still be defined there. Zero noise and zero horizon are excluded explicitly.

## 2. First passage, including a moving-boundary reference

For gap `d=b-x>0`, the first-passage density is

    f(t) = d / (sigma sqrt(2 pi t^3))
           * exp(-(d-mu t)^2/(2 sigma^2 t)).

Integrating `exp(-rate*t) f(t)` gives

    q(T) = exp(-kappa*d) Phi((Delta*T-d)/(sigma*sqrt(T)))
         + exp(gamma_plus*d) Phi((-Delta*T-d)/(sigma*sqrt(T))).

`hitting.py` uses log-normal CDFs and a positive Mills-ratio decomposition for
`dq/dx`, avoiding cancellation between derivative terms. This is a first-passage
probability/value, not the terminal Gaussian tail. Below-threshold initial-state
derivatives are one-sided at gap zero; above threshold the event has already
happened and its exterior derivative is zero.

A deterministic linear barrier `b(t)=b0+speed*t` is exact after replacing drift
by `mu-speed`. A general smooth deterministic boundary is handled only as a
numerical reference, solving the Fortet equation

    P(X_t >= b(t)) = integral_0^t f(s)
                    Phi((b(s)+mu*(t-s)-b(t))/(sigma*sqrt(t-s))) ds.

The triangular midpoint method reports negative mass without clipping and must
be checked on successively finer meshes. It does not cover random adaptive or
discontinuous boundaries. Frozen-boundary use for a changing policy is a local
approximation and must be labeled accordingly.

## 3. Affine one-shot stopping and global verification

For payoff `R(x)=x-cost`, positive total rate `r=discount+killing`, no running
reward, and zero recovery, a candidate upper threshold gives

    J_b(x) = (b-cost) exp(-kappa*(b-x)).

Its interior optimum is `b*=cost+1/kappa`. The value is
`exp(kappa*(x-b*))/kappa` below the boundary and `x-cost` above it.
For `y=kappa*(x-b*)`, `exp(y)>=1+y` proves the obstacle inequality.
The continuation generator residual vanishes. In the stopping region,

    (L-r)R = mu-r*(x-cost) <= mu-r/kappa = -sigma^2*kappa/2 < 0.

Together with value matching, smooth fit, admissibility and the usual stopped
martingale argument, these verify the candidate globally. Finite-grid numerical
checks supplement this proof; they do not replace it. Clipped thresholds solve
a restricted policy family and deliberately do not claim unconstrained smooth fit.

Threshold sensitivities are `b_cost=1`, `b_mu=1/(kappa*Delta)`,
`b_sigma=sigma/Delta`, and `b_rate=-1/(kappa^2*Delta)`. Thus increasing a
cancellation hazard can encourage earlier action; a resource price should act
through an explicit cost, not be silently identified with the hazard.

## 4. Repeated reward, reset, and refractory delay

The renewal benchmark has positive discount `rho`, reset `a`, refractory delay
`tref`, and no cancellation or silent resets. Put `delta=exp(-rho*tref)` and
`q=exp(-kappa*(b-a))`. Its fixed-threshold value from reset is

    J_b(a) = q*(b-cost)/(1-delta*q).

The correct action value includes continuation:
`M U(x)=x-cost+delta*U(a)`. Optimality and smooth fit both give

    kappa*(b-cost) = 1-delta*exp(-kappa*(b-a)).

The positive-gap solution is

    b = cost + (1+W0(-delta*exp(-1-kappa*(cost-a))))/kappa.

It exists in the interior exactly when `kappa*(cost-a)>delta-1`.
At this point `U(a)=q/kappa`; the same exponential obstacle proof verifies the
impulse QVI. The implementation provides a separate bracketed solve of the
dimensionless equation, including a stable exponential remainder near the
Lambert-W branch point. It never treats the second Lambert-W branch as an
admissible optimum.

Without refractory delay, `cost<a` creates an unbounded fast-intervention
incentive; `cost=a` gives a nonattained chattering supremum. A positive minimum
gap can bound that policy family. Positive refractory delay can instead put the
optimum at immediate execution after release. These regimes are returned
explicitly; no gradient is asserted across their switching surfaces.

For `H=kappa*(b-cost)-1+delta*q`, `H_b=kappa*(1-delta*q)>0`, so implicit
boundary derivatives use `b_theta=-H_theta/H_b`. They include both the
parameter dependence of kappa and the refractory continuation value. Value
derivatives likewise re-evaluate the whole renewal equation. The condition
index `1/(1-delta*q)` exposes approaching degeneracy.

The spatial value gap `U-MU` is tangent at the optimum. Its spatial derivative
is zero, so dividing by that derivative to infer boundary sensitivities is
invalid. One can instead differentiate the optimality equation above or the
coupled value-matching/smooth-fit system in amplitude and boundary.

## 5. Native-owner finite-state oracle

`finite_horizon.py` exports a separate, fully specified Bermudan MDP. Gaussian
increments are binned onto the declared state grid, with tails saturating the
endpoint bins. Every exported transition row already includes survival
`exp(-killing_rate*dt)`; its missing mass is absorbing killing with zero value.
The Bellman continuation is

    C_n = -running_cost*dt + exp(-rho*dt) P V_(n-1).

Stop pays `x-payoff_cost`; abstain pays zero. At horizon zero only stop and
abstain are available. At positive horizons, nonpositive maximum value selects
abstain, otherwise stop wins an exact tie. The owner must sample these exact
transition rows and must not apply killing a second time. This is the exact
finite-state numerical MDP, not an exact continuous-diffusion free boundary.

## Commands and evidence

From the repository root:

```bash
python -m unittest discover -s experiments/free_boundary_neuron/math/tests -v
python -m experiments.free_boundary_neuron.math.audit --output-dir experiments/free_boundary_neuron/math/results --source-seal SOURCE_SEAL
```

Omitting `--source-seal` creates an explicitly unsealed preflight. Audits retain
timestamped files, actual command/environment/source hashes, failures, numeric
errors, and immutable readout snapshots. `latest_audit.json` is only a pointer.
The pre-seal unit tests cover independent integrals, whole-domain inequalities,
independent optimizers, complete-resolve finite differences, conditioning,
moving-boundary refinement, and independently evaluated Bellman transitions.

## Primary mathematical context

- Peskir (2007), [Principle of Smooth Fit and Diffusions with Angles](https://doi.org/10.1080/17442500601040461).
- Villeneuve (2007), [On Threshold Strategies and the Smooth-Fit Principle for Optimal Stopping Problems](https://doi.org/10.1239/jap/1175267171).
- Evans and Majumdar (2011), [Diffusion with Stochastic Resetting](https://arxiv.org/abs/1102.2704), for why resetting and killing require different renewal semantics.

The affine stopping and renewal derivations above are the explicit assumptions
and verification used by this implementation; they are not claims that those
sources introduce the proposed neural architecture.
