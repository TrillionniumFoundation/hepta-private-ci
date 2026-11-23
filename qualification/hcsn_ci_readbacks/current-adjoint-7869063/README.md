# Current HCSN continuous-adjoint CPU replay

The frozen successor source is `7869063345ea43cc9cb83ff6d76d70bf94ff62a5`. It ran on Linux with Python 3.12, CPU PyTorch 2.15.0, NumPy 2.3.5 and SciPy 1.17.0. The original reference at `975a169df5f3a1dd51b81ddd51b0a338592a0e0f` used CPU PyTorch 2.10.0. The two runs have separate identities.

All 69 input coordinates passed the original scalar gradcheck, 27 on the uniform grid and 42 on the graded grid. The full run executed 166 forwards and 10 adjoints. All 20 mutation controls rejected their inputs before an adjoint call. The result includes all 12 numerical checks, 888 arrays and both complete journals. Among the 38,805 recorded values, the largest absolute difference from the archived reference arrays was 4.83e-11. Of the 888 arrays, 714 were bit-identical. The process took 70.26 seconds and emitted the SciPy BDF runtime warning retained in `native.stderr`.

To replay from the source commit, download `SOURCE-MANIFEST.json` from this evidence directory and set the three math-library thread limits to 1. Use an absent directory for the output.

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -B -m qualification.hcsn_adjoint_torch.native_probe \
  --current-source --source-manifest /path/to/SOURCE-MANIFEST.json \
  --baseline-archive qualification/hcsn_initial_vjp/evidence/NUMPY001-ORIGINALS.tar.gz \
  --output /path/to/new-output
```

The independent reference basis, tolerances and numerical test body match the original procedure. The source manifest binds the current state/flux implementation. The probe evaluates first-order derivatives with respect to the four input tensors at fixed model coefficients. It applies zero optimizer updates.
