# Reproduce the R15 campaign

Use the repository revision containing this directory and the pinned R14
parent. Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 and Torch 2.15.0+cpu were
observed in this run. `ENVIRONMENT.json` records the actual CPU/memory and
unavailable GPU/energy sensors. The development runtime adds its installed
Torch package directory to `PYTHONPATH`; a normal environment with these
packages does not need that session-specific path.

Run from the repository root with one BLAS/Torch thread per worker:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
```

Choose a new output directory. Commands deliberately refuse to overwrite
previously registered runs or fit outputs.

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.campaign freeze --output /tmp/hcsn-new-run --updates 768
python -m experiments.hcsn_distribution_content_r15_20261101.online_confirm register --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.train_execution_cross register --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.launch train --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.campaign index --output /tmp/hcsn-new-run
```

Freeze recovery policies before any recovery confirmation:

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run prepare --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.launch recovery_fit --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run freeze --output /tmp/hcsn-new-run
```

Confirmation and analysis:

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.launch evaluate --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.evaluate index --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.online_confirm launch --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.online_confirm index --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.launch recovery_confirm --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run aggregate --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.audit --run /tmp/hcsn-new-run --output /tmp/hcsn-new-run/INDEPENDENT_AUDIT.json
python -m experiments.hcsn_distribution_content_r15_20261101.summarize --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.train_execution_cross launch --output /tmp/hcsn-new-run --workers 2
python -m experiments.hcsn_distribution_content_r15_20261101.train_execution_cross index --output /tmp/hcsn-new-run
```

The complete-cohort online execution addendum is registered separately before
confirmation by `online_confirm.py`. It retains the original recorded outcomes
and reports every discrepancy without rewriting them. Its CLI and registration
are preserved beside the run.

The separate training/execution addendum completes LL/LV/VL/VV for each
primary core. LL, VL and VV reuse the full-cohort actual records; LV executes
the selected light-trained model with the same task/seed's selected value
controller, without recalibration. Its 240 additional conditions are registered
before confirmation but run only after the original five stages and summaries.
This is distinct from the original core-by-value-program A/B/C/D estimand.
The current six-model joint optimization, shared clipping and group checkpoint
selection are described in `publication/ESTIMAND_REVIEW_ZH.md`.

After all six stages, create the complete process-cost ledger with
`publication/runtime_ledger_v2.py build --results PARENT_OF_RUNS --output NEW_LEDGER`.
The recorded run names `formal_01`, `formal_02` and `formal_03` identify this
campaign's retained failed and successful attempts; for this delivered campaign,
use `experiments/hcsn_distribution_content_r15_20261101/results` as that parent.
The ledger intentionally includes discarded training CPU and distinguishes
complete receipts from interrupted-process lower bounds. A fresh independent
reproduction has its own attempt history and must not fabricate these receipts.

For kernel checks, use `law_checks --mode checks`, `--mode complete-successor`
or `--mode benchmark`, each with a new `--output` path. The frozen
`tail_checks.numerics()` computation produced a NumPy-boolean JSON serialization
failure in its auxiliary CLI. `tail_numerics_03.json` preserves the exact external
writer source, its hash and the failed partial output hash; that writer calls
the same computation and converts NumPy scalar values only during JSON output.
The supported corrected entry point is:

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.write_tail_evidence --output /tmp/new-tail-checks.json
```

This added writer calls the frozen numerical function directly. No model,
training or evaluation source changed to handle the auxiliary serialization
failure; the original failed CLI record remains available.

Development01/02 results are pipeline/development evidence, not confirmation.
Source changes and the unsuccessful short-domain profile must remain separate
from the frozen formal candidate. `formal_01` was superseded before confirmation
because development posteriors exposed excessive upper-bound loss. The six-worker
`formal_02` training attempt was interrupted after a worker received SIGKILL
while the 8 GiB cgroup was out of memory. Its receipts and pre-termination CPU
lower bounds are retained. `formal_03` retries with two workers and byte-identical
protocol, source freeze and training-context registration. Neither restart
changed the fit seeds, data, update budget or selection rule. The online addendum
is registered again for the new output directory before confirmation.

Trained checkpoints must be restored with
their own stored core configuration; do not load old generator buffers into a
new physical grid when testing parameter-preserving domain extension.
