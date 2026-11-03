# V4 fitted semantic router interface

The implementation routes the six numeric intents `at`, `previous`, `change`,
`mean3`, `range3`, `peak3`, or abstains. Primitive definitions and type signatures
are supplied by the numeric graph. This router does not invent new memory types,
grant source permissions, or bypass a per-hop owner check. Public development
currently fails the semantic qualification gate; see `DEVELOPMENT_ROUTING.md`.

## Training and serving

```python
from v4.routing_study import DEFAULT_CONFIG, RoutingBundle, train_routing

bundle, receipt = train_routing(
    pinned_encoder,
    training_rows,
    selection_rows,
    output_directory,
    seed=8011,
    source_commit=exact_frozen_commit,
    config=DEFAULT_CONFIG,
)

loaded = RoutingBundle.load(
    output_directory,
    pinned_encoder,
    expected_primary_sha256=receipt["primary_sha256"],
)
decisions = loaded.decisions([
    {
        "utterance": "Read the archived series Q measurement for 2018-06.",
        "series_name": "series Q",
        "date": "2018-06",
    }
])
```

The actual serving inputs are only `utterance`, `series_name`, and `date`.
Normalization replaces the supplied entity/date identity strings and preserves
the remaining whole request. It does not use an intent lexicon or read
`intent`, `family`, `operator`, `result_type`, `provenance_offsets`, source values,
or expected graph outputs. No natural-language extraction of the explicit date
or entity handle is claimed.

Training and selection rows additionally require unique `id`, `intent` and exact
`partition` values `train` / `selection`. Optional `family` is a training
balancing group; `risk_group="near"` supplies the selection risk stratum. These
are supervision/grading fields and are not deployment features. Every class
requires training examples. Identical normalized train/selection text is refused.

`RouteDecision` exposes `route` (intent or `None`), `raw_route`, `confidence`,
`margin`, and `disposition`. `evaluate_routing(bundle, rows)` evaluates all retained
candidates without changing them and returns saved per-query records plus metrics.
The primary is fixed by selection; development/held metrics cannot select it.

## Artifact contract

Minimal deployment uses exactly:

```text
PRIMARY.json
selected/manifest.json
selected/weights.bin
selected/features.json
```

The externally supplied SHA binds `PRIMARY.json`; its artifact binding pins the
feature file, model manifest and encoder. The model manifest binds all numeric
arrays and their bytes/SHA, classes, architecture, thresholds, frozen encoder,
feature identity, source commit, and train/selection digests. The loader consumes
the checked parameter/feature bytes and does not read training corpora or cached
features. The source commit must be a complete 40-character hash; explicitly
uncommitted development runs record their parent identity separately.

`memory-cell-v4.semantic-model.v1` supports `linear`, `mlp64`, `factorized64`, and
`attention32`. The first three use `memory-cell-v4.semantic-features.v1`; attention
uses `memory-cell-v4.semantic-token-features.v1`. All learned parameters are stored
in little-endian float64. Attention additionally specifies frozen contextual
state → float16 → float64 → per-token L2, relative position and its square, four
attention heads, 32 projection dimensions, and 64 hidden dimensions. Its trained
six-way intent and binary supportedness probabilities form the seven-way output.

The encoder must be the pinned v2 MiniLM source manifest with actual byte/hash
verification. Contextual extraction uses the existing tokenizer and ONNX session,
native batch one, with no additional dependency. The sequence/contextual path
refuses requests exceeding 128 wordpieces. Dense/hybrid inference retains the v2
encoder's truncation behavior. A single contextual evaluation can
also produce the original masked-mean dense feature with identical arithmetic.

## Evidence and cost fields

All candidates are saved under `candidates/{id}` before primary selection. The
selected copy is separately retained and charged. `selection-receipt.json` records
the complete candidate grid, actual optimizer/example counts, calibrated decisions,
all artifacts, corpus/cache bytes, real encoder calls and timing, and save/load
parity. `PRIMARY.json` is included in minimal deployment bytes.

Dense/hybrid arrays are saved as non-pickled NumPy arrays. Sequence cache files
contain concatenated float16 states and int64 offsets; they are bounded by the
128-token limit and are research artifacts. They are not a semantic answer table,
are unnecessary to serve, and are not subtracted from training/storage costs.
Actual observed example counts are a declared candidate tie break, not FLOPs;
full process RSS, transient activation peaks, energy and currency are not measured
by serialized byte accounting.

## Local commands

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m unittest discover \
  -s tests -p 'test_semantic*.py' -v

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m v4.routing_development \
  --base /absolute/path/to/pinned/all-MiniLM-L6-v2 \
  --source-commit FULL_PARENT_OR_FROZEN_COMMIT \
  --output results/development/NEW_DIRECTORY

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m v4.routing_development_audit \
  results/development/EXISTING_RUN --output validation/NEW_AUDIT.json
```

The development runner permits only 8011/8017 and has no independent-v4-holdout
reader. It copies the routing source modules before training and seals outputs.
The read-only audit verifies every sealed byte and emits outside the run. Root's
integrated runner owns formal seeds, full-source freezing, independent language
materialization, graph execution, memory backends, and fresh-process serving.

## Independent selected-router execution replay

After a complete unified run has been sealed, run:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m v4.semantic_replay_audit \
  results/SEALED_UNIFIED_RUN --base /absolute/path/to/pinned/all-MiniLM-L6-v2 \
  --output validation/NEW_SELECTED_REPLAY.json
```

Add `--allow-development` only for a sealed unified development run. The audit
first verifies its entire seal, source snapshot, protocol phase, and seeds. For
formal runs the active inference/audit source must also match the frozen bytes.
It then reads each seed's three-field unlabeled serving requests, independently
loads only `deployed-router`, runs the actual pinned ONNX session and saved head,
and requires every `RouteDecision` field to match the historical fresh-process
output exactly, with no numerical tolerance. It hashes loaded parameters before
and after inference, directly counts native `session.run` invocations, and records
the additional wall time and process CPU time separately from research training.

The output must be a new file outside the sealed run. No fitting, calibration,
candidate selection or source-value lookup occurs in this replay. It complements
the separate joint audit's mathematical checks of targets, graph traces and
metrics; neither an identical replay nor an intact seal waives quality failures.
The process can access the shared filesystem, so OS-level isolation is not claimed.

The public development core self-check is retained in
`validation/selected-router-replay-public-audit.json`. It loads the two fifth-round
selected artifacts, creates new independent-process outputs for their 140 public
development requests, and replays all 140 decisions exactly. Those two passes use
280 additional native encoder calls, recorded as audit work with no new fitting.
This fixture explicitly does not claim the complete unified-run outer seal check;
the same replay auditor must still be run on root's sealed integrated run.
