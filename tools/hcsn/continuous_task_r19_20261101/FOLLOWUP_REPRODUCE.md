# Reproduce the prospective small-step supplement

From repository root, use a fresh output path:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.continuous_task_r19_20261101.followup --out /tmp/hcsn_r19_gradient_followup_fresh.json
```

The source verifies all eleven frozen files, exact R18 input identities and the
actual original failed result before running. The prospective protocol fixes
both smaller steps before its evaluation. The original larger-step result is
neither overwritten nor pooled into a new success.

Both the original and followup whole-array gates failed. Repeat deterministic
verification produces no additional independent task samples. Full perturbed
arrays are not archived; every maximum-error witness and array hash is retained.
The standard-library record checker independently verifies witness arithmetic
and published aggregates, without claiming a full numerical array replay.

The frozen source is Python/NumPy/SciPy research code. The official followup was
run on Linux with CPU affinity 0–5 and BLAS threads 1. Resource measurements and
the unsupported moving-delay, domain, global and continuum derivatives remain
explicit in the report.
