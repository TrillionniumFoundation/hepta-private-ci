# Reproduce the HCSN task-value study

This is a CPU research implementation. The source and every training/data file
are bound by `results/study001/protocol.json`. The registered matrix contains
168 jobs and seeds 31031, 31067 and 31103. Do not overwrite the published runs
or reinterpret a rerun as an untouched test confirmation.

## Runtime

The executed training environment was CPython 3.12.14, PyTorch 2.9.1+cpu and
NumPy 1.26.4. The independent numerical environment used NumPy 2.3.5 and SciPy
1.17.0; combined torch/SciPy audits used the training NumPy. Figures used
Matplotlib 3.10.8. `ENVIRONMENT.json` records the actual runtime and resource
limits. There was no GPU or readable RAPL energy counter.

The scripts do not install packages. Provide those environments explicitly and
set `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`. Workers also set
PyTorch intra/inter-op threads to one. Exact CPU timings require comparable
hardware and load; the original host was shared.

## Recover the evidence and actual asynchronous features

From the repository root:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_task_value_v1/artifacts/foundations001/foundations001.json \
  --destination experiments/hcsn_task_value_v1/results
```

The foundation bundle includes numerical validation, original failure records,
the 48-clip actor-disjoint asynchronous features, train-fitted normalization,
source/license manifests, causal-prefix checks and training-only preflights.
Each part is at most 327,680 bytes. Restoration verifies every part, the whole
compressed stream and every member. An existing different file is rejected.
Original media are retrieved only if the frontend is deliberately rebuilt;
the prepared inputs do not require a second download.

The completed training bundle uses the same archive format and is restored by:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_task_value_v1/artifacts/study001/study001.json \
  --destination experiments/hcsn_task_value_v1/results
```

It includes registered jobs, validation selections, full model/Adam/RNG
checkpoints, per-update traces, heldout predictions, access logs, whole-process
meter receipts, failed attempts if any, final analysis and figure data.
`selected.pt` contains project-generated PyTorch serialization; load only the
published, hash-verified files you trust. These checkpoints include the optimizer
and RNG state, unlike earlier model-only NPZ snapshots.

## Numerical and event contracts

The following commands exercise meaningful independent references. Use a fresh
output directory for each audit that writes evidence.

```bash
python -m unittest -v experiments.hcsn_task_value_v1.oracle_tests
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_tail \
  experiments.hcsn_task_value_v1.gradient_audit_tests \
  experiments.hcsn_hx_unified_v3.test_matched_slope
python -m experiments.hcsn_task_value_v1.flow_audit_tests --output /tmp/hcsn_flow_recheck
python -m experiments.hcsn_task_value_v1.experiment_tests --output /tmp/hcsn_event_recheck
python -m unittest -v experiments.hcsn_task_value_v1.async_av_tests
python -m unittest -v experiments.hcsn_task_value_v1.analysis_tests
```

The scalar affine and two-cell QVI validation scripts preserve timestamped
reports. `CONTRACT.md` distinguishes the continuous scalar optimum, finite-grid
own-policy values, and the general two-cell QVI; do not substitute their
boundaries or phase indices without the declared mapping.

## Rerun the registered jobs

Inspect `protocol.json` and `jobs/<id>.json` first. `training.py` verifies every
registered source/data hash before running. For a single registered job, use a
new output and meter path:

```bash
python -m experiments.hcsn_task_value_v1.cost_meter \
  --output /tmp/hcsn_rerun_meter.json --timeout-seconds 1200 -- \
  python -m experiments.hcsn_task_value_v1.training \
  --job experiments/hcsn_task_value_v1/results/study001/jobs/fixed_selective_copy_value_dual_w16_s31031.json \
  --output /tmp/hcsn_rerun
```

The original full invocation was:

```bash
python -m experiments.hcsn_task_value_v1.study register \
  --output experiments/hcsn_task_value_v1/results/study001
python -m experiments.hcsn_task_value_v1.study run \
  --output experiments/hcsn_task_value_v1/results/study001 --workers 3
```

Those paths are now immutable evidence. For a new full run, choose a new study
directory; registration preserves the fixed data seed and source identities.
The training selection rule is minimum validation CE every 32 updates and at
the final/budget step. Test data are loaded only after `selection.json` exists.

## Analyze without changing the question

`analysis.py --execute-after-completion` refuses to read official predictions
until the complete queue has a terminal `execution.json`. Its output directory
must not already exist. The analysis is based on three paired seeds; nominal
95% intervals are not corrected for all reported comparisons. The original
analysis and figures should normally be read from the verified archive rather
than overwritten.

`ECONOMICS_SCOPE.md` defines the ledger. Whole-worker CPU already includes the
training, validation, numerical solves and inference phases. Frontend preparation
is reported once. GPU throughput, measured joules, optimized KV-cache serving
and distributed communication are outside the completed CPU measurement scope.
