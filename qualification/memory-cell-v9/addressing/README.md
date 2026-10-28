# V9 semantic address qualification

V9 implements a trained intent and operation compatibility model, independent
threshold calibration, and a three-arm native worker evaluation. The independent
language held set **fails** the stated quality gate. The frozen artifacts are
qualification evidence; they do not establish production readiness.

## Model and executable boundary

The encoder remains the pinned 384-dimensional MiniLM model. Each candidate fits
one seven-class intent head (six supported operations plus reject) and six binary
operation compatibility heads. Semantic candidates use encoder features; hybrid
candidates also use bounded character and word TF-IDF features. The candidate grid
is `{semantic, hybrid}` × `C={2, 8, 32}`. Every candidate performs seven actual
logistic regression fits. This updates small learned heads, not the encoder.

The operation score is the minimum of the selected intent probability and its
compatibility score. Joint and compatibility margins also constrain acceptance.
These scores are explicitly not calibrated posterior probabilities. The supported
operations remain `current`, `history`, `semantic`, `procedure`, `change`, and
`apply`; all data access is still bound to the actual owner's snapshot.

Explicit negative contracts reject requests requiring semantics absent from that
ABI, including mutation, forward event selection, unsupported arithmetic, reversed
differences, historical semantic/procedure records, external parameters, causal
explanations, and multiple outputs. They never select a positive operation or
inspect expected values. Tests cover negated unsupported actions and legitimate
uses of the same words across all six supported operations.

`learned_hypotheses` is an offline diagnostic ablation before those contracts.
Both raw head scores and the contract-filtered results are retained. The raw
ablation uses the same frozen thresholds; it is not separately admitted for use.

## Selection, calibration, and source locks

The public corpus has 1,094 fitting rows and 112 development selection rows
(48 known and 64 unsupported). Disclosed V7/V8 public training and selection data
are reused for fitting. Their calibration and held data are not reused.

The first V9 development run completed all 42 head fits and selected semantic
`C=32`, with 36/48 known requests accepted correctly and 3/64 unsupported requests
accepted. Its parameters, source snapshot, scores, and cost are retained.

One public-development correction added the explicit negative contracts and their
counterexample tests. The second run completed another 42 fits and selected hybrid
`C=2`, with 48/48 known correct and 1/64 unsupported accepted. Public selection was
used iteratively and is development evidence, not independent efficacy evidence.

The final source closure was committed before calibration. Each phase stores
source bytes and hashes and checks the same closure; unrelated repository commits
do not alter that identity. `MODEL_LOCK.json` precedes the first calibration read.
`EVALUATION_LOCK.json` precedes the first held read. New output directories are
required, so original results cannot be silently overwritten.

Selection chooses six operating points under one global integer unsupported
allowance, `floor(0.05 * unsupported_rows)`, and zero accepted known errors.
Independent calibration can only raise selected score thresholds. It cannot
change margins, fit weights, or reselect the candidate. The gate remains at least
80% correct known coverage, at most 5% unsupported acceptance, and no accepted
known error. The curves and actual allocation of that budget are retained.

## Frozen results

The evaluator authored and hashed the independent inputs before seeing model
results. Each input has 272 native requests: 144 known, 96 unsupported, 12 unknown
entities, 8 ambiguous aliases, and 12 time conflicts. Known and unsupported
wordings each have two entity replicas. Classifier evaluation deduplicates these
to 72 known and 48 unsupported wordings; replicas are not independent language
observations. The native suite additionally tests identity and time boundaries.

| Independent stage | Correct known | Accepted known errors | Unsupported accepted | Gate |
| --- | ---: | ---: | ---: | --- |
| V9 calibration | 59/72 (81.94%) | 0 | 1/48 (2.08%) | Pass on this sample |
| V9 held | 47/72 (65.28%) | 0 | 4/48 (8.33%) | **Fail** |
| Frozen V8 on the same new held wordings | 39/72 (54.17%) | 0 | 5/48 (10.42%) | Fail |
| Frozen V7 on the same new held wordings | 26/72 (36.11%) | 0 | 3/48 (6.25%) | Fail |

Held V9 coverage by operation is current 7/12, history 4/12, semantic 7/12,
procedure 11/12, change 9/12, and apply 9/12. The unthresholded learned argmax
matches 70/72 known operations but routes 28/48 unsupported wordings. At the final
thresholds, the raw learned model gives 47/72 correct known and 10/48 unsupported
acceptances. Contracts leave known coverage unchanged and reduce unsupported
acceptances to 4/48. They reject 23 unsupported wordings in total, including ones
the learned model would already decline, and reject no known wordings here.

Thus the observed gain over V8 is accompanied by a substantial unresolved
supportability problem. Different public fitting data and policies prevent a
causal claim about architecture alone. Authored samples and small denominators
also do not establish a population error guarantee. No weights, thresholds, or
model source were changed after the held result.

The original `serving_admitted=true` field records **calibration only**. It is
preserved verbatim in raw evidence. The transport and held summary explicitly
record `held_language_quality_gate_passed=false` and `final_use_authority=false`.
A successful measurement or engineering test must not replace this failed gate.

## Cost and retained artifacts

The two development runs total **84 actual address-head fits**, 91.905690369
recorded wall seconds, and 77.884593454 recorded CPU seconds. Calibration adds
2.913904211 wall / 2.898112997 CPU seconds; held comparison adds 2.401572446 wall /
2.391838281 CPU seconds, with zero additional fits in either phase. These timers
cover the recorded model stages, not human development, CI, or native cell fitting.
Native three-arm evaluation separately performs two memory parameter fits per arm.

The selected calibrated model uses 807,984 bytes excluding the 127,538,960-byte
shared encoder: 161,921 bytes of manifest and 646,063 bytes of weights. Manifest
SHA-256 is `36bf40924f93fdc47ab569b02132adb1edef659338d4b82ea1bd695fdfdb40bf`.
The native fixture SHA-256 is
`cb1dabcd85fe5dd7ec1b3e4246d6b4cb51c25d408bc2d295ce155088b4cac357`.

[`../evidence/addressing/frozen-01`](../evidence/addressing/frozen-01) contains
small `TRAINING`, `ADMISSION`, `HELD`, `SOURCES`, and `ARCHIVE` summaries plus
17 ordered tar.xz parts, each at most 400,000 bytes. The archive retains all 306
original files across both selections, admission, held, logs, and evaluator
provenance. Every archived member was reconstructed and rehashed. Each execution
source snapshot was also checked against its recorded Git commit.

[`../fixtures/address-model/PARTS.json`](../fixtures/address-model/PARTS.json)
describes exact weight reconstruction, manifest, and native fixture bytes. It is a
transport for the frozen result and requires no refitting. `prepare_ci.py` verifies
the identities before writing the reconstructed model.

## Native qualification contract

The ignored integration test is
`memory_cell_language_v9_tests::actual_v9_three_arm_suite_retains_worker_decisions_and_native_readouts`.
Run it through the repository's `just test` workflow with these explicit settings:

| Input or output | Environment variable |
| --- | --- |
| Shared Python and encoder | `MEMORY_CELL_TRAINING_PYTHON`, `MEMORY_CELL_ADDRESS_ENCODER_DIR` |
| Frozen V7 model | `MEMORY_CELL_ADDRESS_MODEL_DIR`, `MEMORY_CELL_ADDRESS_MODEL_DIGEST` |
| Frozen V8 model | `MEMORY_CELL_V8_ADDRESS_MODEL_DIR`, `MEMORY_CELL_V8_ADDRESS_MODEL_DIGEST` |
| V9 model | `MEMORY_CELL_V9_ADDRESS_MODEL_DIR`, `MEMORY_CELL_V9_ADDRESS_MODEL_DIGEST` |
| Same held fixture for all arms | `MEMORY_CELL_V9_NATIVE_FIXTURE`, `MEMORY_CELL_V9_NATIVE_FIXTURE_DIGEST` |
| Create-only V7 receipt | `MEMORY_CELL_V9_BASELINE_V7_RECEIPT_PATH` |
| Create-only V8 receipt | `MEMORY_CELL_V9_BASELINE_V8_RECEIPT_PATH` |
| Create-only V9 receipt | `MEMORY_CELL_V9_CANDIDATE_RECEIPT_PATH` |

Each arm writes the same new records into an actual owner store, fits semantic and
procedure parameters, publishes an actual bundle, and executes every request both
directly and through control. Results retain readouts, source IDs, bundle identity,
errors, transport bytes, timing, and exact validated worker wire frames. A raw
frame is bounded to 32,769 bytes, hashed, and bound to the expected query and model.
Host time abstentions have no worker frame. The diagnostic slot is single-entry
and drained sequentially; it is not a concurrent invocation log or authority source.

The Rust profile pins the closed V9 import closure and preserves frozen V7/V8
profiles. Regular V9 workers require the calibration receipt. The explicitly
scoped qualification shadow worker allows measurement of unsuccessful candidates
only under the reserved fixture owner. Neither path grants final-use authority.

Development tests cover numerical fitting and round trips, compatibility vetoes,
bounded parameter loading, wrong-known and global-error-budget constraints,
calibration tightening, contract counterexamples, and fixture/request separation.
Native engineering success and scientific acceptance remain separate outcomes.
