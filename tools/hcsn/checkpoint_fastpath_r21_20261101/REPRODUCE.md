# Reproduce R21 V2 correctness

Use the published V2 tree and exact45inputs in V2_SOURCE_MANIFEST. Restore packaged logical evidence if needed. The source receipt is df35a6d3869cbcafce8e15b9e40d4bcdd1164439; do not edit frozen sources to bypass checks.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 2 python -m tools.hcsn.checkpoint_fastpath_r21_20261101.v2_cold_checks --output /tmp/checkpoint-r21-v2-cold-fresh
```

This creates117coldprocessesplus9in-controlleroldreferenceexecutions and refuses an existing output directory. Choose an allowed core and record any changed host identity. It is correctness evidence, not a performance comparison. The independent_admission_v2 module writes its declared own create-only receipts; use a separate clean checkout to rerun its60cases, preserving the published original outputs.

`audit_v2_cold_records.py` is the standard-library record auditor for the published retained cold directory. It binds full raw files and compares checksums, typed state, fees and legacy wire bytes without rerunning the actor.

V1 timings and executed sources remain in development_01/executed_sources. To reproduce V1, materialize those six files at their original relative paths in an isolated copy with unchanged base inputs; do not overwrite the V2 checkout. V1 results do not qualify V2 cost or throughput. Read PROOF_AND_SCOPE.md and COST_LEDGER.json for admission boundaries and excluded costs.
