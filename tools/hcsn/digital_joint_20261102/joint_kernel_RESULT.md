# Complete-distribution kernel qualification result

The finite CTMC kernel passed all **47** registered numerical checks in
`joint_kernel_validation_attempt_002.json`. Its source identity is
`0439cf12f4519c29b1b079adb2ebc66eb86a252c59a2754770acc58ed5cff0e9`.
The result source snapshots and reference manifest retain exact input identities.

| Check | Measured maximum error / result |
| --- | --- |
| Full 43-output Jacobian, all eight raw parameters, two long-prefix cases, two FD steps | `3.9018e-9` |
| Full-state Jacobian, seven independent physical coordinates | `2.5982e-10` |
| Same-context whole/split full mass | `3.1364e-15` |
| Same-context whole/split raw Jacobian | `3.6360e-15` |
| Expected-count split gradient | `4.4686e-15` |
| Zero-time identity and zero raw gradient | passed exactly |
| Fixed boundary under gradient and optimizer weight decay | unchanged |
| Batch context/duration versus individual calls | passed |
| Generator signs, mass and stochastic expm on grids 31/63/127 | passed |
| Brownian killed-law stress cases, grid 31 | `.0097422242` absolute probability error |
| Same killed-law cases, grid 127 | `.0005807781` absolute probability error |
| Regenerative moments versus independent PDE240, grid 31 | `.0005494980` |
| Regenerative moments versus PDE240, grid 127 | `.0000250158` |
| Expected events in a single stress interval, grid 31 | `1.4286819259` |
| Published continuous trajectory reference, 2,000 paths | within registered six-SE diagnostic bands |

The full output Jacobian includes all 33 state masses, nine reset-aware future
threshold probabilities, and an expected repeated-event count. Both reset
centers, recovery and Gaussian reset SD have nonzero exercised derivatives.
Finite differences operate on deterministic matrix-exponential laws, not hard
Monte Carlo paths. All initial refractory mass and subsequent resets remain in
the differentiated graph. The whole/split test includes derivatives of the
complete composed distribution, not just equality of mean features.

The raw coordinate column norms are nonzero in both registered contexts; the
smallest is reset SD (`.00132623` in the first case). This verifies exercised
partial derivatives, not physical identifiability: the documented scale gauge
remains. The bank includes future refractory/release/reset transitions under a
constant declared context, and uses strict `>` at finite-grid threshold atoms.

A separate independent audit at the same kernel source identity also passed a
five-context nonlinear distribution/bank/count loss gradient check (`9.65e-10`
maximum FD error), quadrature-based reset construction, SciPy expm, complete
semigroup/gradient, fixed-boundary/inactive ordinary coordinates and scale-gauge
checks. Its source and results are saved separately as
`joint_independent_audit.py` and `joint_independent_audit_kernel.json`.

Attempt 001 did not execute numerical checks: the archived standalone PDE
validation script used a top-level import that failed when imported as a package.
The failure JSON and full new-source snapshots remain preserved. Attempt 002
changed only the new validator's import path handling; archived source was not
edited. The successful run used 11.719633434 wall seconds and 14.136636817 process
CPU seconds, including independent SciPy work. These costs have no task-speed
advantage interpretation.

These results qualify differentiable complete-state propagation for the declared
finite CTMC, with exponential recovery and continuous truncated-Gaussian reset
mass projected to its grid. They quantify spatial approximation error in the
registered continuum comparisons. They do not establish continuum/free-boundary
gradients, a moving boundary, unique physical parameter identification, learned
task gain, native parity or production readiness. The new task, observation
conditioning, head training and deployed owner require their own evidence.
