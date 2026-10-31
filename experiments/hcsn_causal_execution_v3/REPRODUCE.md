# Reproduce and restore the causal-execution follow-up

Run commands from the repository root. This namespace extends the exact baseline
`c5e159ec6c5ba174b36debacad166da635c57d48` (PR #4519). The imported dependency
sources remain in their original experiment namespaces. Their Git blob identities
are recorded in `provenance/MATERIALIZED.json`; do not silently substitute a newer
branch's kernels or content models.

The measured training/runtime interpreter has Python 3.12, PyTorch 2.8.0+cpu,
NumPy 2.3.5 and SciPy 1.17.0. The archive utility uses only the Python standard
library. Use one thread for the experiments:

```bash
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
```

The archived receipts retain the actual machine, paths and costs of their original
run. A new host's timings are new measurements. This work does not infer joules
from CPU time or FLOPs.

## Restore this round's evidence

`archive_v3.py` reads the manifest, verifies every 192-KiB-or-smaller binary part,
the assembled compressed archive, and every declared member before writing.
It rejects traversal, absolute paths, duplicate members, symlinks, hardlinks,
undeclared members and existing files with different bytes. Identical existing
files are accepted without rewriting them. Restored paths are relative to this
experiment namespace; they already start with `results/`.

```bash
python -m experiments.hcsn_causal_execution_v3.archive_v3 restore \
  --manifest experiments/hcsn_causal_execution_v3/artifacts/memory001/memory001.json \
  --destination experiments/hcsn_causal_execution_v3

python -m experiments.hcsn_causal_execution_v3.archive_v3 restore \
  --manifest experiments/hcsn_causal_execution_v3/artifacts/av_probe001/av_probe001.json \
  --destination experiments/hcsn_causal_execution_v3

python -m experiments.hcsn_causal_execution_v3.archive_v3 restore \
  --manifest experiments/hcsn_causal_execution_v3/artifacts/mechanism_final001/mechanism_final001.json \
  --destination experiments/hcsn_causal_execution_v3

python -m experiments.hcsn_causal_execution_v3.archive_v3 restore \
  --manifest experiments/hcsn_causal_execution_v3/artifacts/stream001/stream001.json \
  --destination experiments/hcsn_causal_execution_v3
```

| Bundle | Members | Parts | Compressed bytes | Restored directories |
| --- | ---: | ---: | ---: | --- |
| `memory001` | 188 | 24 | 4,577,784 | `results/memory`, `results/memory_clock_repair` |
| `av_probe001` | 743 | 16 | 3,066,048 | `results/av_probe` |
| `mechanism_final001` | 335 | 39 | 7,659,652 | `results/mechanism` |
| `stream001` | 312 | 3 | 481,300 | `results/stream`, `results/costs`, development snapshots |

Complete hashes and byte inventories are in each bundle's manifest. Each
`RESTORE_VERIFICATION.json` records a successful restoration into a fresh
temporary directory, a second byte-by-byte hash comparison against the retained
raw originals, and packaging/verification costs. The temporary verification
directories were removed after comparison; raw experiment results were preserved.

The final mechanism bundle includes every file under `results/mechanism`,
including its 63-worker formal run, all action/prediction records, fitted model
parameters, auditor source and the final report. `PACKAGING_HISTORY_MECHANISM.json`
retains the cost of a superseded 334-file snapshot taken just before the final
report arrived. Only `mechanism_final001` is the complete mechanism deliverable.
The streaming bundle includes `results/stream/formal002`, the unused old
`formal001` protocol, the outer process receipt/log, and
`development/stream_preexecution_review01` source snapshots. It also includes
the three `results/costs` files: a complete fresh-process AV fitting/selection/
evaluation receipt and the 732-file exact model/prediction replay comparison.
Those are separate cost components, not additional streaming worker receipts.

## Restore exact inherited inputs and checkpoints

The new bundles do not duplicate the inherited neural checkpoints or original
media. The baseline already publishes the necessary evidence archives.

Prepared causal audio/video observations come from the baseline foundations
archive. Its complete compressed SHA-256 is
`cfd7cd8a1f50635bfac30f1c32def69493b7c46a523f683d32f964a31a062adb`.

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_task_value_v1/artifacts/foundations001/foundations001.json \
  --destination experiments/hcsn_task_value_v1/results
```

The prepared input arrays then live under
`experiments/hcsn_task_value_v1/results/async_frontend001/data/`.
Restoring these arrays does not repeat original audio/video decoding or establish
fresh actor confirmation.

The 18 neural checkpoints used by the memory diagnostic are the `selected.pt`
files for Copy/MQAR, fitted seeds 81031–81033, and families `shared`,
`two_gate_frozen_shared_updates256`, and `analytic_frozen_shared_updates256`.
Each checkpoint's SHA-256 and selected step are pinned in the memory protocol.
They are restored from the baseline `content001` archive, complete compressed
SHA-256 `a58534aec1c9bcad5c7cda65659c4d6f03bfb372c7b442767ee0a0fe0d90bd7f`:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/content001/content001.json \
  --destination experiments/hcsn_mechanism_content_v2/results/content001
```

The original manifest contains 2,448 members and 183 parts. Its 47,716,564
compressed bytes restore 149,121,856 file bytes. These historical training and
selection records remain part of the provenance; follow-up evaluation cost does
not replace or erase their cost.

## Recompute the independent raw-record audits

```bash
python - <<'PY'
import json
from pathlib import Path
from experiments.hcsn_causal_execution_v3.memory_audit import audit as memory_audit
from experiments.hcsn_causal_execution_v3.memory_clock_audit import audit as clock_audit
root = Path("experiments/hcsn_causal_execution_v3/results")
print(json.dumps(memory_audit(root / "memory"), indent=2))
print(json.dumps(clock_audit(root / "memory_clock_repair"), indent=2))
PY
python -m unittest experiments.hcsn_causal_execution_v3.memory_probe_tests
python -m unittest experiments.hcsn_causal_execution_v3.archive_v3_tests
```

The memory auditors intentionally refuse to replace an existing audit receipt.
The commands above call the pure `audit(Path(...))` functions and print their
returned dictionaries without changing archived receipts. The archived initial memory-audit
failure and its corrected accumulation check remain available under
`results/memory/audit_history/`.

## Run fresh memory diagnostics

Choose new, nonexistent output directories. `--prepare` binds the actual source
and checkpoint hashes and freezes the matrix before any new predictions. It
recreates a local plan rather than executing archival absolute paths.

```bash
python -m experiments.hcsn_causal_execution_v3.memory_probe \
  --output /new/output/memory \
  --checkpoint-root experiments/hcsn_mechanism_content_v2/results/content001/jobs --prepare
python -m experiments.hcsn_causal_execution_v3.memory_probe --output /new/output/memory --run
python -m experiments.hcsn_causal_execution_v3.memory_clock_repair \
  --output /new/output/clock --memory /new/output/memory --prepare
python -m experiments.hcsn_causal_execution_v3.memory_clock_repair --output /new/output/clock --run
```

The clock intervention remains explicitly post-diagnostic and exploratory even
when numerically reproduced. A rerun does not turn reused data into confirmation.

## Run the common AV feature probe

```bash
python -m experiments.hcsn_causal_execution_v3.av_probe --output /new/output/av_probe
```

The probe freezes its candidate families and regularization grid, uses training
for fitting and validation for selection, then opens the old actor-disjoint test
split once. The old test actors have been observed in earlier project work; this
is still exploratory evidence. All attempted candidates and selection records
must be retained. Consult `AV_RESULTS.md` for feature sufficiency and attribution.

## Freeze and execute mechanism and streaming reruns

Use the exact final source version and new output directories. The mechanism
worker matrix fits each ordinary baseline once and meters each arm in a separate
fresh process; do not replace its primary comparison with a subset of workers.

```bash
python -m experiments.hcsn_causal_execution_v3.mechanism_followup freeze \
  --output /new/output/mechanism --episodes 128
python -m experiments.hcsn_causal_execution_v3.mechanism_followup execute \
  --plan /new/output/mechanism/PROTOCOL.json
python -m experiments.hcsn_causal_execution_v3.mechanism_followup analyze \
  --plan /new/output/mechanism/PROTOCOL.json
python experiments/hcsn_causal_execution_v3/results/mechanism/audit_followup.py \
  /new/output/mechanism/PROTOCOL.json
```

All four formal mechanism commands completed successfully in the archived run.
Its `POSTPROCESS_DISPLAY_FAILURE.json` records a later malformed inline console
display command; it was not a model-worker, analyzer or raw-auditor failure.
The mechanism raw auditor creates `RAW_AUDIT.json` with exclusive creation and
must be run against a new reproduction directory where that receipt does not
already exist. It does not silently overwrite an archived audit.

## Reproduce the final streaming study and its complete process receipt

The final pre-execution source commit is
`58734d86b5dd8436f56a210632fca1acf8f3ea6c`. Its formal run is
`results/stream/formal002`. The earlier protocol and development source
snapshots are retained for provenance; they were not the final executed matrix.

Restore the AV probe bundle and inherited prepared observations first. The
streaming study consumes the exact frozen ordinary selected encoders in
`results/av_probe/{async_av,av_binding}/selected_encoder.npz`. It does not retrain
or select a different encoder during the stream experiment.

Use a new study path **inside this namespace** so the independent auditor can
relocate recorded namespace paths on another checkout. The process meter uses
Linux `wait4`; this requirement is separate from the platform-independent
standard-library archive utility. The Python interpreter below must import the
tested PyTorch dependencies, or pass the corresponding interpreter explicitly
as `--training-python` in the measured command.

```bash
python -m experiments.hcsn_causal_execution_v3.stream_study freeze \
  --output experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001

python - <<'PY'
import sys
from pathlib import Path
from experiments.hcsn_causal_execution_v3.process_meter import measured
study = Path("experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001").resolve()
measured([
    sys.executable, "-m", "experiments.hcsn_causal_execution_v3.stream_study",
    "execute", "--output", str(study), "--training-python", sys.executable,
], study.parent / "STUDY_PROCESS_RECEIPT.json", Path.cwd())
PY

python -m experiments.hcsn_causal_execution_v3.stream_audit \
  --study experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001 \
  --output experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001/INDEPENDENT_AUDIT.json

python -m experiments.hcsn_causal_execution_v3.stream_study analyze \
  --output experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001 \
  --destination experiments/hcsn_causal_execution_v3/reruns/stream_reproduction/formal001/RECOMPUTED_SUMMARY.json
```

`execute` already writes `SUMMARY.json`; `analyze --destination` demonstrates a
separate recomputation without overwriting it. The independent audit verifies
the enclosing process receipt in the study's parent directory, which is why the
outer `measured(...)` call is part of the reproduction. Do not add its CPU time to
the sum of the 26 inner worker CPU receipts: waited descendant costs are already
included in the outer receipt. Keep the complete AV-fitting receipt separate.

The final audit verified 24 result files, 12,575 action records, 26 inner workers
and 36 fresh-process episode restarts. Both tasks selected **READ all** as the
only validation-eligible policy. This run establishes causal access and restart
equivalence; it establishes no saved encoder calls or same-quality economy.
Repeated timing runs reuse the same examples and are not extra independent
quality observations. Original media decoding, live communication, physical
sensors and device joules were not measured.
