# R13 completed nonzero-risk two-weight exact-moment certificate

This round actually executed a deterministic, exact-rational certificate for a **two-weight forward Stem** with nonlinear input-state dynamics, two nonzero NDU risk profiles, a branch-induced preference-state transition, and a one-step entropic BSDE. It is not neural-network training at scale.

## Exact certificate

| Item | Verified result |
| --- | --- |
| Candidate forward coefficient \(a\) | 1.359072658021 (exact rational) |
| Candidate forward coefficient \(b\) | -1.400028626085 (exact rational) |
| Unique global optimum | Existence and uniqueness follow from Hessian \(\succeq(9/35)I\) |
| Rigorous Euclidean parameter distance | < 2.954176e-13 |
| Rigorous population cost suboptimality | < 1.122063e-26 |
| Restricted family \(b=0\) excess | > 0.2520103 |
| Uniform complex-Taylor argument bound | 9428999501/39062500000 < 1/2 |
| Error control | Exact 64-degree rational tanh Taylor plus Cauchy tail |
| Preference transition | \(P_1=P_0\oplus\mathbf1\{\varepsilon=+1\}\) |

All inequality directions and exact fractions are retained in `CERTIFICATE.json`. No floating-point optimizer output is used as a proof premise. The proposed rational candidate was selected after preliminary numerical scouting; the mathematical certification is independently checkable for those fixed rational numbers.

## Executed float-only controls (not part of the certificate)

| Finite integration used to fit two weights | Coefficients approximately | High-order continuous-population cost gap |
| --- | --- | ---: |
| CC5 | 1.335172783754, -1.500194893590 | 0.001475426875 |
| GL5 | 1.359101843616, -1.399977551727 | 5.17698e-10 |
| GL17 | 1.359072658021, -1.400028626085 | approximately zero at FP64 precision |

These are independently computed with SciPy nonlinear root finding and NumPy quadrature, not certified global values of each finite-integration target. The actual entropic population objective of the rational candidate is about 0.1117041520362. The Bernoulli martingale identity is independently checked to 2.78e-17 in floating arithmetic.

## Verification and scope

15/15 targeted stdlib rational-geometry/gradient/convexity/negative-input tests passed. The exact solver and tests are verified against their remote Git blob identities; independent NumPy/SciPy diagnostics run separately. Historical R12, R11 and R10 source, weights and classifications are unchanged. No native model admission, main merge, FBSDE viscosity proof, nonconvex global-network theorem, LLM training or project-cloud execution is claimed.

This is a meaningful extension of R12's one-weight, zero-risk case: the optimal parameters are nontrivial in two dimensions; a second weight is mathematically necessary within the stated family; and nonzero NDU risk genuinely changes the population optimum. The logical next step is a higher-dimensional, genuinely coupled multi-step forward/backward setting in which the parametric strong-convexity shortcut no longer applies, with independent solution verification.
