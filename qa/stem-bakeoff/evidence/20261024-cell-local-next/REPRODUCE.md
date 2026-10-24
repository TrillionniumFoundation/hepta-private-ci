# Restore and replay the local next-stage evidence

Use the archive/index pairs linked by the final report. The index binds archive
bytes, the manifest, every logical file and the implementation provenance.
Verification establishes byte integrity; it does not grant production authority
or make a previously observed holdout independent. All conditions remain shadow-only.

## 1. Parts and implementation

| Part | Logical contents and purpose |
|---|---|
| A | Cheap image/audio and Granite studies; `calibrated/`, `cheap-features/`, `cohort-metadata/`, Granite `full-source/` and `historical-prefix/`; repair cohort, source recovery, operational datasets/head view, private-gradient and serving evidence. |
| B | EG2 repair prefix/full studies and feature bundles; repair cohort and source-recovery copies needed to interpret them. |
| C | Remaining native-media and operational-EG2 evidence, companion analyses, cost/verification/report closure. Use its final bound logical inventory; its final paths are not assumed here. |
| D | Original media under `media/`; operational protocols, prepared inputs, all execution conditions, logs and environment/acquisition receipts under `operational/`. Installed runtimes and public Git histories must be reacquired from their pins. |

Parts are independent archives with overlapping logical names. Restore each into
a separate new directory; do not overlay parts or replace historical `part-state`
receipts. A/B state snapshots legitimately say that later work was still pending.
The final delivery index/Part C supplies the later closure state.

Read each external index's `provenance.git` for its commit, tree and source hashes.
Use that repository source for the archive tool. For numerical replay, use source
whose hashes match the prepared task's `plan.code_sha256`; later report-only
commits are usable only when these implementation bytes still match.
Commands below were checked against committed CLI definitions; they are not
instructions to rebuild or recompress the delivered archives.

## 2. Verify and restore with the Python standard library

Run from the repository root with Python 3.11 or newer. Archive verification and
restoration need neither NumPy nor PyTorch, and do not execute archived source.
Replace these placeholders with the chosen part's delivered archive/index paths:

```sh
CELL_ARCHIVE=/absolute/path/to/chosen-part.tar.gz
CELL_INDEX=/absolute/path/to/chosen-part.tar.gz.index.json
CELL_RESTORED=/absolute/path/to/new-part-restore
python3 qa/stem-bakeoff/package_cell_local_evidence.py verify \
  --archive "$CELL_ARCHIVE" --index "$CELL_INDEX"
python3 qa/stem-bakeoff/package_cell_local_evidence.py restore \
  --archive "$CELL_ARCHIVE" --index "$CELL_INDEX" --output "$CELL_RESTORED"
```

Repeat for A, B, C and D with different restore destinations. `--output` must
not exist. The tool validates hashes, sizes, member types, paths and counts,
then recreates independent ordinary files even when the package deduplicated
their bytes. A failed restore is incomplete; do not treat its directory as verified.
The manifest/instructions are verified inside the archive; only logical evidence
files are materialized in the restore directory.

Inspect the verified manifest without extracting arbitrary tar members:

```sh
python3 - "$CELL_ARCHIVE" <<'PY'
import json, sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as archive:
    manifest = json.load(archive.extractfile("manifest.json"))
print(json.dumps(manifest["provenance"]["roots"], indent=2))
print("logical files:", manifest["file_count"])
print("logical bytes:", manifest["logical_bytes"])
PY
```

## 3. Relocate paths without changing sealed evidence

`provenance.roots` maps **archive-relative logical path → original experiment
path**. Resolve an old path outside the receipts: choose its longest matching
original root, append the relative suffix to `RESTORED/logical-path`, and verify
the resulting file against its recorded SHA256. An exact file-root match has no
suffix. Consult all part inventories when the dependency is in another part;
overlapping copies are interchangeable only after their byte hashes agree.

Do not edit paths in `study-plan.json`, manifests, source records, calibration
files or seals, and do not insert symlinks or replay outputs into a sealed tree.
Keep any relocation map as a separate new artifact. There is no generic
`--root-map` switch. A tool that reopens historical absolute paths needs an
explicit external resolver or its original path layout; do not bypass its checks.
The direct replay below accepts relocated input paths and leaves every receipt intact.

## 4. Inspect and replay one frozen Head without refitting

Use the recorded numerical environment for a bitwise comparison: the local study
used CPython 3.12.14 and NumPy 2.2.6 with one BLAS/OpenMP thread. Frozen-head replay
needs NumPy only. Pin `numpy==2.2.6` in an isolated environment; the full Encoder
environment is described by the feature/runtime receipts and requirements files.
Set `CELL_PYTHON` to that environment's Python and `CELL_PART_A` to restored A:

```sh
CELL_PYTHON=/absolute/path/to/pinned-environment/bin/python
CELL_PART_A=/absolute/path/to/restored-part-a
CELL_TASK="$CELL_PART_A/calibrated/cheap-audio/audio_animals"
CELL_REPLAY=/absolute/path/to/new-frozen-head-replay
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
PYTHONPATH=qa/stem-bakeoff "$CELL_PYTHON" - "$CELL_TASK" <<'PY'
import json, sys
from pathlib import Path
from cell_calibrated_curve import inventory, verify_prepared
task = Path(sys.argv[1])
frozen = verify_prepared(task / "prepared")
evaluation = task / "evaluation"
seal = json.loads((evaluation / "seal.json").read_bytes())
assert seal == {"schema": "hepta.calibrated-evaluation-seal.v1",
                "files": inventory(evaluation)}
print("prepared runs:", len(frozen["runs"]))
print("unavailable budgets:", frozen["unavailable"])
PY
mkdir "$CELL_REPLAY"
"$CELL_PYTHON" qa/stem-bakeoff/cell_calibrated_evaluate.py \
  --model "$CELL_TASK/prepared/seed-7_n-128/linear" \
  --features "$CELL_TASK/evaluation/features.npy" \
  --identity "$CELL_TASK/evaluation/feature_identity.json" \
  --calibration "$CELL_TASK/evaluation/seed-7_n-128/linear-fresh.calibration.json" \
  --output "$CELL_REPLAY/linear.npz"
"$CELL_PYTHON" - "$CELL_TASK" "$CELL_REPLAY/linear.npz" <<'PY'
import sys
from pathlib import Path
import numpy as np
original = Path(sys.argv[1]) / "evaluation/seed-7_n-128/linear.npz"
with np.load(original, allow_pickle=False) as a, np.load(sys.argv[2], allow_pickle=False) as b:
    for key in ("logits", "probabilities"):
        assert np.array_equal(a[key], b[key]), key
print("bitwise replay passed")
PY
```

This reuses immutable weights and four calibration scalars; it neither trains
nor supplies labels to the replay process. The process still shares the filesystem.
Inspect the task's `evaluation/report.json` for scores, parameter-off/shuffled
controls and original fresh-process checks; `prepared/frozen.json` retains every
training search path and selection/calibration choice. Condition `summary.json`
and the paired-analysis reports retain unavailable budgets and uncertainty scope.

Features are FP32; private Head parameters/calibration arithmetic are FP64.
A matching width is insufficient: checkpoint, preprocessing, feature identity,
tensor hash and source row order must match. Text prefix/full, native media and
cheap features cannot be substituted by relabelling an identity. Operational
head-view aliases preserve full feature bytes but separately bind their text view.
Cross-platform BLAS/runtime differences may prevent bitwise replay; retain the
observed discrepancy and environment rather than rewriting the reference evidence.

## 5. Optional new fit: always a separate repeated-use condition

Only run this when a new fit is intended. It starts a new search/calibration run;
it is not necessary to inspect or replay the sealed results. Use a nonexistent
study output, keep all original parts unchanged, and designate the now-observed
holdout as repeated-use. The following example uses already restored MFCC features:

```sh
CELL_NEW_STUDY=/absolute/path/to/new-repeated-use-study
"$CELL_PYTHON" qa/stem-bakeoff/run_calibrated_cells.py \
  --dataset "$CELL_PART_A/cohort-metadata/audio.json" \
  --features "$CELL_PART_A/cheap-features/audio" --output "$CELL_NEW_STUDY" \
  --condition repeated_use_cheap_MFCC80 \
  --holdout-use legacy_repeated_use_diagnostic --phase prepare
"$CELL_PYTHON" qa/stem-bakeoff/run_calibrated_cells.py \
  --dataset "$CELL_PART_A/cohort-metadata/audio.json" \
  --features "$CELL_PART_A/cheap-features/audio" --output "$CELL_NEW_STUDY" \
  --condition repeated_use_cheap_MFCC80 \
  --holdout-use legacy_repeated_use_diagnostic --phase evaluate
```

Keep the 8/32/128 protocol and unavailable records intact; diagnostic 122 is its
separately preregistered supplement, never a renamed 128. Source/model acquisition,
media encoding and operational command execution are separate, costly activities:
follow their pinned protocols/runtime receipts and write new artifacts if repeated.
None is triggered by archive restoration or frozen-head replay.

## 6. Replay a relocated cost ledger

Clone the registry into a **new descriptor outside sealed trees**, changing only `datasets[*].path` and `receipts[*].path`.
Resolve paths through verified `manifest.provenance.roots`, require actual `manifest.files` membership, and verify each candidate file against the entry's unchanged `sha256`.
Keep every JSON-pointer key, binding edge, other registry value and historical source path inside sealed receipts unchanged. Use a fresh ledger output:

```sh
python3 qa/stem-bakeoff/cell_cost_ledger.py --registry NEW_DESCRIPTOR --output NEW_LEDGER
```

The metadata-only portability proof used the then-incomplete draft registry: 259 ordinary copied inputs, with all 21 cost-semantic output fields equal. Receipt `portability-replay.json` has SHA256 `e99726c10547db76f0a1c2db54fa822b86ea96d4d09cce5df77c4583203c5de6`; it is not a final full-archive restoration claim.
Expected provenance differences are `registry_sha256`, `artifact_bindings`, `artifact_file_bytes` and location fields in `dataset_artifacts`. Compare every other output field exactly; do not claim byte-identical whole JSON after relocation. No wrapper or source modification is needed.
