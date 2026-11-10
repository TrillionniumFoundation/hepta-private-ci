# Original42 / C1 descriptive resource analysis

This read-only analysis derives resource tables from the frozen original42 and
C1 curve export. The inputs, three wall-budget cutoffs and all interpretation
rules are explicit in `PLAN.json`. The analysis plan was written after terminal
scores were known; it is not a prospective scientific confirmation plan.

The tool pins the exact exported curves, complete baseline audit results, core
table and six-HCSN terminal summary by SHA256. It checks all 49 report bindings,
recomputes 2,969 confusion matrices, verifies original and C1 clock intervals,
and retains all two-LR / three-seed rosters in both original-only and C1 views.
Missing observations stay missing. Strict-best ties retain the first complete
epoch. Before-training evaluations are eligible only in the budget table.

`RESULT.json` records every selected point and all candidate costs. `POINTS.json`
keeps compact copies of every original observation. Independent review of the
first result used a separate implementation and exact rational CM arithmetic;
its receipt and the complete frozen input archive are archived separately.

## Run

Supply exact local paths to the six authenticated input files and an output
directory that does not already exist:

```sh
python -B analyze_resources.py \
  --curves /absolute/path/to/CURVES.json \
  --plan /absolute/path/to/PLAN.json \
  --baseline-v1 /absolute/path/to/v1-RESULT.json \
  --baseline-v2 /absolute/path/to/v2-RESULT.json \
  --hcsn-summary /absolute/path/to/HCSN-TERMINAL-SUMMARY.json \
  --core-table /absolute/path/to/CORE_TABLE.json \
  --output /absolute/path/to/new-output
```

Run `python -B -m unittest -v test_analysis` from this directory for the five
focused behavior checks. The full real-data verification, including reference
table reconciliation, runs during analysis. It does not import Torch or execute
a model. The CM checks cannot reconstruct NLL, calibration or Brier scores.

## Interpretation

The budget axis is active per-fit wall time, including initialization and
diagnostics. All six candidates are charged; C1 costs are explicitly separate.
C1 cumulative CPU remains a lower bound. Complete-attempt RSS is a prefix upper
bound, not a target-time measurement or GPU memory. Controller scopes overlap
fit costs. Historical tuning, audits, transfers and energy are not silently
folded into or inferred from these fit-process tables.

A reproducible D metric does not establish adequate training, whole-trajectory
numerical accuracy, an independent confirmation result, or overall CI success.
