# Same-process bounded propagation and cost audit

## Result

The optional `operator_fastpath.transition(A, t)` evaluates the same finite
matrix exponential as the existing dense reference. Development attempt 002
passes **202/202** checks. It is not enabled as the content model's default.
Its measured advantage is confined to the larger **forward plus backward**
batches in this CPU experiment; the small-batch and most forward-only calls
are slower. No network-quality, GPU, or joule advantage follows from these
measurements.

The exact source identities, original arrays, every check, raw timing samples,
and complete source snapshots are in [development002](development002/).
The first attempt and its two failed checks remain in
[development001](development001/). These are development experiments,
not preregistered independent confirmation outcomes.

## Numerical method and bounds

For a row subgenerator `A`, choose a detached dominating rate `lambda` and
set `U = I + A/lambda`. The implementation evaluates the positive polynomial

`exp(-x) sum_(k=0)^K x^k U^k/k!`,

using a Paterson–Stockmeyer evaluation and then per-item squaring. No negative
probability is clipped and no row is normalized. `A` may be the complete `Q`,
the killed `Q-R`, or the marked content generator
`Q-(1-eta)R-decay*I`. This changes the numerical implementation, not the
underlying reset, refractory, or firing model.

Each scaled interval has Poisson mean at most 0.5. For a strictly
substochastic jump matrix, the maximum row-l1 truncation error after `m`
intervals is at most `m P(Poisson(x)>K)`. Small positive row sums produced by
generator construction roundoff are explicitly included: with
`alpha=max(0,max(A*1))`, the polynomial bound uses the enlarged Poisson mean
`x+alpha*t/m` and a multiplier `exp(alpha*t)`. The bound itself is an
exact-arithmetic truncation statement; it excludes floating-point error.

For repeated counts the same polynomial is applied to the augmented jump
matrix with event column `r/lambda`. The dominating rate also includes
`max(r)`, so self-firing marks still count when they do not move the state.
The constant coordinate is truncated too. A union bound over omitted
Poisson events gives the count-error majorant

`exp(alpha*t) [m E(N 1{N>K}) + (m-1) t max(r) P(N>K)]`.

The second term is necessary. Merely composing a count-error tolerance
without accounting for lost probability in other intervals would be
insufficient. The implementation uses a geometric upper bound on both
Poisson tails, which is checked against SciPy's independent survival
function. If the declared polynomial/squaring work caps cannot meet the
requested truncation tolerance, the implementation falls back to the dense
reference and labels that choice. Dense fallback has no Poisson truncation;
this does not assert a zero floating-point error.

Input caps are 128 states, 4096 batched matrices, and a norm-duration product
at most 2048. Invalid rates, negative time, nonfinite input, invalid
subgenerators, and excess resource demands are refused.

## Independent checks

The audit reconstructs physical generators with the previous independent
NumPy assembler, and compares against SciPy `expm`, augmented count
exponentials, and `expm_frechet`. It includes killed/tilted/full semigroups,
time zero, zero events/noise, negative drift, refractory residence,
instantaneous self-reset, all-self-mark count 680 with unchanged state,
rate scales from zero through 512, PGF derivatives, batch isolation,
fallback, and invalid-input refusal.

Selected largest recorded errors in attempt 002:

| Check family | Largest absolute error |
|---|---:|
| Regular FP64 transition vs SciPy | 1.788e-13 |
| Regular FP32 transition vs SciPy | 1.384e-6 |
| Sampled Frechet/time gradients | 6.033e-9 |
| PGF derivative vs repeated-count sum | 3.318e-12 |
| High-rate count at scale 512 | 1.239e-11 |

The gradient audit has its own fixed 2e-7 tolerance. A transition truncation
bound is not silently promoted into a uniform bound on derivatives.

## Finite spatial approximation

An independent reflected-diffusion mean first-passage calculation prevents
the finite CTMC from being mistaken for an exact diffusion. It solves
`(sigma^2/2)u'' + mu*u' = -1` with `u'(lower)=0` and `u(boundary)=0`.

For zero drift, the continuum solution is
`[(boundary-lower)^2-(x-lower)^2]/sigma^2`. The discrete cell-center solution
has an offset `h^2/(4*sigma^2)`; after linear interpolation, the absolute
error has the envelope `h^2/(4*sigma^2)`. For the fixed initial position used
here, the actual error happens to remain approximately 0.000486592 from 8
through 128 cells, while remaining within the shrinking envelope. It is
therefore incorrect to demand that every chosen refinement reduces this
particular pointwise interpolation error by a fixed ratio.

For the positive-drift witness, the error decreases from 0.0651968 at 8
cells to 0.00556810 at 128 cells; intermediate errors are nonmonotonic.
These are two mean-passage-time witnesses, not a general convergence proof
for transition densities, gradients, or trained model outcomes.

## Cost

Timings use torch 2.9.0+cpu, NumPy 2.3.5, SciPy 1.17.0, one computation
thread, matched matrices/dtypes/losses, four warmups and eleven interleaved
repetitions. Validation, scheduling, allocation within the kernel, and
backward are included. Tensor preparation is matched and occurs outside
the timers for both implementations. This is a shared CPU environment.

Values below are dense median time divided by bounded median time; values
above one favor the optional implementation.

| Matrix batch | Precision | Forward only | Forward plus backward |
|---:|---|---:|---:|
| 24 | FP64 | 0.397 | 0.647 |
| 24 | FP32 | 0.388 | 0.666 |
| 384 | FP64 | 0.740 | 1.643 |
| 384 | FP32 | 0.860 | 1.562 |
| 1536 | FP64 | 0.837 | 2.201 |
| 1536 | FP32 | 1.167 | 2.080 |

The subsequent [full-model comparison](full_model001/SUMMARY.json) uses
the same trained development MQAR/binding weights, the same independent
development inputs and the complete `AddressedModel` forward/backward.
Source and checkpoint hashes were frozen, and all source files were verified
unchanged afterwards. The optional adapter runs only in that isolated audit
process; no default or stored model is modified. Maximum differences in
the logits and parameter gradients are both zero for the tested calls.

| Task | Batch | Forward only ratio | Forward plus backward ratio |
|---|---:|---:|---:|
| MQAR | 24 | 0.940 | 1.022 |
| MQAR | 64 | 0.981 | 0.880 |
| Binding | 24 | 0.921 | 1.032 |
| Binding | 64 | 0.861 | 1.165 |

The kernel improvement is not a stable full-model improvement. In particular,
the fixed batch-24 workload gains only about 2–3% on these backward timings
and loses time in inference; MQAR batch-64 backward is also slower. **The
dense default should remain in place.** These are four warmups and nine
interleaved repeats in a shared CPU environment, not a complete training
study or a distribution of deployment latencies. No energy reading was
available or inferred from CPU seconds.

A targeted execution-path check in [full_model002](full_model002/SUMMARY.json)
records **216 backend calls over 133,056 matrices**. Every call used the
Poisson scaling/squaring path, with no dense fallback; the largest selected
polynomial degree was 11. Logit and gradient differences remained zero in the
tested FP32 neural outputs. Thus equality did not arise because the adapter
was bypassed. The repeat's complete-model backward ratios were 1.014/1.132
for MQAR batches 24/64 and 1.015/1.203 for Binding batches 24/64. Its
forward ratios were 1.053/0.931 and 0.931/0.971 respectively. The variation
between the two retained shared-CPU runs reinforces the decision to keep the
dense default.

## Preserved first-attempt findings

Attempt 001 passed 200/202 checks. One batch-isolation fixture constructed
its nominal FP64 duration via a FP32 tensor, so its two sides received
different numerical times. Correcting the fixture to supply the same FP64
values closes that failure without changing the propagator.

The other failed assertion demanded a fivefold error decrease for the
zero-drift MFPT witness. The correct analytic interpolation envelope above
explains why this demand was invalid. Attempt 002 tests that envelope and
reports the unchanged errors rather than hiding them. The original arrays,
source snapshots, failed rows and timing records remain available.

## Reproduction

From the repository root, using the recorded scientific Python environment:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONDONTWRITEBYTECODE=1 python -m \
  experiments.hcsn_addressed_flow_20261101.operator_fastpath_checks \
  --out NEW_AUDIT_DIRECTORY
```

The destination must not already exist. Each invocation freezes source
copies before executing and retains every failed check.
