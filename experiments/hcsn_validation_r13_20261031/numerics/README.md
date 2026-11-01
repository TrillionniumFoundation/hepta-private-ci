# R13 recovery age and complete-state checkpoints

The R12 audit compared the continuous active-position law and total refractory
mass with an independent forward equation. It did not independently compare
refractory-age moments or bins, and its twelve semigroup checks applied only to
the killed, never-hit kernel. This additive study addresses those two gaps.
Original R12 source and evidence are unchanged.

The physical process is a constant-coefficient one-dimensional Brownian distance
to an absorbing boundary, followed by a fixed positive recovery delay and a fixed
positive reset distance. The future depends on both the active distribution and
the remaining recovery times. A scalar pending mass does not retain those times.

## Independent age reference

If the n-th firing occurs at `T_n`, fixed reset and drift/noise imply
`T_n` has the distribution of the hitting time from `x+(n-1)*reset`, shifted by
`(n-1)*refractory`. For age `a` in `[0,refractory)` at time `H`, the recovery-age
density therefore sums the n-th firing densities at `H-a`. The reference
integrates this density separately over four age bins and against `1,a,a^2`.
Its moments are crosschecked against the unchanged R12 quadrature.

`age_pde.py` independently evolves nearest-neighbor spatial rates and a complete
deterministic-age queue driven by its own absorbing flux. It never injects an
analytically supplied event count. The queue retains every pending recovery
cohort. Age moments use the finite-volume uniform-within-bin reconstruction;
this is a numerical approximation, not an exact pathwise event-time sample.

Three spatial grids also refine the time/age grid. The delay is an integral
number of time steps, avoiding unrecorded fractional-delay interpolation.
Mass, positivity, upper-boundary loss, active bins, event count, age bins and
normalized age moments are checked against frozen tolerances. Continuum
agreement is numerical evidence at the registered cases, not a uniform theorem.

## Checkpoints and observation partitions

A checkpoint contains active probabilities, the full ring buffer of recovery
cohorts and its cursor, the physical clock and integer step, accumulated events
and upper-boundary loss, and the complete model/grid identity. SHA256 protects
the serialized payload against accidental change. Restore also checks field
presence, shapes, time/cursor consistency, finite/nonnegative probabilities and
probability mass, then checks the identity expected by the caller.

Four uneven observation splits roundtrip through actual JSON files. At each
split the original space/time grid remains fixed. The complete final checkpoint
must equal the unsplit result bit for bit. At the finest grid for each parameter
case, a fresh Python process also resumes a mid-interval file and reproduces the
unsplit final state. Off-grid time requests are explicitly refused. These checks
do not establish arbitrary mesh-change or interpolation equivalence.

Two deliberate physical corruptions are retained as failed equivalence rows:
dropping the recovery queue, and moving all pending mass to the youngest age
while preserving its total. Separate positive tests require each corruption to
produce a detectable final-state/count difference. The latter control isolates
the loss of age information from mere mass loss. Malformed, hash-altered,
grid-mismatched, clock-inconsistent and negative-mass checkpoints must refuse.

## Execution and evidence

Write-once attempts retain protocol/source snapshots, reference values, all
ordinary and negative-control rows, every checkpoint, direct and segmented final
states, fresh-process logs, failures and full-process CPU/RSS receipts.

From the repository root:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B experiments/hcsn_validation_r13_20261031/numerics/launch.py \
  --out experiments/hcsn_validation_r13_20261031/numerics/results/development_01
```

For a formal attempt, first publish and independently read back the exact
source/protocol set, then pass `--stage formal --frozen-commit ACTUAL_COMMIT` and
a new output directory. Each scientific process is limited to one BLAS thread,
512 MiB address space and 120 CPU seconds. The two recovery subprocesses inherit
these limits. The Linux `wait4` receipt includes waited descendants; do not add
the audit's internal counters to that inclusive total.

The result does not qualify the R12 content gate as a complete propagated neural
state, validate arbitrary learned or state-dependent boundaries, establish
financial-kernel regeneration equivalence, or demonstrate model-quality or
hardware-energy gains.
