# R14 full-domain content cost replay

This experiment fills the missing stress-domain latency measurements in the
frozen R12 content study. It does not retrain models, open a new confirmation
set, change old predictions, or claim that frozen encoders are frozen complete
content backends.

The matrix contains 720 fresh sequential workers: 8 families × 2 training
modes × 3 historical fitting seeds × (7 recall + 8 binding domains). Every
worker measures batch sizes 1 and 32, and reexecutes its 256 historical test
predictions. All eight baseline families are retained. Three fit seeds remain
three fit seeds; neither domains nor timing repeats are independent fits.
Worker order is permuted using fixed seed 1401101 before any measurement, to
avoid running every architecture in a single contiguous time block.

## Measurement boundaries

- Each worker's batch-1 first forward is its first complete model call after
  model and data loading. Batch-32 first forward is only the first call for
  that shape. It is not process-cold after batch 1 has executed.
- Warm timing includes NumPy-to-Torch tensor views, encoder, all recurrent or
  attention steps, readout, and the copied CPU output. Inputs are cached raw
  synthetic arrays; their generation is outside this inner timer.
- Each timing repeatedly uses the fixed first sample or first 32 samples of
  its domain. All samples within a domain have the same shape and elapsed-time
  pattern, and these models have no input-dependent early stopping. This is a
  domain-shape micro-workload for the complete model, not measured average
  latency over all 256 quality-evaluation examples.
- A standard-library parent uses `wait4` to measure each complete fresh
  scientific worker, including import, load, verification, data generation,
  first/warm measurements, instrumentation, full prediction replay, and
  evidence writes. This is not a single production cold-request latency.
- Instrumentation is outside all reported inner timing. It counts actual
  Python calls/elements to the selected `torch.special.log_ndtr`,
  `torch.logaddexp`, `torch.expm1`, and `torch.exp` functions. It does not count
  every equivalent tensor method or every operator in the model. Outputs must
  be bit-identical to the uninstrumented path.
- Parameter, buffer, input, returned history, and output bytes are exact tensor
  accounting. Peak RSS is a complete-process metric. Neither is a full native
  allocator peak or a measured full survival-density storage requirement.
- Device joules, free-boundary optimization, full survival-density state,
  online acquisition, service infrastructure, and optimized GPU execution are
  not established by this historical model. Unsupported fields remain null.

Complete process costs contain the inner stages. Never add nested first/warm
timers to the external process ledger. Independent deployment training
amortization includes the historical common donor once for each independently
deployed candidate pipeline, plus that candidate's fit/selection, divided by
the stated reuse count. The historical receipts are retained and hashed.
The reuse count is total sample requests, not batches. Amortization rows are
emitted only when the request count is at least one full batch and exactly
divisible by the batch size. Batch-32 costs are never assigned to workloads
of only one or ten requests; partial-tail batch costs are unmeasured.
Historical training CPU plus newly measured warm inference CPU is a
cross-period accounting scenario. Training was not rerun. The original
training receipts do not pin an independently verifiable identical CPU/host
configuration, so matching software versions does not turn this combination
into a same-hardware, from-scratch end-to-end benchmark.

The five development workers cost 8.032816 CPU seconds (4.365532 in
development_01 and 3.667284 in development_02). They remain separate from the
720 formal-worker ledger and from per-request deployment amortization.
`formal_01` was superseded before any worker executed after independent review
identified the invalid batch-32 amortization scenarios. `formal_02` is the
corrected active protocol.

## Reproduction

Use the pinned historical CPU runtime: Python 3.12, NumPy 2.3.5, PyTorch
2.8.0+cpu, and ncps 1.0.1. The CfC source hash is verified at startup. The
existing R12 source freeze, all 96 selected checkpoints, all 720 prediction
files, and original training receipts are required at their original paths.

From the repository root, choose an output directory that does not exist:

```bash
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python -m experiments.hcsn_validation_r14_20261101.cost.study prepare \
  --output experiments/hcsn_validation_r14_20261101/cost/results/replay_01
python -m experiments.hcsn_validation_r14_20261101.cost.study run \
  --output experiments/hcsn_validation_r14_20261101/cost/results/replay_01
python -m experiments.hcsn_validation_r14_20261101.cost.study summarize \
  --output experiments/hcsn_validation_r14_20261101/cost/results/replay_01
python -m experiments.hcsn_validation_r14_20261101.cost.report \
  --output experiments/hcsn_validation_r14_20261101/cost/results/replay_01
```

`prepare` freezes source and input identities and preserves source snapshots
before any measurement. `run` executes sequentially and can resume only
completed workers whose retained result hashes match. A failed worker and its
receipt are retained; do not silently rerun over them. Make any scientific
correction explicit and freeze a new output attempt. `summarize` requires all
720 workers, verifies every retained input hash, and reports paired seed rows,
all-domain quality/cost means, descriptive Pareto sets, training amortization,
and the disjoint external process ledger.

## Independent verification and evidence parts

After the complete matrix and summaries exist, run the independent arithmetic
audit (it does not import the model or measurement implementation):

```bash
python -m experiments.hcsn_validation_r14_20261101.cost.audit \
  --output experiments/hcsn_validation_r14_20261101/cost/results/formal_02
```

The delivery helper preserves the cost subtree in gzip-framed parts below the
repository's 500 KiB blob limit, and really restores all members to a fresh
temporary directory before reporting success. The archive does not duplicate
the inherited R12 source/checkpoint/data dependencies outside this subtree.
Existing `archives` directories are excluded to prevent recursive packages or
archiving the package process's still-open receipt log.

```bash
python -m experiments.hcsn_validation_r14_20261101.cost.package_results \
  --output experiments/hcsn_validation_r14_20261101/cost/archives/publication_01
python -m experiments.hcsn_validation_r14_20261101.cost.package_results \
  --restore-index experiments/hcsn_validation_r14_20261101/cost/archives/publication_01/INDEX.json \
  --output /tmp/hcsn-cost-restored
```

The restore destination must not already exist. All part, archive, and member
SHA256 hashes are checked before the restore is accepted; raw original files
remain available in the working tree.
