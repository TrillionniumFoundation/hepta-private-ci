# Reproduce the frozen R20 profiles

Restore packaged logical evidence first if necessary. All35 SOURCE_MANIFEST inputs and all38 SCRIPTED_SOURCE_MANIFEST inputs must match their hashes. Main and scripted publication receipts identify separate frozen source commits.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 8 python -m tools.hcsn.planner_r20_20261101.campaign --output /tmp/hcsn-r20-resource-fresh
python -m tools.hcsn.planner_r20_20261101.raw_audit /tmp/hcsn-r20-resource-fresh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 2 python -m tools.hcsn.planner_r20_20261101.recovery_checks --output /tmp/hcsn-r20-recovery-fresh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 2 python -m tools.hcsn.planner_r20_20261101.scripted_recovery --output /tmp/hcsn-r20-scripted-fresh
```

The selected cores must belong to the current allowed affinity mask; changed environmental identity must be recorded. Existing output directories are rejected. Repeating these namespaces is engineering reproducibility, not new independent efficacy evidence. Source verification must pass; do not modify frozen files to make a replay run.

The main48fit/groups require their individual gates; pooled arithmetic never overrides a failedgroup. Scripted controls are a separately frozen action-coverage profile and cannot be pooled with value-policy costs/quality. Read PROOF_AND_SCOPE.md and COST_LEDGER.json before interpreting results. INDEPENDENT_* outputs bind separate reviewer scripts, executed inputs and partial reviewer costs.
