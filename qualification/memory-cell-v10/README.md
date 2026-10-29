# Memory cells: V10 frozen comparisons and native bridge

This package tests new finite, authored inventory memories at 32, 64 and 128
semantic addresses plus the same number of procedure addresses. It leaves the
old `memory-cell-adapters` protocol and formal evidence unchanged. The fixed old
baseline is `0f41c4968eea63727c69e2b979491e94a99a9dbb`.

The encoder is the original pinned multilingual MiniLM ONNX model, frozen at
revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. New weights are trained by
explicit NumPy float32 gradients and Adam. The residual operator is
`z = x + (x A.T) B.T; logits = z H.T + b`. With a trainable head it is still an
affine map. This is actual optimization and persisted parameter memory, but it
is **not Transformer fine-tuning**. The independently trained linear control
is therefore essential, as are source and canonical-feature storage costs.

## Frozen comparison

`PROTOCOL.json` fixes seeds 1741/1742/1743, values, capacity, presentations,
optimizer settings, independent wording groups and decision rules before a
formal fit. `SOURCE_MANIFEST.json` is generated only after development checks.
The controller publishes those bytes before supplying the remote commit to
the runner. The runner verifies local hashes; it explicitly does not claim
to independently authenticate the remote GitHub commit.

```bash
python qualification/memory-cell-v10/freeze_source.py --write
# Publish and verify the source manifest and every listed file first.
python qualification/memory-cell-v10/run.py \
  --encoder-dir /absolute/path/to/pinned-encoder \
  --output /absolute/path/to/a-new-run-directory \
  --freeze-commit PUBLISHED_40_CHARACTER_COMMIT
```

Every fit child exits before held wording is opened and encoded. Each
evaluation then runs in a fresh child and loads parameter bytes through a
separate reader that imports no trainer. Failures retain their output,
return code and partial evidence; the runner never overwrites a run directory.
Formal results are not used to adjust thresholds or budgets.

The content arms are independently trained linear, rank-4 residual,
untrained and exact SQL. Canonical SQL scores execute one SELECT per source
record and check the returned value, key and source ID. Canonical reads isolate storage, while direct unseen
wording measures generalization without an address oracle. Separate routing
arms are oracle, deterministic exact registry matching, learned constrained
operation/entity/workflow heads, and nearest training embedding. Learned and
nearest thresholds are chosen on calibration with zero accepted unknowns;
held unknown acceptance and known coverage are then reported separately.
Routing reports retain `known_accepted`, `known_coverage`,
`accepted_known_precision` and `correct_known_acceptance` independently.
Coverage divides accepted known requests by all known requests; precision
divides correct accepted known requests by accepted known requests. Precision
is JSON `null` when nothing is accepted. The original correct-known acceptance
divides correct accepted known requests by all known requests. Summary ratios
pool raw counts across seeds and show undefined precision as NA.

Composition uses two typed rank-4 cells, one global rank-4 residual with typed
head blocks, and a stronger dense-head joint model. All receive the same
768-dimensional pair array, 40 target coordinates, seven loss groups and
global minibatch schedule. Typed and block-head joint store 21,544 floats;
dense joint stores 36,904. Both versions of joint are retained. The SQL
planner has exactly the same policy, procedure, episode and hold information
and calls the same bounded interpreter. Training/calibration/held pair
offsets are disjoint. Two episodic revisions and explicit hold sources are
preserved, so learned content never substitutes for current event evidence.

Structure candidates are proposed by two-means on training gradients after
a declared correction. Two private rank-4 adapters, fixed alternating
experts and one rank-8 adapter share the same frozen head and exact global
row schedule. Per-parameter update counts expose empty routed batches.
Structural worded reads use the true registry address to select the saved
cluster membership. These structural results are conditional on oracle
addressing; separate routing experiments measure address access quality.
Merging distills child probabilities into a rank-4 candidate. Calibration
quality and canonical reads are separate gates. Full native lifecycle costs
are not measured by this research job, so neither split nor merge is
promoted. Releasing Python arrays and reloading a persisted child exercises
sleep/wake mechanics without claiming OS memory reclamation.

Maintenance runs 32 cycles per seed at 64 addresses, comparing full replay
with 16-record replay sampling at the same presentation budget. Each ordinary
cycle samples 15 records afresh from the complete active list without
replacement and includes the corrected or inserted record. The compatible
arm name `reservoir16` denotes this resampling rule, not an independently
maintained persistent streaming reservoir. Deletion rebuilds use all retained
records in both arms.
Adam moments reset for each declared fit. Every eighth cycle deletes an
address and cleanly reconstructs both models from the original
initialization on retained sources; the next cycle inserts a new version.
Every checkpoint, source revision, schedule and failed candidate is retained.
Offline forensic predictions may probe all addresses; service reads deny a
deleted address or stopped owner before entering model inference. Incremental
lineage remains a historical dependency record, **not live owner authority**.
Physical erasure and general machine unlearning are not claimed.

## Real owner and original-checkpoint bridge

The importer accepts a native snapshot page, a list of same-cut pages, or
`{"pages": [...]}`. The page schema is
`hepta.memory.inventory-owner-snapshot-page.v1`; records retain canonical
`source_id`, owner memory ID, revision and the inner inventory record. Digests
remain the owner-provided 64-character strings. Source mapping is explicit;
the Python importer does not claim to authenticate an owner.

```bash
python qualification/memory-cell-v10/legacy_bridge.py \
  --owner-snapshot exported-owner-pages.json \
  --legacy-root /absolute/path/to/verified-formal01-restored \
  --encoder-dir /absolute/path/to/pinned-encoder \
  --output /absolute/path/to/new-legacy-bridge

python qualification/memory-cell-v10/native_bridge.py \
  --owner-snapshot exported-owner-pages.json \
  --encoder-dir /absolute/path/to/pinned-encoder \
  --output /absolute/path/to/new-trained-bridge
```

Legacy import requires `inventory:semantic:{index}` and
`inventory:procedure:{index}` to match original indices, names and values.
It loads the original Torch `TensorCell`, verifies every float32 tensor,
original parameter digest and cached canonical input, and compares actual
Torch logits with independent scalar float64 reductions. No old held data
is read. The old Torch reader exits before fresh readers load exports.

New training reads values from the supplied cut. It outputs `semantic.json`,
`procedure.json`, separately identified B-zero intervention artifacts,
checkpoints, training schedules, `TRAINING.json`, `PARITY.json` and process
receipts. Nonzero adapters and the effects of ablation are measured; a changed
typed prediction is not assumed. Float32 parameter bytes remain unchanged
under the `hepta.memory.residual-native.v1` bridge. Native inference is
factored scalar float64, with declared logit tolerance `atol=1e-4, rtol=1e-5`
and raw margin threshold 0.001. Stop is opcode 6, negative halving is floor
division, pack 0 is legal, and a four-opcode program without stop is decoded
before the common interpreter reports `missing_stop`.

`inventory-router/` is also produced by new training. Its model digest is
SHA-256 of `manifest.json` bytes. The JSONL worker starts with:

```bash
python qualification/memory-cell-v10/inventory_worker.py \
  --model /absolute/path/to/inventory-router \
  --model-digest MANIFEST_SHA256 --encoder /absolute/path/to/pinned-encoder
```

This native worker combines a learned four-class operation model with
deterministic, unique owner-registry key/alias binding. It is explicitly a
hybrid address mechanism. The registry contains no values; no gold operation
is sent by the host. The worker echoes request, registry and source-cut
digests and holds no publication authority. Its generic training text never
reads native integration queries. Current/history/change are unsupported
and may be rejected. The separate research router tests fully learned
operation/entity/workflow heads.

## Dependencies, development and measured scope

Use Python 3 with NumPy 2.3.5, ONNX Runtime 1.20.1 and tokenizers 0.21.0.
Original-checkpoint parity additionally uses Torch 2.8.0+cpu. The complete
observed environment is `DEPENDENCIES.freeze.txt`; this is an inventory,
not a portable installation lock for unrelated system packages. Encoder
initialization verifies all six original asset lengths and SHA-256 values.
Each formal run captures its actual complete package inventory again.

```bash
python qualification/memory-cell-v10/development_check.py --output NEW_DIR \
  --encoder-dir /absolute/path/to/pinned-encoder
python qualification/memory-cell-v10/development_suite.py --output NEW_DIR
python qualification/memory-cell-v10/development_worker_check.py --output NEW_DIR \
  --encoder-dir /absolute/path/to/pinned-encoder
```

These checks use development seed 90401, independent random vectors and
development-only labels. They validate gradients, saved-byte corruption
rejection, equal composition budgets, process boundaries, SQL interpreter
consistency, all lifecycle transitions and clean rebuild identities. They
do not score formal held inputs. The legacy bridge's development transport
fixture is explicitly not proof of a real owner; the native integration
harness must first write and export a real DurableCognitiveStore.
The worker check runs the actual `python -I -u -B` process with independent
development text and a development-only threshold, checking valid learned
acceptance, missing-key rejection and UTF-8 request/registry digest binding.

The process ledger is Linux-specific (`resource.RUSAGE_CHILDREN`). It records
non-overlapping process scopes, CPU, wall time, exit code and cumulative
peak RSS. Nested fit timing is not added twice. Evidence inventories charge
source data, the 127,536,988-byte encoder, feature caches, heads, adapters,
routing, schedules and retained history separately. Pipeline timing includes
reference lookup and evidence serialization and is not isolated serving
latency. Installation, upload, energy and external host costs are unmeasured;
the report therefore cannot claim a complete lifecycle cost advantage.
The six read arms use offsets 0, 1 and 2 across the three seeds. This is a
partial read-arm rotation; all six starting positions are not represented,
so the design does not fully counterbalance order effects.
