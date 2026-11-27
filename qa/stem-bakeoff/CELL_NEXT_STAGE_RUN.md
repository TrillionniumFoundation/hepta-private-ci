# Reproduce the shared-encoder / small-Cell study

This research harness evaluates immutable shared features, private learning,
source recovery and serving scale separately. It retains `DENY_ALL` authority;
it does not promote a model into the native production runtime. The native
`SharedEncoderOwnerV1` / `CellHeadV1` ownership boundary remains unchanged.

## Evidence and interpretation

The dated evidence directory contains the compact result and publication index.
The separately delivered data archive contains all original features, fitted
heads, predictions, controls, source payloads, queue state and integrity receipts.
Its external index binds the archive SHA-256, immutable Git commit and tree.
Repository source and public checkpoint weights are kept out of that archive.
The raw Parquet restores to `upstream/swebench.parquet`; its acquisition receipt
is `dataset/acquisition.json`. Checkpoint receipts restore under
`run/checkpoint-pins`, and public media assets/receipts under `run/media`.

There are 32 correlated, lexically defined repair-shape targets in **one** task
family. Inputs are real SWE-bench issue reports; labels are predicates over the
associated gold patch. Comments and strings can match these predicates. These
are not human-validated root-cause, next-action or repair-success labels. Gold
patches, test patches, hints and pass/fail tests never enter the encoder input.
The chronological, duplicate-group-separated cohort contains 1,361 training,
454 calibration and 456 holdout events. Unknown foundation pretraining overlap
remains a limitation. Physical copies at 64/256/1,024 Cells are not additional
independently learned tasks.

The original 192-token budget is deliberately preserved in the recorded result.
The separate token audit quantifies truncation. Do not attribute weak scores to
an encoder bottleneck without testing input coverage and target quality first.
The prior-calibration probe is a separately declared post-hoc diagnostic; it
does not replace the original learning curves or establish a new model winner.

## Environment

The recorded run used Linux x86-64, Python 3.12, CPU FP32, PyTorch 2.10.0+cpu and
torchvision 0.25.0+cpu. Install the two Torch packages from the official CPU
index, then install `requirements-cell-study.txt` in a fresh virtual environment.
The exact feature receipts additionally record the runtime and tokenizer
versions. Plot rendering is optional and used matplotlib 3.10.8.

Run the examples from `qa/stem-bakeoff`. Set `CELL_DATA` to a fresh absolute
restoration path, `CELL_REPLAY` to a different new output path, and `CELL_PYTHON`
to the virtual environment's Python. Use single-threaded BLAS for head training:

```sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

These variables do not replace system home or tool configuration directories.
Feature extraction explicitly sets four Torch threads; routing uses one thread.

## Verify and restore the sealed data

Check out the exact code commit from the supplied evidence index first. The
archive is a deduplicated object store; use the verifier to restore ordinary
files instead of treating the object names as the experimental directory tree.

```sh
"$CELL_PYTHON" package_cell_evidence.py verify \
  --archive "$CELL_ARCHIVE" --index "$CELL_INDEX"
"$CELL_PYTHON" package_cell_evidence.py restore \
  --archive "$CELL_ARCHIVE" --index "$CELL_INDEX" --output "$CELL_DATA"
```

Restoration requires a new directory. Each logical file is checked against the
manifest; no symlinks or hardlinks are created. Original absolute paths in
receipts are provenance and are not rewritten. Both original task seals and
queue/finalization inventories must verify. Do not suppress unexpected files,
replace a failing seal or regenerate a manifest to conceal a changed input.

## Replay learning without downloading an encoder

The restored `run/granite97m/features` and `run/embeddinggemma2/features` contain
the measured global feature matrices. The dataset, source rows and every head
remain available independently of the original model process.

```sh
"$CELL_PYTHON" real_cell_study.py \
  --dataset "$CELL_DATA/dataset/dataset.json" \
  --features "$CELL_DATA/run/granite97m/features" \
  --source-report "$CELL_DATA/run/source-recovery/report.json" \
  --source-path "$CELL_DATA/run/source-recovery/sources.jsonl.gz" \
  --output "$CELL_REPLAY/granite97m"
```

Repeat with `embeddinggemma2`. Each study fixes seeds 7/17/29, balanced distinct
training groups at 8/32/128 examples, 200 optimizer steps, learning rate 0.02,
L2 0.001, residual rank 8 and a 100,000-private-parameter ceiling. It evaluates
exact, lexical, dense and prototype baselines plus linear, gated and residual
heads, including disabled/shuffled parameters and fresh-process reloads. The
finalization actually trains 32 more heads through the durable queue and reopens
them in another process. Reuse `--resume` only for a compatible recorded plan;
completed task directories are immutable.

The original `run/source-recovery` provides 2,271 byte-exact source reads and
stale/missing-version negatives. It addresses a source by identity and revision;
it is not an evaluation of semantic retrieval. Regeneration uses
`source_recovery_probe.py run --dataset ... --parquet ... --acquisition ...
--output NEW_DIRECTORY` with the archived raw Parquet and acquisition receipt.

## Regenerate encoder features

The dataset acquisition pins SWE-bench revision
`e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6`. To regenerate preprocessing, pass
the raw Parquet and its acquisition receipt to `prepare_repair_cohorts.py
--input ... --acquisition ... --output NEW_DIRECTORY`.

Obtain only the exact checkpoint files listed in the successful acquisition
receipts, subject to their upstream terms. Extra download/cache files invalidate
the strict inventory. The pinned checkpoints are:

| Candidate | Upstream revision | Extracted text width |
|---|---|---:|
| `ibm-granite/granite-embedding-97m-multilingual-r2` | `835ad14087e140460703cf0fae09f97d469d65c2` | 384 |
| `google/embeddinggemma-2` | `914f7f89142e33e77833254d9c9b90c3cef7303b` | 768 |

```sh
"$CELL_PYTHON" real_cell_features.py --candidate granite97m \
  --dataset "$CELL_DATA/dataset/dataset.json" \
  --snapshot "$CELL_GRANITE_SNAPSHOT" --acquisition "$CELL_GRANITE_RECEIPT" \
  --batch-size 16 --max-tokens 192 --threads 4 \
  --output "$CELL_REPLAY/granite-features"
```

Use `embeddinggemma2_740m` with the EG2 snapshot for the other candidate. The text
profile loads the text tower; full multimodal storage is reported separately.
An export uses one shared owner, one forward per batch and no target labels.
Global features, optional native local tokens, source revision/time and all
encoder/preprocessing/feature identities use `SharedFeatureEncoder`. The EG2
audio profile selects eager audio attention while keeping supported text/vision
SDPA. Missing native temporal/patch locations remain explicitly unavailable.

The exact original public-image/audio smoke scripts are preserved unchanged in
`evidence/20261023-cell-next-stage/source/`. They contain original machine paths;
adapt paths in a separate replay copy. Their receipts measure actual forwards,
native token retention and equal global outputs, not multimodal task accuracy.

## Analysis and serving comparisons

```sh
"$CELL_PYTHON" summarize_cell_study.py \
  --dataset "$CELL_DATA/dataset/dataset.json" \
  --granite-study "$CELL_DATA/run/granite97m/study" \
  --eg2-study "$CELL_DATA/run/embeddinggemma2/study" \
  --output "$CELL_REPLAY/comparison"
"$CELL_PYTHON" logical_routing_probe.py \
  --dataset "$CELL_DATA/dataset/dataset.json" \
  --features "$CELL_DATA/run/granite97m/features" \
  --study "$CELL_DATA/run/granite97m/study" \
  --repeats 20 --output "$CELL_REPLAY/granite-routing"
```

The comparison uses 2,000 paired source-group bootstrap draws, averaging seeds
within each fixed target. Correlated tasks/seeds are not independent trials.
The serving probe retains the original 16 input rows, 32 trained states and
physical top-16 decisions, and adds same-process all-physical, unique-top-16 and
all-unique-with-fanout measurements. Deduplication requires the same task,
complete learned-state digest and feature identity. Distinct private learning
states stay distinct; a new state requires a new serving snapshot. The default
all-unique path preserves complete routing coverage and exact physical outputs.
Selective top-16 retains measured recall limitations.

`cell_prior_calibration_probe.py` takes `--dataset`, `--sealed-root` (the restored
`run` directory), `--features-root` (also `run`) and `--output`. It keeps all
576 inherited n=128 heads unchanged, fits calibration-only priors/temperatures,
then evaluates holdout once. Constant-prior accuracy must be read alongside
balanced accuracy and positive recall.

`audit_cell_token_budget.py` takes `--dataset`, `--granite`, `--eg2` and `--output`;
it tokenizes without model forwards or learning. `render_cell_study.py` takes
`--comparison`, `--granite`, `--eg2` (the three JSON reports) and `--output`.
Plots show descriptive means; inferential intervals stay in the paired report.

## Validation scope

The focused GitHub workflow checks the exact pull-request head and saves logs.
Its NumPy job covers learning, queue, routing, analysis and evidence packaging;
the Torch job covers existing and new real-feature contracts. Local combined
verification records its complete module list and source hashes before/after.
CI queued without an assigned runner is pending, not passed. Neither passing
mechanism tests nor replay parity establishes production task quality.
