# New arithmetic diagnosis of Hepta numerical risks

This is a new, independent diagnostic. It is **not** a recreation of the lost
Hepta source, trained checkpoints, dataset, or previous numerical runs. The
original report was read from Library item
`libfile_78e322835cfc819199a7e4293e3c9132`.

No training or test-set scoring was performed. The script uses NumPy and
Python's 80-digit Decimal arithmetic. Both precisions receive the same exactly
represented float32 inputs, so input rounding is separated from arithmetic.
The protocol and source hash were written before the numerical evaluation.

## 1. Two cancellation mechanisms deserve direct source inspection

For the semilinear flow y' = L y + N(y), a second-order ETD update uses

    z = h L
    p = exp(z) y + h phi_1(z) N(y)
    y_next = p + h phi_2(z) [N(p) - N(y)]

where phi_1(z) = (exp(z)-1)/z and
phi_2(z) = (exp(z)-1-z)/z^2. Their removable limits are 1 and 1/2;
their first derivatives at zero are 1/2 and 1/6.

Direct subtraction is ill-conditioned near zero. Replacing exp(z)-1 with
expm1(z) substantially improves values, but does not by itself ensure a stable
derivative for phi_2. Small arguments should use the same polynomial for values
and autodifferentiation:

    phi_k(z) = sum_{j=0}^J z^j / (j+k)!

The demonstration uses degree 18 and |z| <= 0.25. An actual tensor implementation
must keep both branches of `where` finite: replace the unused quotient's small
denominator with a safe nonzero argument, and keep the unused polynomial's
argument bounded. A late mask over NaN/Inf does not establish a safe backward.

The Call feature has an additional, independent cancellation. In the continuation
region x > 0, its expression in the retained report is

    D = kappa*exp(x) + exp(-kappa*x)
    a = [D - (1+kappa)] / D.

Smooth pasting makes the numerator second order at the boundary:

    a(x,kappa) = kappa*x^2/2 + O(x^3).

The algebraically identical numerator

    N = x^2 [kappa*phi_2(x) + kappa^2*phi_2(-kappa*x)]

preserves this small positive quantity and its parameter sensitivity. Then
`a=N/D`. In a production implementation this expression can be restricted to a
bounded near-boundary region; large positive x also needs overflow-safe scaling.
The present diagnostic does not claim to implement every large-x case.

For x <= 0, the stopped Call channel remains zero. At x=0, value and x derivative
are zero on both sides. The definition of the Put exercise branch, parameter
gradients, boundary translation, and any clamps must be checked against the
actual cell contract before modifying the original implementation.

## 2. Executed results

Run:

```bash
python3 arithmetic_diagnostic.py --output a_new_empty_directory
```

The completed `run001` contains 144 phi records, 96 Call records and 54 affine
flow records, and took 0.055 process CPU seconds on this environment.

At represented z approximately -1e-4, float32 phi_2 gives:

| Formula | Value relative error | z-derivative relative error |
| --- | ---: | ---: |
| Direct exponential subtraction | 4.3194 | 259,181 |
| expm1 numerator | 0.0002500 | 27.9611 |
| Series at small arguments | 1.35e-8 | 4.98e-8 |

Across the entire declared phi grid, the stable float32 maximum relative errors
were 4.52e-8 for values and 3.11e-7 for derivatives. Float64 derivative error was
at most 4.02e-16 against Decimal, rounded to float64 for reporting.

At kappa=1 and represented x approximately 1e-4, the direct Call formula gives
zero instead of approximately 5e-9; its kappa derivative also becomes zero.
The series-based form has value relative error 4.03e-8. Across all declared Call
cases its float32 value, x derivative, and kappa derivative relative errors stay
below 2.68e-7.

The affine ODE test has an exact solution:

    y' = -lambda*y + (alpha*y+c)
    y(T) = exp((alpha-lambda)T)*y0 + c*T*phi_1((alpha-lambda)T)

For T=1, lambda=0.001, alpha=0.4, c=0.1, y0=0.2 (each represented first as
float32), stable float64 ETD2 exhibits approximately second-order convergence:

| Steps | State relative error | lambda-gradient relative error |
| --- | ---: | ---: |
| 4 | 9.855e-4 | 9.500e-4 |
| 16 | 6.516e-5 | 6.458e-5 |
| 64 | 4.130e-6 | 4.122e-6 |
| 256 | 2.590e-7 | 2.589e-7 |
| 1024 | 1.620e-8 | 1.621e-8 |

In float32, even the stable method reaches a rounding-error floor: its gradient
relative error decreases to 4.04e-6 at 64 steps, then becomes 1.10e-5 at 1024.
The expm1-only method has substantially larger, nonmonotone gradient errors in
the same experiment. This demonstrates why finer steps alone are not a valid
precision acceptance rule.

Forward sensitivity of the stable **discrete** map was independently checked by
central finite differences at 64 steps; the best absolute difference was
1.44e-12. The exact ODE solution provides a separate continuous-flow reference.

These numbers describe NumPy scalar evaluation of analytic derivative formulas,
not PyTorch's exact autograd operation ordering. A PyTorch kernel implementation
must be checked directly: `expm1` backward, quotient decomposition, exp kernels,
fusion and saved intermediates can have different floating-point behavior.

## 3. Minimum next experiment once original bytes are available

The following is a proposed protocol, not an executed old-checkpoint test.

1. Verify source, weights, inputs, loss definition, parameter flattening order,
   and initial-state bytes. Preserve the original selection and use the same
   TRAIN first 4 and VAL first 64 examples. Do not use TEST or retrain here.
2. Begin with the two preidentified counterexamples: RMS analytic / seed7503 /
   updates256, and content_analytic / MQAR / seed7202 / updates768. The latter
   has candidate `07e29f1a3a6ae2368b9b7c907f9045359abf2a68607585fda3cc0a55842e67b6`,
   checkpoint `step-0000768`, weights SHA
   `97ef782fb1f009ba86a6dbbcbadb0bf24b9dbefbcee6b9334e31820467f47dca`, and
   manifest SHA
   `2f749bafc3e42702d09990aab30fad9239e22d09f990730ebd6eb361a5df6b09`.
3. First compare **float32 versus float64 at the same h**, for h=0.25, 0.0625,
   and 0.03125. Record logits, loss, final states, full gradients, and parameter
   group gradients. Do not confound precision with refinement again.
4. Inspect real ranges of lambda*h, kappa, margin, and Call numerators. Record
   boundary crossing counts, minimum absolute margin, internal step counts,
   clamps, and any nonfinite intermediates. Compare identical mathematical
   kernels using a 2x2 switch: old/stable phi and old/stable Call arithmetic.
   Do not change the state equations or model weights in this attribution step.
5. Establish a float64 reference using stable kernels at h=1/32, 1/64, 1/128;
   extend to 1/256 only if the reference is not converged. Cross-check the two
   diagnostic cases with an independent high-accuracy ODE integrator and the
   corresponding variational equations or parameter directional differences.
   Keep the content h update exactly once per external tick.
6. Freeze acceptance tolerances before examining these new results. A suitable
   kernel gate requires relative error <=1e-5 (float32), <=1e-11 (float64) for
   nonzero representable scalar values and derivatives, plus exact boundary
   values. An absolute tolerance alone would incorrectly accept a zero Call
   value where its small positive value and kappa sensitivity were lost.
   For trajectory gradients, require two consecutive reference refinements to
   agree within a separately declared loss-scaled absolute tolerance and
   relative L2 tolerance (for example 1e-3), and report per-group conditioning.
7. If the numerical correction works on these fixed cases, evaluate all 42
   originally selected checkpoints before retraining. A replacement numerical
   map changes training; any new training study must receive a new source seal,
   run identity and frozen selection protocol, retaining the original results.

Possible outcomes are distinct: a precision implementation defect; an
under-resolved but numerically stable integration; sensitivity caused by the
actual nonlinear trajectory; or a reference that was itself inadequate.
The diagnostic must determine which occurs rather than declaring every
nonmonotone gradient a defect of the model or of ordinary BP.

## 4. What remains unsupported

The old source and trained tensors were unavailable to this standalone study.
It cannot establish that the original implementation used unstable formulas,
that the two mechanisms explain the previously measured errors, that any old
checkpoint now passes, or that a stable kernel improves task accuracy.

Raw result SHA-256:
`5046e98cba805c7cb978126b3229016541f7296cd423fce6b592d815af303e36`.
Source SHA-256:
`fb56c61fc1080180d1ad360804240f4526d3ffcb15d628e296549fa7ad3b071d`.
Protocol SHA-256:
`17196faea1d5f550d86a61ea0dbab75a7cb9ad9dd1af3e5dfea3077779e86669`.
