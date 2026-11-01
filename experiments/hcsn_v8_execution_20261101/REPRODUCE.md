# Restore, inspect and reproduce

This is a research development delivery. Reproduction does not recover v6 or
turn historical recordings into independent new confirmation objects.

## Runtime and source combination

The executed numerical runtime used Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and
PyTorch 2.9.1 CPU, with one Torch thread for the mechanism campaign. The primary
runtime supplied NumPy/SciPy and an existing read-only environment supplied
Torch. No network package installation was needed. Commands below assume those
libraries are importable from `python3`; substitute the appropriate interpreter.

Use a complete checkout of the published v8 branch, whose parent is
`7b57b61ffd99e7d3920d0bcb771e2c5fcf2b9503`. V3 sources and archive fragments
are inherited at their original repository paths. Do not substitute newer source
files when the frozen hashes differ. The actual local workspace used an exact
partial reconstruction; full repository Rust formatting/CI is a separate gate.

## Restore historical inputs

From the repository root:

```bash
python3 -m experiments.hcsn_v8_execution_20261101.frontend.recover_local \
  --source . --output recovered/v3
```

This uses only already committed original archives. It checks source Git blobs,
27 part identities, both archive identities and all declared members. Existing
different files are rejected. There is no data download, model fit or new-cohort
selection in this step. The recovery specification and original identities are
in `frontend/RECOVERY_SPEC.json`.

## Restore larger new evidence files

Oversized raw evidence is published as genuine gzip transport parts, with
original compressed bytes retained when the input itself was gzip or NPZ.
From the repository root, run:

```bash
python3 experiments/hcsn_v8_execution_20261101/publication/transport.py restore \
  --manifest experiments/hcsn_v8_execution_20261101/publication/MANIFEST.json \
  --destination .
```

The manifest binds every original byte length and SHA256. Additional transport
details are in `publication/README.md`.
Restore before opening the original JSONL/NPZ paths or running the independent
raw audit. Identical already restored bytes may be reused; conflicting files
must not be overwritten.

## Check the executed evidence without fitting again

The main results are directly readable in `REPORT_ZH.md`, `ACCEPTANCE.json`,
`mechanisms/results/development001/SUMMARY.json` and the component READMEs.
After restoration, the independent standard-library auditor can reconstruct the
mechanism findings without importing Torch or the original aggregation code:

```bash
python3 -m experiments.hcsn_v8_execution_20261101.economics.audit_mechanism_records \
  --run experiments/hcsn_v8_execution_20261101/mechanisms/results/development001 \
  --repo . --out /tmp/hcsn-v8-new-independent-audit.json
```

The retained audit passed 133,975 checks over 48 worlds, 1,728 runs and 6,912
outputs. Supplementary record and cost reconciliation is in
`economics/review/REPORT.json`. Independent scientific interpretation and the
posthoc world-block bootstrap are in `frontend/review/`.

## Re-execute components

Every output destination must be new. Existing failed and successful evidence
must remain intact. The outer worker meter can wrap any of the commands below:

```bash
python3 -m experiments.hcsn_v8_execution_20261101.economics.worker_cost \
  --out /tmp/hcsn-v8-new-cost-receipt --timeout 1800 --sample-interval 0.5 \
  -- python3 -m YOUR_COMPONENT_MODULE YOUR_ARGUMENTS
```

See each component's `--help` and README for the exact replay arguments:

- `experiments.hcsn_v8_execution_20261101.frontend.replay`
- `experiments.hcsn_v8_execution_20261101.frontend.causality_check`
- `experiments.hcsn_v8_execution_20261101.scheduler.historical_probe`
- `experiments.hcsn_v8_execution_20261101.scheduler.balanced_binding_replay`

The mechanism CLI is explicit:

```bash
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign prepare --output /tmp/hcsn-v8-new-mechanisms
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign fit --output /tmp/hcsn-v8-new-mechanisms --seed 81101
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign fit --output /tmp/hcsn-v8-new-mechanisms --seed 81103
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign fit --output /tmp/hcsn-v8-new-mechanisms --seed 81107
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign fit --output /tmp/hcsn-v8-new-mechanisms --seed 81109
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign fit --output /tmp/hcsn-v8-new-mechanisms --seed 81113
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign evaluate --output /tmp/hcsn-v8-new-mechanisms
python3 -m experiments.hcsn_v8_execution_20261101.mechanisms.campaign aggregate --output /tmp/hcsn-v8-new-mechanisms
```

Five data/initialization fits are ordinary models. Analytic C/D use one common
physical calibration per world and are not five independent analytic fits.
All original fit families and checkpoint selection records must be retained.
Outputs carry actual execution timing, so the entire result archive is not
expected to be byte-identical after rerunning. The original published bytes
are restored exactly by transport instead.

## Accounting and unresolved gates

Use the enclosing receipt once. Inner fit, evaluation, task and grandchild
timers explain that total and must not be added to it. The full mechanism
campaign is 447.582388 CPU seconds; its seven inner stages total 427.898262
seconds and are already included. Historical AV batch receipts include model
loading, empirical calibration, logical replay, real source-clock replay and
evidence writing; they are not per-inference costs.

Original media decoding, original feature preparation, pretraining, complete
process-family memory and attributable physical energy remain unavailable.
Unknown required costs stay null in both H=20 and H=10,000 accounting. Historical
test data reused for development remain historical. A new crop or pair does not
produce a fresh recording. The unavailable v6 bundles and exact identities are
listed in `REPORT_ZH.md` and the unchanged v7 recovery checker.
