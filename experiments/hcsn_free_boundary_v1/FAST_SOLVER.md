# Optional faster stationary-boundary solver

This extension changes the numerical root calculation, not the regenerative
control problem. It is separate from the frozen study. `oracle_torch.py`,
`model.py`, all selected checkpoints, and `PROTOCOL.json` remain unchanged.
The implementation is `oracle_fast.py`; the complete reproducible evidence is
`results/fast_solver001/RESULTS.json`.

The useful result is a roughly 2–3.4 times faster isolated boundary operation
on the measured CPU workloads, with better accuracy in the extended near-branch
and rounded-endpoint stress cases. Whole-model training probes show much smaller
and noisy improvements. This is not evidence of improved task accuracy,
generalization, energy use, or training at a different compute budget.

## 1. Same root, better numerical coordinates

For the existing scalar oracle, write

\[
 a=\rho\tau+\kappa(K-r)>0,\qquad y=\kappa(b-K).
\]

The unique admissible root obeys

\[
 f_a(y)=y+\operatorname{expm1}(-a-y)=0,\qquad 0<y<1.
\]

Since \(f_a(0)<0\), \(f_a(1)>0\), and
\(f_a'(y)=1-e^{-a-y}>0\), uniqueness follows immediately. Its principal
Lambert-W representation is

\[
 y=1+W_0(-e^{-a-1}).
\]

The other real branch is outside the positive-root domain. Direct binary64
evaluation of this formula loses precision near the branch point; it is used
only as a diagnostic. The reference used for the stress grid evaluates it at
100 decimal digits, independently of the iterative solver.

### Analytic bracket

At the root,

\[
 a=-\log(1-y)-y=\sum_{n=2}^\infty \frac{y^n}{n}.
\]

For \(0<y<1\),

\[
 \frac{y^2}{2}\le a\le\frac{y^2}{2(1-y)}.
\]

Consequently,

\[
 \frac{2\sqrt a}{\sqrt{a+2}+\sqrt a}
 \le y\le\min(\sqrt{2a},1).
\]

This is a real-arithmetic bracket. The tensor implementation pads its computed
endpoints by a few ulps and safeguards proposals within them. It does not claim
that ordinary Torch elementary functions implement directed interval rounding.
The independent exact-rational certificate below establishes a rigorous
enclosure for each audited returned value.

### Stable residual and three Halley iterations

For small \(a\), the root is \(y\sim\sqrt{2a}\). Evaluating
\(y+\operatorname{expm1}(-a-y)\) directly subtracts two quantities of order
\(\sqrt a\), while the residual changes on the order of \(a\). With
\(z=a+y\), the extension instead evaluates

\[
 f_a(y)=-a+\frac{z^2}{2}-\frac{z^3}{6}+\frac{z^4}{24}-\cdots
\]

when \(z<1/8\). The polynomial ends at degree 14. The alternating-series
truncation error is bounded by \(z^{15}/15!\), independently of floating-point
rounding. For larger \(z\), the ordinary `expm1` residual is adequate for the
observed error criterion.

Starting at the bracket midpoint, the fast path performs three safeguarded
Halley steps:

\[
 y_{+}=y-\frac{2ff'}{2(f')^2-ff''},\qquad f''=e^{-a-y}.
\]

If a proposal is outside the bracket or nonfinite, it falls back to its
midpoint. Inclusive endpoint checks matter: when the true root is closer to 1
than binary64 can distinguish, returning exactly 1 is appropriate. Rejecting
that floating-point endpoint can force unnecessary bisection.

After the three steps, unresolved entries use safeguarded Newton/bisection,
with an explicit maximum of 80 fallback iterations and a failure exception if
the residual condition is not met. The test suite exercises this branch by
setting the fast-step count to zero. The ordinary 481-point stress grid needed
no fallback.

## 2. Certificate and conditioning

`dimensionless_root(..., return_diagnostics=True)` returns a floating-point
bracket, residual, derivative lower bound, condition measures and fallback
counts. These diagnostics are inexpensive a posteriori numerical checks.

`rational_certificate(a, y)` is a separate, more expensive proof layer. It
interprets the supplied binary64 numbers exactly as rational numbers. It bounds
the exponential using

\[
 S_N\le e^z\le S_N+
 \frac{z^{N+1}/(N+1)!}{1-z/(N+2)},\qquad N+2>z,
\]

where \(S_N=\sum_{j=0}^N z^j/j!\). All arithmetic in these inequalities uses
Python `Fraction`, so the sign proof does not depend on a correctly rounded
`exp`, `expm1` or Lambert-W implementation. For very large \(z\), the simpler
upper bound \(e^{-z}\le1/S_N\) suffices; no enormous range-reduction exponent
is constructed.

The certificate verifies \(f(\ell)\le0\le f(u)\), giving a rigorous root
enclosure. It also uses

\[
 f'(t)\ge \frac{a+\ell}{1+a+\ell}=:m>0
 \quad\text{for }t\in[\ell,u]
\]

and a rational upper bound \(R\) on \(|f(y)|\) to obtain

\[
 |y-y_*|\le\min\{\max(y-\ell,u-y),R/m\}.
\]

Bounds are converted to JSON floats with outward rounding. The reported
`root_relative_error_bound` divides this absolute bound by the supplied computed
`y`; it is not a claim about a different denominator. The certificate applies
to the exact binary64 input `a`. Rounding in the physical construction of
\(\kappa\), \(K-r\), \(a\), or the final \(b=K+y/\kappa\) is outside its scope.

Certificates are deliberately excluded from fast-path performance timings.
The validation run requests one for **every one of the 481 grid points**. Thus
the delivered evidence has rigorous enclosures, while production tensor calls
do not pay the exact-rational arithmetic cost by default. This distinction is
part of the API contract.

At the root,

\[
 \frac{dy}{da}=\frac{1-y}{y},\qquad
 \left|\frac{a}{y}\frac{dy}{da}\right|
 =\frac{a(1-y)}{y^2}\longrightarrow\frac12\quad(a\downarrow0).
\]

The dimensionless root is relatively well conditioned in `a`, but its absolute
derivative diverges. Physical sensitivities such as
\(\partial b/\partial K=1/y\) also diverge. The solver cannot recover a reset
gap that was already lost when representing `K` and `r` in float32, nor can it
remove the mathematical near-chattering sensitivity.

## 3. Same six-parameter first derivative

The optional `free_boundary(mu, sigma, rho, K, r, tau)` has the same broadcasting
interface and scalar-model domain as the frozen function. It supports first
implicit derivatives only. Higher-order implicit differentiation is not
implemented or certified.

The backward uses the existing exact derivative formulas, with one algebraic
stability improvement. If \(q=e^{-a-y}\), the sensitivity term is evaluated as

\[
 \frac{y(1-q)}{\kappa}-q(K-r)
\]

instead of subtracting
\(y/\kappa-q[y/\kappa+(K-r)]\). This avoids subtracting two quantities of
order \(\sqrt a\) near the branch point.

Validation includes three full six-parameter Torch `gradcheck` cases, a
broadcast `gradcheck`, and six physical regimes against 100-digit reference
derivatives. The latter include negative drift, a \(10^{-16}\) reset gap and a
large refractory time. Very small underflow-scale derivatives are assessed
with absolute error, not a fictitious relative-accuracy guarantee.

## 4. Accuracy evidence

The complete run passed five unit tests plus the larger numerical/gradient and
model-probe checks. It used one Torch CPU thread and no main-study outcomes.

| Check | Result |
|---|---:|
| Log-spaced `a` grid | 481 points, \(10^{-16}\) through \(10^8\) |
| Maximum root relative error vs 100-digit reference | \(7.231\times10^{-16}\) |
| Maximum independent SciPy Brent relative error | \(6.906\times10^{-16}\) |
| Maximum exact-rational error bound divided by computed root | \(7.760\times10^{-16}\) |
| Grid points requiring fallback after three Halley steps | 0 |
| Exact-rational certificates obtained | 481/481 |
| Maximum positive-exponential series terms used in certificates | 49 |
| Scalar / broadcast first-derivative gradchecks | 3/3 and 1/1 |
| Maximum relative derivative error over the nonzero reported references | \(3.04\times10^{-15}\) |

On this extended stress grid, the frozen 32-step implementation had maximum
relative root error approximately \(9.01\times10^{-9}\). This reveals a
finite-precision limitation of its direct small-`a` residual and endpoint
safeguard. It does not reclassify the earlier ordinary-domain oracle validation
as a failure, and these extreme reset gaps are excluded by the frozen neural
model's parameter constraints.

The optional full-model adapter used freshly initialized float32 models and
synthetic inputs. On both tested batch sizes, the complete logits and the
concatenated parameter gradients were **bitwise equal** between the original
and replacement solver in those probes. That is a result for these tested
inputs, not a universal bitwise-equivalence guarantee.

## 5. CPU measurements and practical limit

Seven interleaved timing blocks alternate old/new order. Each table entry below
is the median of paired CPU-time ratios; raw pairs and per-operation times are
preserved in the JSON. These are timing repetitions, not independent training
seeds. Exact-rational certificate work is outside these timings.

| Boundary input shape | Forward speed ratio | Forward + backward ratio |
|---|---:|---:|
| Scalar | 2.80× | 2.19× |
| `[32]` | 2.80× | 2.17× |
| `[8,32,32]` | 3.42× | 3.03× |
| `[32,32,32]` | 2.71× | 2.53× |

Every measured paired boundary ratio exceeded 1.8×. This supports a useful
isolated root speedup for the measured workloads.

The full-model probe uses width 32, depth 1, sequence length 32, input dimension
64, 10 output classes, and the same synthetic inputs. It measures forward or
forward-plus-backward, with no optimizer update or task training.

| Batch | Forward paired median / range | Forward + backward paired median / range |
|---|---|---|
| 8 | 1.123× / 0.485–1.236× | 1.047× / 0.949–1.350× |
| 32 | 1.437× / 1.339–1.572× | 1.085× / 0.549–1.657× |

The batch-32 forward probe was consistently faster in these timings. The
training-like probe ranges include slowdowns and substantial noise; a stable
whole-training speedup is **not established** by this small probe. In
particular, the isolated 2–3× root ratio must not be presented as a 2–3×
model-training improvement. The paired-ratio median is also not necessarily the
ratio of the separate old and new medians.

Conditionally on the separately reported profile in which the root contributes
about 12% of training time, Amdahl's law gives

\[
 S_{\rm whole}=\frac1{0.88+0.12/S_{\rm root}}.
\]

Even an infinitely fast root would then be limited to about 1.136× overall,
assuming the other costs remain unchanged. Forward-only workloads can have a
different root fraction. No hardware-energy inference follows from CPU time.

The complete validation/probe function consumed 12.954 CPU seconds and 14.790
wall seconds in its recorded run. That measured scope starts after module
imports and excludes the final evidence write; it is not a fabricated complete
process bill.

## 6. Running and optional integration

From the repository overlay root:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
python -m experiments.hcsn_free_boundary_v1.oracle_fast_tests \
  --output experiments/hcsn_free_boundary_v1/results/fast_solver_new_run
```

Evidence directories are not overwritten. `--no-benchmark` retains numerical,
certificate and gradient validation while skipping the performance probes.

Applications may import the optional boundary directly. For an isolated probe
of the existing model, `model_runtime_adapter()` temporarily replaces only the
current Python process's `model.free_boundary` symbol and restores it in a
`finally` block. It changes no files and must not be used concurrently by
multiple threads in one process. It has not been activated in the frozen study.

The extension does not address the mean-state closure bias, moving-boundary
regeneration, memory/content quality, or any of the failed/untested scientific
claims outside the scalar boundary solver. Those retain their existing
contracts and evidence.
