# V8 selective addressing and native qualification

V8 keeps the published V7 model, code and held evidence unchanged. Its new
candidate fits one positive-operation head on supported rows and a separate
binary supportedness head on all public fitting rows. The score is the minimum
of these two scores, followed by a per-operation threshold and margin. These
scores are ranking statistics, not calibrated posterior probabilities.

The runtime continues to use the existing bounded eight-field V7 decision
envelope. The native host now selects one of two **closed** model/import
profiles; V8 does not bypass code pins, request binding, owner cuts or releases.

## Fitting and independent evaluation order

Commit all addressing Python sources before executing these commands. Each
stage uses a new output directory and retains exact inputs, source snapshots,
candidate fits, costs, failure receipts and model identities. Do not place run
outputs inside this source directory. Source or dependency changes between
selection, calibration and evaluation are rejected.

```bash
python qualification/memory-cell-v8/addressing/train.py select \
  --encoder /absolute/pinned/encoder --output /new/selection

python qualification/memory-cell-v8/addressing/train.py calibrate \
  --encoder /absolute/pinned/encoder --selection /new/selection \
  --calibration /absolute/independent-calibration.json --output /new/admission

python qualification/memory-cell-v8/addressing/evaluate.py \
  --encoder /absolute/pinned/encoder --selection /new/selection \
  --admission /new/admission --held /absolute/independent-held.json \
  --held-sha256 AUTHOR_FROZEN_SHA256 --output /new/held \
  --baseline-model /absolute/frozen-v7-model --baseline-digest V7_MANIFEST_SHA256
```

Selection fits all six declared semantic/hybrid × C=2/8/32 candidates, two heads
each. It reuses the original public V7 train/selection split, canonicalizes
entity/date placeholder spacing to the worker transport, and adds disclosed
V8 public fit examples. The new calibration and held files are not fitting
inputs. Calibration cannot update weights, change the chosen candidate, lower
thresholds or change margins. Its finite-sample requirements are at least 80%
correct known coverage, no incorrectly accepted known operations and at most
5% unsupported acceptance. The six per-operation OOD allowances sum to no more
than that global allowance. Authored examples do not establish a population
risk guarantee or iid sampling.

The held stage freezes the selected model, baseline identity and independently
provided input digest before its first held read. It retains raw classifier
decisions and a native fixture. This Python stage explicitly reports zero native
executions; only the separately recorded Rust owner/socket run can establish
native readback. Comparing the existing frozen V7 model with V8 includes the
public-data and policy changes; it is not an isolated architecture ablation.

## Input contract

The exact top-level fields are `schema` (the literal
`hepta.memory.v8.language-suite.v1`), `split` (`calibration` or `held`), `entities`
and `rows`. Each entity has exactly `entity`, `aliases` and `records`. Each record
has `kind`, `effective_at` in Unix seconds, and a native value:

| Kind | Exact value |
| --- | --- |
| event | Integer in −1,000,000..1,000,000 |
| semantic | `{factor: bounded integer, label: nonempty UTF-8 string <=256 bytes}` |
| procedure | `{opcode: identity/add_bias/multiply/affine/clamp, bias: bounded integer, limit: 0..1,000,000}` |

Every entity needs two event times plus semantic and procedure records. There
are at most 32 entities and 480 records, leaving room for the existing owner
fixture. All record timestamps must already have occurred. No source IDs,
owner cuts or permissions are imported from the input file.

Each row has exactly `id`, `family`, `language` (`en` or `zh`), canonical `entity`,
`text`, `at`, `since`, `expected_operation` and `category`. Supported rows use a
registered operation and category `known`; negative rows use null operation and
one of `unsupported`, `unknown_entity`, `ambiguous_alias`, `time_conflict`.
Aliases appear in text; the entity slot remains canonical. A literal date in a
supported request must exactly match the UTC midnight cutoff for history.at or
change.since. Every generated request has max_hops=max_cells=8. Thus syntactic
budget rejection cannot masquerade as unknown-entity detection.

Only successfully normalized `known` and `unsupported` rows enter classifier
metrics and calibration. Unsupported requests that the owner parser rejects,
such as multiple historical cutoffs, remain complete native read cases. Their
IDs, categories and rejection reasons are reported separately and never enlarge
the classifier denominator. A parser failure on a `known` row still rejects the
input. Unknown/ambiguous entity cases also remain separate native read cases.
Repeating the same normalized wording for several entities counts once in
classifier metrics. Conflicting labels, duplicate requests and overlap with
earlier fitting/calibration text are rejected; the prior-split overlap checks
include all native rows, even parser rejections. Exact entity resolution is
limited to the owner's listed aliases.

## Production and shadow execution

`worker.py` requires the completed calibration gate to pass. A separate
`qualification_shadow_worker.py` executes the same frozen thresholds even if
that gate failed, but only for the reserved ControlFixture owner
`018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81` in its agent-private scope. Its decisions
carry a `qualification-shadow` score-kind marker. It creates no final-use grant
and is never enabled by default daemon configuration. Both entry points and the
full first-party import closure are part of the pinned policy identity.

The ignored Rust test
`memory_cell_language_v8_tests::actual_v8_shadow_suite_records_every_frozen_request_and_bound_native_readout`
creates separate real owner fixtures for frozen V7 and candidate V8, writes the
same records, actually fits semantic/procedural parameters for each fixture,
and executes every request through both workers and native control sockets.
A direct resolver call precedes each control read so that a downstream failure
cannot erase an incorrect unsupported route. These are two measured routing
calls per case; their times and all worker/control bytes are reported separately.

The test uses the existing training Python and V7 model/encoder environment
variables, plus:

| Variable | Meaning |
| --- | --- |
| MEMORY_CELL_V8_NATIVE_FIXTURE | Absolute path to held/native-fixture.json |
| MEMORY_CELL_V8_NATIVE_FIXTURE_DIGEST | SHA-256 of those exact fixture bytes |
| MEMORY_CELL_V8_ADDRESS_MODEL_DIR | Absolute admission/model path |
| MEMORY_CELL_V8_ADDRESS_MODEL_DIGEST | Selected V8 manifest SHA-256 |
| MEMORY_CELL_V8_NATIVE_RECEIPT_PATH | New, create-only candidate receipt path |
| MEMORY_CELL_V8_BASELINE_RECEIPT_PATH | New, create-only frozen V7 receipt path |

The engineering test checks complete measured execution and binding invariants.
Scientific quality has its own `quality_gate_passed` field, including coverage,
unsupported routes and identity/time failures. A successful measurement of a
negative result must not be reported as passing the research acceptance gate.

## Reviewable stages

The change can be reviewed as numerical model/serialization; per-operation
policy and native fixture contract; public data and staged runners; closed host
profile and import tests; then the paired native fixture and boundary tests.
All generated outputs remain separate from source and prior negative evidence.
