# Same-law continuous first-hit reference

This read-only diagnostic separates agreement between the two finite CTMC
solvers from agreement with the continuous diffusion. It advances no finite
generator, evaluates no matrix exponential, changes no admission criterion,
and leaves the original bitwise gate **RED**.

## Initial and release laws

The authentic export is a vector of **node masses**, not density samples.
`hcsn_initial_law/migration.py` constructs a conservative linear nodal lift;
its SHA-256 matches the export metadata. The reference uses every exported
binary FP64 coordinate and weight exactly, without normalization, reconstruction
of the pre-export law, or modification of the signed content channels.

Initial probability, including the permanent upper coordinate, sums to
0.9693442699581465; remaining probability is already in refractory packets.
The initial lower atom is zero. The upper atom is permanent active mass and
contributes no lower hit. The actual upper coordinate is 8.

On this interval there is one original constant release source, starting at
0 and ending at 1/40. It is included with the original FP64 channel rates and
the actual two-node reset distribution: nodes 0.31114065825695336 and
0.3189905701887992, weights 0.7444253708107298 and 0.25557462918927015.
These injection coefficients are checked byte-for-byte against the executed
dense packet generator. The separate exact-reset-point sensitivity in the
raw result does not replace this law. Delay 1/5 exceeds the horizon 1/1000,
so no newly emitted hit returns during the interval.

## Analytic computation

For `dX = mu dt + sigma dW`, first lower hit `tau`, and discount `rho`, write
`chi = sqrt(mu^2 + 2 rho sigma^2)` and

```
A_rho = exp((-mu+chi)x/sigma^2) Phi((-x-chi T)/(sigma sqrt(T)))
B_rho = exp((-mu-chi)x/sigma^2) Phi((-x+chi T)/(sigma sqrt(T)))
G_rho(T,x) = E[exp(-rho tau); tau <= T] = A_rho + B_rho
F(T,x) = G_0(T,x)
```

Sum these kernels against the exact initial node masses. For each constant
release source, integrate its reset-node mixture using

```
M_1(T,x) = E[tau; tau <= T] = x/abs(mu) (B_0-A_0)
J_F(T,x) = integral_0^T F(s,x) ds = T F(T,x)-M_1(T,x)
J_G(T,x) = integral_0^T exp(-rho u) G_rho(T-u,x) du
         = (G_rho(T,x)-exp(-rho T) F(T,x))/rho.
```

The discount in `J_G` is global-time discount, including the release time.
Here the actual drift is nonzero and discount positive. The computation uses
the original FP64 parameters and the binary FP64 duration used by the finite
solver. The half-line result differs from a diffusion permanently absorbed
at the upper coordinate by at most the initial interior total variation plus
released total variation, times `F(T,8)`. This follows by the strong Markov
property after reaching 8; the probability-channel bound is below
1.198e-113448 for both reported quantities.

## Actual result

All five channels have the same leading relative error because their near-
boundary initial profiles are proportional. The table gives the continuous
reference and **dense minus continuous** signed error. Sparse errors differ
from dense errors only at the finite-solver roundoff scale; all are in the
raw result.

| Channel | Continuous hit | Dense hit error | Continuous discounted hit | Dense discounted error |
|---|---:|---:|---:|---:|
| Probability | 0.005271584405494924 | -1.334470620649e-7 | 0.005271319242413837 | -1.333763435826e-7 |
| Content 1 | -8.688405113966667e-5 | 2.199418708501e-9 | -8.687968083257766e-5 | 2.198253155954e-9 |
| Content 2 | 1.082397733668469e-4 | -2.740026269791e-9 | 1.082343288572660e-4 | -2.738574229542e-9 |
| Content 3 | -2.705742058536243e-4 | 6.849427053481e-9 | -2.705605958486299e-4 | 6.845797291237e-9 |
| Content 4 | -4.853586405225965e-4 | 1.228656882726e-8 | -4.853342267633443e-4 | 1.228005772445e-8 |

The probability-channel relative errors are **25.3144 ppm** for hit and
**25.3023 ppm** for discounted hit (approximately 0.00253144% and 0.00253023%).
Both finite solvers underestimate these quantities. Their mutual maximum
coordinate difference of about 9.09e-16 therefore does not measure continuum
accuracy. This is a spatial-generator discretization error for this fixed
nodal law, interval, and parameter set; it is not a result about the unprojected
original density or a global convergence guarantee.

The probability release-source contribution is about 4.93e-182, included
despite being negligible here. Analytic sums at 45 and 80 digits differ by
less than 5.81e-49 in the probability quantities. Independent, endpoint-scaled
quadrature of both source convolutions at both reset nodes has maximum relative
disagreement 1.775e-72. Scaling avoids an absolute-tolerance false zero for these
tiny integrals. Runtime was 1.8104 wall seconds / 1.7776 CPU seconds.

`attempt001.json` preserves all values, individual errors, source hashes,
precision comparisons, and quadrature results. Reproduce from the repository
root, with mpmath 1.3.0, using a new output path:

```bash
python -m qualification.hcsn_currentstate_n256_warm1_sparse.continuous_reference /tmp/continuous-reference-new.json
```

No continuum gradient, longer-time, varying-parameter, complete-roster, or
downstream-task qualification is inferred from this single diagnostic.
