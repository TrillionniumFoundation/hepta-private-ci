# Renewal operator: frozen formal results

## Outcome and identity

**All 2,142 prespecified audit rows passed; no failed rows were discarded or rerun.** This establishes the reported numerical and stochastic checks for the frozen one-dimensional constant-parameter, fixed-reset contract. It does not establish a globally coupled neural process, a task-optimal free boundary, a production Hepta integration, or superiority on a learning task.

- Source/protocol freeze: `103be7196bf5d88a5662e57084d5b8761d9a71a3`.
- Formal run: [`evidence/renewal/formal_01/`](evidence/renewal/formal_01/).
- Machine-readable read-only analysis: [`formal_results_analysis.json`](evidence/renewal/formal_results_analysis.json).
- Original raw cases SHA-256: `cddc275b9d84d2e6160c1901117548ae956cbfb1b9b4652df68727861bafb618`.
- Runtime: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0; float64.
- Process receipt: user CPU 9.033382 s + system CPU 0.127306 s = 9.160688 s; wall 9.173187 s. This includes the audit subprocess startup and final I/O. It is an audit runtime, not a network inference benchmark.
- The frozen source files and contract were not modified for this analysis.

| Audit group | Rows | Result |
|---|---:|---|
| boundary | 4 | All passed |
| convolution | 48 | All passed |
| extreme_cdf | 10 | All passed |
| finite_refractory_grid | 1350 | All passed |
| invalid_domain | 19 | All passed |
| mass_integrals | 24 | All passed |
| monte_carlo | 12 | All passed |
| zero_refractory_diagnostic | 675 | All passed |

These are audit records, including negative-domain and endpoint checks; they are not 2,142 independent trained models. Exact cases, thresholds, and seeds were registered before the formal run in [`protocol.json`](evidence/renewal/formal_01/protocol.json).

## 1. What is exact, and what is numerical evidence?

For the declared contract, the nth firing time has the distribution

\[T_n\overset{d}=\tau_{x+(n-1)r}+(n-1)d,\]

where the waiting times are Brownian first-passage times with the same drift and volatility. The first-passage convolution semigroup yields

\[\Pr(N_H\ge n)=F(H-(n-1)d,x+(n-1)r),\qquad \mathbb E[N_H]=\sum_{n\ge1}\Pr(N_H\ge n).\]

This is a mathematical identity, including defective waiting-time distributions at positive drift. For positive refractory time the count sum has finite support. Float64 evaluation still has rounding error. For zero refractory time the sum is infinite and is evaluated with explicit mathematical remainder bounds; a finite truncation is not relabeled exact. See [`MATHEMATICS.md`](MATHEMATICS.md) for the derivation.

The separate checks have different interpretations:

- **CDF reference comparisons** compare two numerical implementations: the stable kernel and SciPy inverse-Gaussian/Lévy distributions. Their differences are not certified error bounds against exact real arithmetic.
- **Quadrature comparisons** independently integrate waiting-time convolutions and density mass. The integrator tolerances and estimated errors are numerical diagnostics, not formal interval certificates.
- **Gradient comparisons** compare the analytic initial-distance derivative to finite differences. The differences include finite-difference truncation, floating-point cancellation and, for zero refractory time, controlled series truncation. They are not direct measurements of the unknown exact derivative error.
- **Monte Carlo comparisons** use exact conditional waiting-time sampling rather than a time grid. They provide finite-sample statistical consistency, not an identity proof or an all-parameter guarantee.

## 2. Largest observed numerical discrepancies

All maxima below retain their original case identities. `horizon` is H, `reset` is r, and `refractory` is d.

| Check | Maximum absolute discrepancy | Case |
|---|---:|---|
| CDF, registered grids | 5.55111512e-16 | `mu=-0.25, sigma=0.2, x=0.4, horizon=1, reset=0.4, refractory=0.15` |
| CDF, extreme cases | 4.44200232e-13 | `mu=-1, sigma=0.0001, x=1.0, horizon=1.0` |
| Count x-gradient, central difference | 1.76534734e-07 | `mu=1, sigma=0.2, x=0.05, horizon=0.1, reset=0.4, refractory=0.15` |
| Count x-gradient, right difference at x=0 | 1.51930323e-06 | `mu=-0.25, sigma=2, x=0, horizon=3, reset=0.4, refractory=0` |
| Independent two/three-wait convolution | 3.05205861e-12 | `mu=0, sigma=1.5, x=0.8, horizon=1.5, reset=0.8, refractory=0.15, order=3` |
| Active + refractory mass versus one | 3.32178729e-13 | `mu=1, sigma=0.7, x=0.2, horizon=1.5, reset=0.8, refractory=0` |
| Killed density mass versus initial survival | 4.4408921e-16 | `mu=1, sigma=0.7, x=0.2, horizon=1.5, reset=0.8, refractory=0` |
| PMF mass including omitted probability | 2.22044605e-16 | `mu=-0.25, sigma=2, x=1.5, horizon=1, reset=0.8, refractory=0` |
| Tail-adjusted PMF first moment | 7.10542736e-15 | `mu=-0.25, sigma=2, x=0.05, horizon=3, reset=0.4, refractory=0` |

The maximum central-difference case had analytic dx `-3.98111696837305`, finite difference `-3.98111714490779`, step `1e-05`, and its prespecified mixed absolute/relative tolerance was `1.22433509e-06`.

The maximum right-difference case had analytic dx `-2.58588131300343`, finite difference `-2.58588283230665`, step `1e-06`, and its prespecified mixed absolute/relative tolerance was `1.49294066e-05`.

Consequently the formal gradient result should not be summarized as uniform machine precision. The earlier development check near the default parameters had a smaller error, but the formal-domain maxima above are the appropriate reported values.

For the 675 zero-refractory cases, the number of summed count-tail terms ranged from 1 to 72. The largest reported omitted-mean bound was 7.46672332e-13; the largest omitted-absolute-gradient bound was 7.83920821e-13. Each case satisfied its own `1e-13 + 2e-13*abs(sum)` stopping criterion. The maxima can exceed the absolute component alone because the registered tolerance includes the relative component. These bounds control the mathematical series tail, not all float64 roundoff.

## 3. Repeated firing is materially present

The following rows come directly from the formal grid at the default `mu=-0.25, sigma=1, H=1, reset=0.8, refractory=0.15`.

| Initial distance x | P(N >= 1) | P(N >= 2) | P(N >= 3) | E[N] |
|---:|---:|---:|---:|---:|
| 0 | 1.000000000 | 0.464958625 | 0.081962755 | 1.549097226 |
| 0.05 | 0.971020906 | 0.435176779 | 0.072225319 | 1.480158767 |
| 0.4 | 0.755316259 | 0.256405905 | 0.027265283 | 1.039304124 |
| 1.5 | 0.190455009 | 0.021928568 | 0.000449628 | 0.212833583 |
| 3 | 0.005565810 | 0.000094939 | 0.000000119 | 0.005660868 |

At x=0.4, at least two firings occur with probability **0.256405905** and at least three with probability **0.027265283**. A first-event-only feature would give 0.755316259, whereas the expected count is 1.039304124. Thus the implemented repeated-event calculation is not numerically equivalent to simply reusing the first-hit probability. At x=0 the first event is the specified immediate atom; this is why P(N >= 1)=1 there.

The downstream gate `1-exp(-E[N])` is nevertheless a deterministic rate mapping. It is not P(N >= 1), and applying a nonlinear recurrent content update to that gate is not the exact expected hidden state of a sampled reset network. Reinitializing distance from each token preactivation also does not preserve a global live-distance/refractory-age trajectory.

## 4. Initial survival, active mass, and refractory mass

The independent integration domain used H=1.5 and reset=0.8. The table gives its positive-refractory cases, all with d=0.15. Initial survival means no first hit before H. Active mass includes both initial survivors and trajectories that have already fired, recovered and become active again. Initial survival is already included in active mass and must not be added a second time.

| mu | sigma | x | Initial survival | Active mass, all cycles | Refractory mass |
|---:|---:|---:|---:|---:|---:|
| -1 | 0.7 | 0.2 | 0.011128567 | 0.840699130 | 0.159300870 |
| -1 | 0.7 | 0.8 | 0.111502823 | 0.841341606 | 0.158658394 |
| -1 | 1.5 | 0.2 | 0.027686102 | 0.819393998 | 0.180606002 |
| -1 | 1.5 | 0.8 | 0.137188831 | 0.822315636 | 0.177684364 |
| 0 | 0.7 | 0.2 | 0.184459691 | 0.956524714 | 0.043475286 |
| 0 | 0.7 | 0.8 | 0.649251769 | 0.961392028 | 0.038607972 |
| 0 | 1.5 | 0.2 | 0.086691393 | 0.908254814 | 0.091745186 |
| 0 | 1.5 | 0.8 | 0.336774948 | 0.913011085 | 0.086988915 |
| 1 | 0.7 | 0.2 | 0.562866869 | 0.997475146 | 0.002524854 |
| 1 | 0.7 | 0.8 | 0.966072519 | 0.998706390 | 0.001293610 |
| 1 | 1.5 | 0.2 | 0.186048391 | 0.967063206 | 0.032936794 |
| 1 | 1.5 | 0.8 | 0.576274963 | 0.970999480 | 0.029000520 |

All 24 mass cases, including d=0, conserved active plus refractory mass within 3.32178729e-13. For d=0 the refractory mass is zero. The integrals are independent quadrature evaluations of density and survival contributions; their use of accumulated firing distance relies on the renewal identity, which is separately checked by the direct two/three-wait convolutions. This is not an independent high-dimensional coupled-cell simulator.

## 5. Monte Carlo: all fixed seeds and outcomes

Every row used 50,000 trajectories, x=0.4, H=1.5 and reset=0.8. All 600,000 raw counts were retained. The saved NPZ counts were read back for this analysis: all sample counts and reported sample means agree. PCG64 seeds and raw-file SHA-256 hashes are recorded in the machine-readable analysis.

| Seed | mu | sigma | d | Analytic E[N] | Sample mean | Sample SE | Absolute mean difference / SE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026103100 | -1 | 0.7 | 0 | 2.173014417 | 2.16234 | 0.00446248 | 2.392038 |
| 2026103101 | -1 | 0.7 | 0.15 | 1.868925839 | 1.86334 | 0.00353711 | 1.579211 |
| 2026103102 | -1 | 1.5 | 0 | 2.962635227 | 2.95872 | 0.00800890 | 0.488860 |
| 2026103103 | -1 | 1.5 | 0.15 | 2.401989869 | 2.40374 | 0.00569288 | 0.307424 |
| 2026103104 | 0 | 0.7 | 0 | 0.823182656 | 0.82606 | 0.00334800 | 0.859421 |
| 2026103105 | 0 | 0.7 | 0.15 | 0.790103730 | 0.79052 | 0.00310666 | 0.133992 |
| 2026103106 | 0 | 1.5 | 0 | 1.817701006 | 1.81408 | 0.00642986 | 0.563155 |
| 2026103107 | 0 | 1.5 | 0.15 | 1.622928824 | 1.62212 | 0.00524052 | 0.154340 |
| 2026103108 | 1 | 0.7 | 0 | 0.194932905 | 0.19486 | 0.00183354 | 0.039762 |
| 2026103109 | 1 | 0.7 | 0.15 | 0.194452738 | 0.19496 | 0.00183081 | 0.277069 |
| 2026103110 | 1 | 1.5 | 0 | 1.058436853 | 1.06312 | 0.00471771 | 0.992674 |
| 2026103111 | 1 | 1.5 | 0.15 | 1.011835512 | 1.00736 | 0.00429233 | 1.042677 |

The largest mean difference was 0.010674417, or 2.392038 empirical standard errors, at seed 2026103100. All registered mean and individual PMF-bin checks passed. The mean threshold was six sample standard errors plus 3/N, and each bin used `6*sqrt(p*(1-p)/N)+3/N`. These thresholds were fixed before the run; they are consistency diagnostics, not a claimed simultaneous confidence construction. The 12 cases do not prove correctness over untested parameter regimes.

## 6. Positive drift retains the probability of never hitting

For mu>0 the unconditional first-passage law is defective:

\[\Pr(\tau_x=\infty)=1-e^{-2\mu x/\sigma^2}>0.\]

The finite-horizon CDF is not normalized by the eventual-hit probability. The Monte Carlo sampler first samples the conditional inverse-Gaussian time and explicitly assigns infinity to the escape branch using the appropriate independent Bernoulli draw. Reset periods retain the corresponding defect for distance r.

| mu | sigma | Initial x | P(initial hit never occurs) | Reset r | P(next post-reset hit never occurs) |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.7 | 0.4 | 0.804589550 | 0.8 | 0.961814756 |
| 1 | 1.5 | 0.4 | 0.299215989 | 0.8 | 0.508901770 |

The displayed never-hit probabilities are analytic consequences of the contract, not measured infinite-time frequencies. The retained finite-horizon count arrays cannot distinguish a wait lasting beyond H from a wait equal to infinity. Their zero-count mass includes both. The full sampler source and fixed seeds are retained, but per-wait infinity flags were not separately logged.

For completeness, with `p0=exp(-2*mu*x/sigma^2)` and `pr=exp(-2*mu*r/sigma^2)`, positive drift gives the infinite-horizon identities `P(N_infinity>=n)=p0*pr^(n-1)` and `E[N_infinity]=p0/(1-pr)`. These identities explain why discarding the defect would change both count probabilities and long-horizon behavior. They were not asserted to be a separate infinite-horizon empirical validation.

## 7. Endpoints, horizon smoothness, and remaining scope

All 19 invalid-domain checks raised the expected error. At x=0,H=0 the contract counts one immediate event and reports an undefined spatial derivative as NaN. At x>0,H=0 it counts zero. The spatial derivative at x=0,H>0 is a right derivative, audited by a one-sided formula.

For positive sigma, positive reset and x>0, the mathematical expected count is smooth across H=k*d. Each newly possible repeated-firing term starts at a strictly positive distance, and its first-passage CDF has a flat zero-time extension. The time derivative is the sum of the corresponding hitting-time densities. The finite loop length changes, but the mathematical function has no resulting kink. Only the x derivative is implemented/trained in this study. The separate [`horizon_review.json`](evidence/renewal/horizon_review.json) records the derivation and the read-only candidate-freeze review.

The supported conclusion is that the declared local repeated-hit/reset/refractory operator passes its registered mathematical and numerical audit, including positive-drift escape and multiple events. It leaves content learning, control usefulness, continuous feedback self-consistency, learned time/noise parameters, hardware efficiency, and comparison with SNN/Transformer architectures to their separately frozen experiments. No frozen source was changed to obtain or summarize these results.
