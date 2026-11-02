# Reproduce the task-gradient verification

From repository root, with Python 3, NumPy and SciPy available:

```bash
python -m tools.hcsn.continuous_task_r19_20261101.audit --mode confirmation --out /tmp/hcsn_r19_jump_gradient_fresh.json
```

Use a new output path. The audit verifies the frozen source hashes and original
R18 Git blob identities before checks, then reports every grid value's maximum
scaled derivative discrepancy, both finite-difference levels, all detected
left/right branch changes, admission-time errors and rejected unsupported
coordinates. Repeated deterministic verification does not create independent
statistical task samples.

`DEVELOPMENT_01.json` and `DEVELOPMENT_AUDIT.*` are earlier engineering probes,
not pooled confirmation results. The first audit source is preserved under
`development_source/`. `SOURCE_FREEZE.json` binds the subsequent formal source;
the integration's remote checkpoint records when it was published. Confirmation
stdout, stderr and outer process resource records accompany the final JSON.

The result is confined to the declared fixed grids and smooth coefficients.
Continuum error, moving delay/domain gradients, full neural/financial
gradients, architecture utility and production admission remain open.
