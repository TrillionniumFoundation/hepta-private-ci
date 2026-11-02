# Exact addressed-model preparation audit

This additive experiment continues the exact PR #4548 source at
`a793d55c23a7742378b081b162252da428a9fdb2`. The original model and its default
dense propagator are unchanged.

`fused_addressed.py` performs the same FP64 dense matrix exponential after
joining the probability and marked-content generators into one matrix batch.
The last-observed policy indices use a cumulative maximum instead of a Python
loop. The adapter also omits the discounted J/G linear solves and boundary
output because the addressed model never reads them. It preserves every
consumed P/T/remap/initial tensor, the physical process, the model weights and
the content updates. This adapter is specific to `AddressedModel`: the original
`ContentModel` consumes J/G/b and must not use it.

The audit uses two original trained development checkpoints, with exact
upstream bindings in `CHECKPOINT_PROVENANCE.json`. No new checkpoint is selected
by timing results. The independent matrix checks reconstruct physical jumps
using the existing NumPy reference assembler and SciPy expm. Separate causal
edge checks cover deleted observations, all-unobserved sequences, zero elapsed
time and no-marks execution, and compare all consumed matrices and every model
parameter gradient against the original implementation.

`PROTOCOL.json` declares the numerical tolerances, ten complete-model workloads,
four warmups and fifteen randomized interleaved repeats per forward/backward
case. `SOURCE_FREEZE.json` binds the source and checkpoints before the fresh
timing-confirmation seed opens. Development and confirmation are kept separate.
The coordinator published the frozen source at
`5ed625e9bf1328261be468b19ce859bfe5bb06bc` on
`research/hcsn-propagation-perf-20261101` and verified remote source readback
before this timing-confirmation seed opened. The separate
`REMOTE_FREEZE_BEFORE_CONFIRMATION.json` records that handoff. This is a
performance experiment, not a remotely registered new model-quality campaign.

The original campaign used the following commands, from the repository root
with Python 3.12, NumPy, SciPy and CPU PyTorch:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_propagation_perf_20261101.audit development --out NEW_DEV
python -m experiments.hcsn_propagation_perf_20261101.audit freeze
python -m experiments.hcsn_propagation_perf_20261101.audit confirmation --out NEW_CONFIRM
python -m experiments.hcsn_propagation_perf_20261101.contract_checks
python -m experiments.hcsn_propagation_perf_20261101.independent_gradients
```

The freeze and engineering-check commands refuse existing outputs. For a
published checkout, retain its original freeze and reproduce `confirmation`
with a new `--out` directory; the existing freeze verifies source and weights.
The exported numerical helpers can also be invoked independently. Wrap each command with
`experiments.hcsn_four_stage_flow_20261031.meter` to include interpreter startup,
imports and output writes. Inner body CPU is already included in its outer
receipt and must not be added again.

Times include complete model forward or forward plus backward, allocation,
validation and context installation, but exclude data construction and gradient
clearing in both arms. They are shared-CPU measurements using PyTorch 2.6.0+cpu,
so their absolute values must not be compared directly to the old 2.9.0 run.
The all-workload timing gate requires at least 5% median speed improvement in
both modes for every workload. A local gain does not establish that gate.
Neither complete training with optimizer updates, equal-cost model quality,
production tail latency, GPU execution nor energy is measured here.
