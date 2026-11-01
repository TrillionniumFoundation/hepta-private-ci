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
python -m experiments.hcsn_distribution_content_r15_20261101.launch train --output /tmp/hcsn-new-run --workers 6
python -m experiments.hcsn_distribution_content_r15_20261101.campaign index --output /tmp/hcsn-new-run
```

Freeze recovery policies before any recovery confirmation:

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run prepare --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.launch recovery_fit --output /tmp/hcsn-new-run --workers 6
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run freeze --output /tmp/hcsn-new-run
```

Confirmation and analysis:

```bash
python -m experiments.hcsn_distribution_content_r15_20261101.launch evaluate --output /tmp/hcsn-new-run --workers 6
python -m experiments.hcsn_distribution_content_r15_20261101.evaluate index --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.launch recovery_confirm --output /tmp/hcsn-new-run --workers 6
python -m experiments.hcsn_distribution_content_r15_20261101.recovery_run aggregate --output /tmp/hcsn-new-run
python -m experiments.hcsn_distribution_content_r15_20261101.audit --run /tmp/hcsn-new-run --output /tmp/hcsn-new-run/INDEPENDENT_AUDIT.json
python -m experiments.hcsn_distribution_content_r15_20261101.summarize --output /tmp/hcsn-new-run
```

The complete-cohort online execution addendum is registered separately before
confirmation by `online_confirm.py`. It retains the original recorded outcomes
and reports every discrepancy without rewriting them. Its CLI and registration
are preserved beside the run.

For kernel checks, use `law_checks --mode checks`, `--mode complete-successor`
or `--mode benchmark`, each with a new `--output` path. The frozen
`tail_checks.numerics()` computation produced a NumPy-boolean JSON serialization
failure in its auxiliary CLI. `tail_numerics_03.json` preserves the exact external
writer source, its hash and the failed partial output hash; that writer calls
the same computation and converts NumPy scalar values only during JSON output.
No model, training or evaluation code was changed after the campaign freeze
to handle this auxiliary serialization failure.

Development01/02 results are pipeline/development evidence, not confirmation.
Source changes and the unsuccessful short-domain profile must remain separate
from the frozen formal_02 candidate. Trained checkpoints must be restored with
their own stored core configuration; do not load old generator buffers into a
new physical grid when testing parameter-preserving domain extension.
