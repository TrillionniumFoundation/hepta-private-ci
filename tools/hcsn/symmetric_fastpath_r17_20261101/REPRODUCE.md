# Reproduce without overwriting evidence

Read PROTOCOL.json and SOURCE_MANIFEST.json. The source publication receipt binds the exact remote source and manifest before execution. Use a fresh checkout/worktree with all manifest paths present, retain PUBLICATION.json, and choose a checkout whose `results_v2` directory does not yet exist.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.symmetric_fastpath_r17_20261101.study supervise
```

The supervisor first runs the operator/ODE/fallback audit. Only a passing audit launches paired dense/fast full and anchored executions. Failed operator, behavior or checkpoint gates write their records before returning a nonzero status. Create-only files deliberately refuse a second invocation in the same output directory. Replaying the same frozen sample namespace is reproduction, not additional independent confirmation.

`attempt_01` preserves the original audit, its frozen source and receipt. Every numerical comparison passed, but the audit erroneously required all free-rate matrices to be eligible despite the declared dense-fallback contract; the campaign did not launch. Revision2 corrected only that eligibility guard. Its launch refused a previously existing create-only output; no revision2 child or campaign ran. Current `results` duplicates the original audit bytes; the duplication cause is unknown. Revision3 uses explicit `results_v2` and propagates campaign and child failures. Original operator/state/action thresholds remain unchanged.
