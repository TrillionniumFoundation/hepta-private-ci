# R11 finite propagation contract and independent audit

## Result and scope

The R11 controller trains and queries `finite.augmented_features`. The actual
Rust owner still executes the identified R9 `cell::Cell`; `probe.rs` imports that
same file, rather than reproducing it in a substitute executable. The Python
matrix exponential and Rust positive uniformization agree on the declared
three-active-bin, two-Erlang-phase model. **That finite model is the definition
used in this control experiment. It is not claimed to be the continuous
He–Xiong process.** Grid refinement is a separately measured numerical study.

No earlier source or result was changed. `finite.py` was frozen before the R11
controller's heldout data; its hash is also in the controller training freeze.
The main task has a sufficient posterior and public schedule. Its Bellman
teacher does not need the extra cell state to infer that posterior. Sharing the
cell generator therefore establishes feature/execution consistency, not a new
claim that evidence packets are Brownian observations or that cell features
contain additional information unavailable to the ordinary controller.

## Shared model

The six bounded parameters determine positive drift and diffusion, upper
boundary, reset location and mean Erlang recovery time. The physical state has
three active bins followed by two recovery phases; the lower jump reflects.
An upper jump increments the event accumulator and enters recovery. Recovery
passes through both phases before convex interpolation at the reset location.
The accumulator is an expected number of repeated events and can exceed one.

For a row probability vector, the augmented generator is

\[
A=\begin{pmatrix}Q&r\\0&0\end{pmatrix},\qquad
(p(t),\mathbb E N_t)=(p(0),0)e^{tA}.
\]

Removing the upper jump into recovery, while keeping its diagonal loss and its
positive flux into the absorbing accumulator, produces the first-future-event
CDF. This replaces the old Python `1 - survival` evaluation, which can lose tiny
probabilities by cancellation. Event count and first-hit probability remain
separate outputs. A task FIRE additionally resets the physical distribution at
the **end** of its interval and leaves historical event count intact. It is not
identified with a spontaneous cell event.

`transition` exposes the finite matrix exponential and its Frechet directional
derivative. `physical_state` differentiates complete histories, including the
parameter-dependent initial/reset law. Reset interpolation knots with nonzero
motion are rejected instead of given an unjustified ordinary derivative.
Task-history coefficients remain fixed between its public action boundaries.

The native clock uses integer microseconds. Native parity below covers those
representable durations, including zero intervals, one microsecond and 128
seconds. The R11 task protocol's durations are all representable this way.
Arbitrary sub-microsecond floating durations are not a shared native clock
contract. The mathematical `transition` also supports real-valued durations for
the separate semigroup and numerical derivative checks.

## Executed verification

`evidence/BUILD_02.json` records a new Cargo build from identified Hepta sources
and `just test`: **2 tests passed, 0 skipped**. These test complete distribution
receipts and sampled RNG/event recovery, respectively. This is a scoped research
build, not whole-repository CI. Some exact package archives were unavailable;
the existing explicit cached-source fallback records file inventories. Thus
`all_dependency_archives_verified=false` remains visible.

`evidence/AUDIT_02.json` records 48 parameter/history/family cases plus independent
ODE, generator, derivatives, split intervals and invalid-input checks:

| Comparison | Maximum absolute error |
| --- | ---: |
| Python vs actual native generator | 4.44e-16 |
| Python vs native probability state | 7.11e-15 |
| Training features vs native query | 9.05e-15 |
| Cumulative repeated count, including 128 seconds | 8.88e-13 |
| Independent DOP853 ODE vs matrix exponential | 1.46e-13 |
| Whole-history Frechet derivative vs central differences | 5.57e-11 |
| Matrix semigroup split | 7.74e-13 |
| Native interval split | 8.67e-13 |

The 36 nonempty-history executions restored the native cell and matched their
uninterrupted receipts exactly; 12 initial-state cases needed no restoration.
The tiny first-hit case stayed strictly positive in Python and Rust. Out-of-domain
driver and duration requests were rejected. These are finite-case floating-point
checks, not a uniform proof of all parameter histories or an external-effect
exactly-once guarantee. The controller's task-owner audit covers persistence.

## Continuous reference and the remaining approximation gap

`resolution.py` independently solves the constant-coefficient first-hit backward
PDE using a Robin/Dirichlet spectral expansion. For distance from the reflecting
wall \(y\), interval length \(L\), \(D=\sigma^2/2\) and
\(\alpha=\mu/\sigma^2>0\), the gauge-transformed eigenfunctions are

\[
\phi_k(y)=\cos(ky)+\frac\alpha k\sin(ky),\qquad
k\cos(kL)+\alpha\sin(kL)=0.
\]

Each eigenvalue is bracketed separately. The 64/128/256-term results agree on
three declared cases. This is independent of the earlier inverse-Laplace method
and of both finite generator implementations; finite precision still limits
tail accuracy and no interval certificate is claimed.

At the baseline, the continuous first-hit probability at 3 seconds is
`0.7599053773055832`. The following timings are medians of seven measurements,
including two SciPy float64 dense exponentials and vector applications, on one
BLAS thread. They are not native timings, training costs or energy readings.

| Finite profile | Active bins | First-hit absolute error | CPU ms |
| --- | ---: | ---: | ---: |
| Deployed upwind definition | 3 | 0.143312 | 0.0285 |
| Same upwind refinement | 32 | 0.0226882 | 0.1558 |
| Same upwind refinement | 64 | 0.0117244 | 0.6693 |
| Same upwind refinement | 128 | 0.00598727 | 5.6199 |
| Separate centered/upper-face candidate | 32 | 0.000858432 | 0.2292 |
| Separate centered/upper-face candidate | 64 | 0.000179070 | 0.9119 |
| Separate centered/upper-face candidate | 128 | 0.0000527569 | 5.7924 |

The centered candidate rejects negative transition rates and uses the actual
absorbing face. It shows a concrete route to reduce the upwind artificial
variance and boundary-location error. It is a **different finite generator**,
has not been deployed in this owner, and cannot silently replace the model in a
frozen experiment. At the short-horizon tail, even its 128-bin absolute error
`4.66e-9` is substantial relative to the continuous probability `8.96e-9`.
The original continuous-law equivalence blocker is therefore still open.

All three cases, raw timing repeats, state/matrix memory and relative tail errors
are in `evidence/RESOLUTION_01.json`. Continuous repeated-event laws, moving
boundaries and native refined-grid cost are outside this numerical study.

## Resource and source accounting

Build command receipts record child CPU and wall time, with the compiler/test
output retained. The propagation audit's `cpu_seconds` is Python parent CPU;
its native probe children are **not** included in that field. Its wall time
includes those children. It must not be reported as full audit CPU. Resolution
CPU is a single-process measurement; the seven kernel timings are nested within
it and must not be added again. None of these measurements supplies joules.

Each evidence record identifies executed source hashes and, where applicable,
the actual binary hash. A later formatting receipt can identify a formatting-only
change; the execution records must retain their original source identities.
The repository's `just fmt` changed `probe.rs` and `probe_tests.rs` after run 01.
Run 02 rebuilt and revalidated those exact formatted bytes; all 48 cases and the
two Rust tests passed with the same reported maximum numerical errors. Run 01
remains intact. Neither `finite.py` nor the resolution study was changed.

## Reproduce

From the repository root, with a pinned compiler and the identified dependency
cache, build the probe using `python -m
tools.hcsn.calibrated_operator_r11_20261031.propagation.build_probe --help`.
Use a fresh build path and evidence filename. Then run:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.calibrated_operator_r11_20261031.propagation.audit --binary /path/to/codex-hcsn-finite-probe --output /tmp/r11-propagation-audit.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.calibrated_operator_r11_20261031.propagation.resolution --output /tmp/r11-resolution.json
```

All outputs use exclusive creation. Reproduction must preserve the original
evidence and report failures rather than overwrite a previous run.
