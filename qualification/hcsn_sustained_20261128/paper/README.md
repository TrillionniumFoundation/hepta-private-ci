# Independent Table II and renewal cross-check

The first target is an external numerical benchmark. He and Xiong's Table II, Panel A, gives the one-year BB credit spreads at three liquidity shock intensities. Using the rounded inputs in Table I reproduces all three quoted values within 0.36 basis point. The code integrates the equity equation independently of the published boundary ratio and Appendix A7 expression. It also covers zero liquidity premium, where some closed-form implementations contain a removable singularity. [He and Xiong, The Journal of Finance 67 (2012), 391–430, Eqs. 8–12 and Tables I–II](https://www.princeton.edu/~wxiong/papers/rollover.pdf)

| Shock intensity | Boundary | Equity at V=100 | First-hit probability, one year | Calculated spread (bp) | Table II (bp) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 65.048403 | 43.113735 | 0.046475 | 169.9618 | — |
| 1 | 67.441515 | 36.846089 | 0.067093 | 330.3517 | 330 |
| 2 | 69.818055 | 31.048507 | 0.093501 | 499.7787 | 499.6 |
| 4 | 74.521831 | 20.950481 | 0.165760 | 853.2149 | 853.0 |

The external targets are the three spreads. Boundaries, first-hit probabilities and equity levels in the table are outputs of this reference. The one-year hit law is under the paper's specified process. Substituting empirical firing rates would require a physical process and observations.

## Financial equation and the two channel slopes

Write x = log(V/b), mu = r – delta – sigma²/2 and L = mu d/dx + (sigma²/2) d²/dx². At fixed x the Eq. 8 bond value D(x;b) is affine in b. The source of equity is S(x;b) = delta b exp(x) – (1 – tax) C + D(x;b) – p. Let eta be the positive root of sigma² eta²/2 + mu eta – r = 0. In the reported calibration eta > 1.

With E(0) = E′(0) = 0, integrate (r – L) E = S against exp(–eta x) on the half-line. The remaining integral of S must vanish because E grows at most linearly in V. This gives a scalar linear equation for b. The coefficient of b is delta/(eta – 1) + (alpha/m) times the positive discounted-hit integral. For the stated contract it is strictly positive. The program evaluates the two integrals by adaptive quadrature, integrates the equity initial-value equation to V = 100, and inverts Eq. 10 for yield. This numerical procedure checks the published calibration. Extension to a different contract would require verifying the obstacle inequalities over its continuation and stopping regions.

In the absorbed region equity is zero and first-hit probability is one. Value matching and smooth pasting give zero right equity slope. Eq. 11 gives right equity curvature –2 S(0;b)/sigma² = 927.44652 at the baseline. The one-year hit probability instead has right log-margin slope approximately –4.14012 and left slope zero. These distinctions matter when backpropagating through a neuron with a clamped absorbing region.

## Independent scalar renewal check

The separate physical model uses a constant log-margin drift and volatility. It starts at positive x₀ and, after each hit, waits d > 0 before restarting independently from positive xᵣ. Time, reset and boundary use the same units throughout. Under those assumptions the first-hit Laplace transform is exponential in start distance, so active first-hit times add in distance. With F the one-cycle first-hit CDF, the probability of at least j+1 hits by T equals F(x₀+j xᵣ,T–j d). It vanishes at nonpositive remaining duration. Summing these probabilities gives the finite-horizon expected count. The derivative check covers initial distance, reset distance, refractory delay, drift, volatility and observation time.

For positive drift define p(x) = exp(–2 mu x/sigma²). Lifetime mean count equals p(x₀)/(1–p(xᵣ)), with terminal escape almost surely. Zero drift hits almost surely but has infinite mean waiting time. Negative drift gives a limiting rate of 1/(d+xᵣ/|mu|). The latter is a physical drift assumption. The financial discounting equation retains its own pricing-law drift.

| Horizon | Exact mean count | Simulated mean | Monte Carlo standard error | Exact probability of at least two hits |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.398440 | 0.397273 | 0.001111 | 0.057295 |
| 5 | 1.193877 | 1.190073 | 0.002419 | 0.329258 |
| 10 | 1.684325 | 1.682293 | 0.003264 | 0.435055 |

The simulation uses 300,000 independent paths, seed 20261128, x₀ = xᵣ = 0.2, d = 0.05, mu = 0.03355, and sigma = 0.23. It draws an eventual-hit indicator and a conditional inverse-Gaussian time per active cycle. At zero drift the simulation uses a Lévy waiting time. The positive-drift calibration gives 3.462996 expected lifetime hits and zero limiting rate.

## Repository provenance and reproduction

Independent checks here exercise established research interfaces. The repository already contains the financial Green resolvent, shifted first-passage renewal sum with gradients, and a stronger marked, full-distribution transport with a two-neuron boundary path. Its tonic-current audit explains why a fixed relative reset and the financial positive drift fail to sustain an unbounded stationary firing rate. This reference adds selected published spreads as external targets and independent renewal draws and finite-difference comparisons. The aggregate count model has no learned inter-layer connections, changing coefficients or population correlations. [Financial oracle #4377](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4377) · [Finite renewal #5363](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5363) · [Marked transport #7032](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7032) · [Tonic-current analysis](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fff9a90720deaf848ad30991158f2b6180e61f4f/qualification/hcsn_frontier_20261127/continuum/TONIC.md)

From this directory, run the two commands below. The published receipt uses NumPy 2.3.5 and SciPy 1.17.0 on CPU.

```bash
python -B -m unittest discover -v
python -B hx_reference.py
```

[Reference implementation](hx_reference.py) · [Ten regression tests](test_hx_reference.py) · [Machine-readable results](results.json)
