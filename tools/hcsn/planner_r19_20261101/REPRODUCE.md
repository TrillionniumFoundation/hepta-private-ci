# Reproduce the exact engineering workload

Use the final published tree with all original inputs named by SOURCE_MANIFEST.json present. Restore packaged evidence first if using a transport-only checkout. Publication identifies the four frozen candidate files; do not replace their bytes. ERRATA.json corrects the frozen fsync wording: only query==2 is a disk checkpoint.

To execute a new engineering replay, use a new output directory:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 8 python -m tools.hcsn.planner_r19_20261101.campaign --output /tmp/hcsn-r19-fresh-confirmation
python -m tools.hcsn.planner_r19_20261101.raw_audit /tmp/hcsn-r19-fresh-confirmation
```

CPU8 must exist in the allowed affinity mask; another core changes environmental identity and must be recorded. Exact timings are host-specific. The same namespace is an engineering replay, not new independent efficacy evidence. The campaign refuses an existing output directory.

`independent_review.py` retains the separate reviewer implementation. Its published INDEPENDENT_* outputs bind the executed source and raw evidence. `test_planner.py` is a deterministic direct differential; it preserves immutable inputs, scalar values, layouts and rejection controls and is not an independent mathematical continuum reference.

Do not combine nested actor/cache/preparation timers with their complete child receipts. Read COST_LEDGER.json and ERRATA.json before interpreting the acceptance fields.
