# Reproduce the directional contract and separate generic challenge

Use Python with NumPy/SciPy, from repository root and fresh output directories.
Keep BLAS thread settings at one for the recorded execution profile.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.continuous_task_r20_20261101.campaign --output /tmp/hcsn_r20_exact_fresh
python -m tools.hcsn.continuous_task_r20_20261101.record_check --run /tmp/hcsn_r20_exact_fresh --out /tmp/hcsn_r20_exact_replay.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.continuous_task_r20_20261101.generic --output /tmp/hcsn_r20_generic_fresh
python -m tools.hcsn.continuous_task_r20_20261101.generic_record_check --run /tmp/hcsn_r20_generic_fresh --out /tmp/hcsn_r20_generic_replay.json
```

The two prospective protocols are separate. The exact constant-law tie profile
has a mathematical biactive classification and an affine directional identity;
the nonconstant generic probe exposes floating classification uncertainty and
finite-step errors. Neither result repairs or replaces the two failed R19
campaigns, and generic mathematical qualification remains open regardless of
its numerical gate.

The campaign keeps complete numerical arrays in lossless bounded gzip files.
The standard-library replay verifies their hashes and whole-array arithmetic;
it does not independently re-solve each numerical LCP. Independent small exact
controls instead use exhaustive policy enumeration. The execution envelope's
outer resource record includes interpreter startup, source checking, numerical
work and serialization; inner reported CPU is nested and must not be added again.
