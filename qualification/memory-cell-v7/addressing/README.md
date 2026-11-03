# V7 typed addressing and daemon worker

This directory provides owner-scoped address resolution, a trained semantic
intent model, independent admission calibration, and a persistent JSON-lines
worker for the daemon's real memory read path. It never reads memory payloads.

The six operations remain `current`, `history`, `semantic`, `procedure`,
`change` (latest minus historical), and `apply` (current event, semantic
attributes, current stored procedure). Unsupported actions, multiple outputs,
past semantic/program versions, reverse subtraction, and two historical
endpoints have no registered execution meaning. A capability check rejects
explicit requests for them; it does not choose positive operations. Statistical
intent and expected-answer-shape heads choose the supported hypothesis.

## Source authority and entity resolution

The execution owner supplies the complete authorized scope's registry:

```json
{
  "schema": "hepta.memory.v7.owner-registry.v1",
  "scope": "owner:scope",
  "source_cut": "7777777777777777777777777777777777777777777777777777777777777777",
  "entities": [{"entity": "sensor-orion", "aliases": ["Orion", "奥瑞安"]}]
}
```

`source_cut` is the real owner's 64-lowercase-hex `ContractDigestV1`, not a local
integer counter. Aliases resolve exactly after Unicode normalization; ambiguous
or unknown identities fail. Multiple mentioned entities or disagreement with
an explicit entity slot fail before model inference. Entity names are replaced
only internally, so an alias containing a word such as `predict` does not become
an action. Canonical requests retain the original text, timestamps and budgets.

The registry is an address snapshot, not a permission token. Its digest and the
model digest do not authenticate a caller. The native owner must independently
check principal/scope/entity access, the current source cut, and final-use
freshness. With a canonical entity input the daemon can enforce exact request
field equality; alias frontends require an owner-listed unique mapping.

## Train, select, then calibrate

From the repository root, using the existing pinned NumPy/scikit-learn/ONNX
environment:

```sh
python qualification/memory-cell-v7/addressing/train.py \
  --encoder /path/to/pinned/multilingual-minilm \
  --output /new/output/directory \
  --calibration /path/to/independently-authored-calibration.json
```

All six candidates (semantic/hybrid × C=2/8/32) are actually fitted and retained.
Each has separate intent and answer-shape heads. Training uses 616 public rows;
selection uses 134 different rows. The selected candidate and thresholds are
saved in `SELECTION_LOCK.json` **before** the supplied calibration is read.
Calibration only tightens its confidence threshold; it cannot select another
candidate, change the margin or update weights. There is no held-data input.

External calibration is a JSON array of at least 120 and at most 4096 rows:

```json
[
  {
    "id": "independent-family-example",
    "family": "independent-family",
    "language": "en",
    "text": "Query text using entity and date slots",
    "operation": "current"
  }
]
```

The example illustrates the schema, not a sufficient calibration corpus.
`operation` is one of the six names or `reject`; `language` is `en` or `zh`.
`{entity}`, `{at}`, `{since}` placeholders are normalized to `entity`/`date`.
Exact normalized overlap with fit/selection data or duplicate calibration rows
is rejected. Calibration should include all operations and near-unsupported
families, not just easily rejected unrelated questions. Raw supplied bytes and
normalized rows both remain in the run directory with identity bindings.

For a fixed model and independent exchangeable unsupported-request sample,
the one-sided order-statistic threshold targets 5% false acceptance at 95%
confidence. This is conditional on exchangeability. Author-written synthetic
families do not establish a human population risk guarantee. Too few unsupported
samples result in a reject-all threshold; known coverage is reported separately.

Omit `--calibration` to do selection-only development. The output is then
`selected-unadmitted` with `calibration=null`; serving refuses it. The first
development calibration was inspected after failure and is now public diagnostic
material in `corpus.py`, not a fresh independent calibration source for later
designs. Its negative result and all candidates remain retained.

## Persistent native-daemon protocol

```sh
python qualification/memory-cell-v7/addressing/worker.py \
  --model /path/to/selected \
  --model-digest EXPECTED_MANIFEST_SHA256 \
  --encoder /path/to/pinned/multilingual-minilm
```

The model is loaded once and checked against the expected manifest, encoder and
current addressing policy digests. Startup diagnostics go to stderr. Each stdin
line is a bounded object with exactly these fields:

```json
{
  "schema": "hepta.memory.v7.address-worker-request.v1",
  "request": {
    "query_id": "q1",
    "scope": "owner:scope",
    "entity": "sensor-orion",
    "text": "Read the latest value for Orion.",
    "at": 20250201,
    "since": 20250101,
    "max_hops": 4,
    "max_cells": 3
  },
  "registry": {
    "schema": "hepta.memory.v7.owner-registry.v1",
    "scope": "owner:scope",
    "source_cut": "7777777777777777777777777777777777777777777777777777777777777777",
    "entities": [{"entity": "sensor-orion", "aliases": ["Orion"]}]
  }
}
```

Stdout emits exactly one `hepta.memory.v7.address-decision.v1` JSON line. It
includes query ID, request digest, model digest, registry digest, source cut,
status, rejection reason, canonical request and typed plan. An accepted plan
contains `operation`, `required_cells`, `read_hops`, `source_cut` and
`registry_digest`. A failed decision has both `request=null` and `plan=null`;
`authority` always remains false. The worker reports request-body bytes and
per-request CPU/wall time. The caller must add process startup, response bytes,
timeouts, failed attempts and its own transport costs to the full ledger.

Frames are capped at 2 MiB and responses at 32 KiB. Duplicate keys/nonfinite JSON
are rejected. Incomplete/oversized frames terminate the worker rather than
resynchronizing arbitrary remaining input. The daemon supplies deadlines,
restarts failed children and revalidates the owner before using a result.
Requests that would exceed the encoder's actual token window are rejected;
unsupported instructions appended beyond a silently truncated prefix cannot
be admitted by this path.

The one-shot `cli.py` accepts the same pinned model and separate `--registry` /
`--request` files. No route, expected answer or gold label is accepted by serving.

## Validation scope

The boundary tests cover aliases, entity/scope/cut mismatch, temporal-slot
consistency, unregistered override fields, cell/hop budgets, truncated inputs,
persistent frame binding, malformed JSON, and zero executable payload on failure.
They do not establish natural-language quality. New independent calibration and
held evaluation are required after the current design is frozen; the native
owner still determines actual record authority and read correctness.
