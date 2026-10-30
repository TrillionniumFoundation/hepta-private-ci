# P0 research: multi-stage asynchronous Erlang refractory QVI

**DRAFT / DENY_ALL / NOT PRODUCTION.** Additive continuation of #4391 at exact parent head `2a768b8e249ff1e266cd666f62bcfda7e6ac5626`. This is **not** the He–Xiong financial credit fixed point, a certified continuum neural differential equation, or a native spiking runtime. No original formulas, immutable benchmark results, Rust control owner, authority, checkpoints, training, or release path are modified.

## Mathematical contract and deterministic-refractory approximation

Each neuron has finite active grid positions plus `k_i` sequential refractory stages, numbered 0 to `k_i-1`. A firing neuron immediately earns `x_i - cost_i` and enters final stage `k_i-1`. Each stage advances at exponential rate `lambda_i = k_i / tau_i`; stage zero recovers to a convex-grid-interpolated active reset. The other neuron **continues evolving and can independently fire/recover during all these stages**. WAIT uses the same blocked-outward-jump spatial finite CTMC on active states, with positive common discount. No refractory cell can fire again until its recovery.

The refractory duration is Erlang(`k_i`, rate `k_i/tau_i`), giving:

```text
E[T_i]      = tau_i
Var(T_i)    = tau_i^2 / k_i
E[e^-rho T] = (1 + rho*tau_i/k_i)^(-k_i) -> e^(-rho*tau_i)
```

The `k_i=1` case is exactly the earlier exponential-refractory model in #4391. Increasing phases at fixed mean reduces delay variance and approximates a deterministic **per-cell** refractory interval. This is a *finite-state research approximation*, not a proof of convergence of a multi-cell continuum impulse-control process with fixed delays. In particular, it does not claim a valid differentiation rule for a trainable spiking layer.

The finite stationary QVI remains `max{(Q-rho I)V, eligible FIRE1 residual, eligible FIRE2 residual}=0`. WAIT has phase-progression transitions; FIRE takes zero time and adds no fake elapsed-time discount. A refractory neuron cannot fire. At most two immediate fires occur before time-positive WAIT/recovery, which prevents zero-time cycles. The state count is `(n1+k1)(n2+k2)`: still a tensor product and absolutely not a scalable 4096-Cell runtime.

## Reproduce actual local CPU evidence

Python 3.13.5; NumPy 2.3.5; SciPy 1.17.0.

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_erlang_async_qvi
python -m unittest -v experiments.hcsn_hx_unified_v3.test_coupled_qvi experiments.hcsn_hx_unified_v3.test_asynchronous_qvi experiments.hcsn_hx_unified_v3.test_erlang_async_qvi
```

**34/34 combined tests passed on the byte-identical core and test sources** (12 original #4388 + 12 #4391 + 10 new). This is local numerical evidence, not GitHub Actions or production admission.

Key independent checks:

- `k1=k2=1`: full value arrays and policy arrays are **bit-identical** to #4391's two-cell exponential CTMC reference, not merely approximately close.
- Three configurations of Howard sparse policy evaluation versus Jacobi Bellman iteration (different algorithms on the same finite grid): sup-norm error <2e-8. Independent scalar-loop QVI residuals, including each refractory phase and both eligible fire branches, below 3e-8.
- Analytical Erlang Laplace transform approaches the fixed-delay discount `exp(-rho*tau)` monotonically from above in the checked configuration.
- With Cell 2 provably inert, an **independently coded scalar fixed-delay** finite-grid obstacle oracle provides a targeted deterministic-delay limit. For active-grid phases `k1=1,2,4,8,16,32` and Cell 2 `k2=1`, the maximum error versus that independent deterministic reference is `0.0002998486, 0.0001529340, 0.0000772454, 0.0000388207, 0.0000194603, 0.0000097427`. This checks one parameter set and finite grid, **not all parameters or a two-cell deterministic-delay theorem**.
- A separate phase-by-phase Laplace factor identity checks all 6 refractory stages when the other cell is inert.
- Other-cell firing is exercised throughout the first cell's refractory stages; swapping Cell labels and phase counts leaves value unchanged.
- Independent continuous-time Gillespie simulation verifies 3 fixed-policy states with 800 trajectories each, within 6 standard errors plus 0.04.
- 20 seeded parameter cases check residuals; zero/invalid phase count, out-of-range budget, lost FP64 discount, invalid tolerance and iteration-budget exhaustion fail closed.

## OPEN blockers and nonclaims

1. **Full original HX financial fixed-point admissibility, positive equity, independent full-domain certification, derivative/smooth-boundary/interval errors, and low-precision singular limits** remain unclosed.
2. The limit to exactly **deterministic, independently scheduled multi-cell** refractory delays still lacks a verified semi-Markov oracle and continuum convergence bound. The 1D limit above is deliberately narrower.
3. No proof Call/Risk/Margin beats matched ordinary gates or improves long-memory Selective Copy/MQAR/overwrite/irregular-time tasks; previous negative ablations remain.
4. No paired text/image/audio/video pretrained encoder training, no native Rust/GPU production kernel, and no measured 64/256/1024/4096 Cell throughput/p95/p99/RSS/energy/crash recovery.
5. No P5 equal-budget hybrid-backbone superiority and no grounds for production integration.

**Keep all P0–P5 final admission gates DENY_ALL.** Local tests validate only the precisely specified finite-state approximation.