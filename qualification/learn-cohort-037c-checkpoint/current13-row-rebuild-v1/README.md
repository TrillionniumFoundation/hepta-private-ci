# Current13 guard rows: rebuilt identity

This evidence-only delivery reconstructs the Current13 guard delta from exact, durable source. It is **not** the lost 72,732-byte original delta. The rebuilt plan has its own byte, SHA-256 and Git-blob identity in MANIFEST.json.

## Inputs and scope

- Base: `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`, tree `f96bebefbc1e7d8187efadb62f88d524cdd18451`.
- CALLERS.toml base: blob `6eb79688b56aca6306bc500b96f3b10654660196`; all five old protected rows are embedded in full in the plan.
- Actual Current13 source and the original five Current plus three Candidate-material tests: commit `cf4d240f84326539cde7bb7cd53f510dcce4f25b`.
- Exactly five existing protected rows are migrated. One protected row, one uniquely named free-function boundary, and its inventory entry are added.
- There are no existing boundary changes. Relative to this exact base, the counts are 541 boundaries / 389 protected rows before and 542 / 390 after.
- Every old required and forbidden marker is retained in its original array order and multiplicity. Documented function-sequence changes reflect actual whitespace and the explicit Page/Current branches. New whole-body top-level guards keep these checks in the invoked control flow.

No production file, global CALLERS.toml, verifier, allowlist, main branch or main PR is changed by this delivery.

## Validation boundary

The input bytes, SHA-256 hashes and Git blobs have been verified. A scoped JavaScript diagnostic checked six protected rows and rejected eight unused-closure mutations. Its results are included with its helper source and are explicitly **not** results from the repository's authoritative Python scanner. The independent Profile review likewise establishes static row integrity only.

The authoritative Python scanner, original eight source tests, full Rust index/caller validation, native compilation and ordinary qualification have **not** been run for this rebuilt plan. The original eight test bodies remain unchanged. No old passing log is assigned to this new identity.

`validate_current13_rebuild.py` is a prepared, unexecuted runner. It pins all inputs, checks the exact before rows with Python tomllib, renders the declared delta into a new output directory, and calls the unchanged repository verifier. With `--run-qa`, it runs the original eight cases in a temporary overlay. It never writes the tested checkout, global CALLERS.toml or verifier, and it does not launch H, native or a full-index job.

Example for a future authorized local execution:

```sh
python3 validate_current13_rebuild.py \
  --root /absolute/path/to/exact-cf4d-checkout \
  --delta CURRENT13_REBUILT_DELTA.json \
  --output /absolute/path/to/new-current13-validation \
  --run-qa
```

The root must contain the exact pinned files. If CALLERS.toml has already been centrally assembled, provide `--base-callers` pointing to the exact a96 preimage instead. The runner refuses an existing output directory or one within the source checkout.

## Seven-QA overlap

SEVEN_QA_OVERLAP.json records a source-only audit of the seven delivered QA files. For the actual Version V3 and Root source in this checkpoint, one QA file needs five EXPECTED tuple changes adding seven concrete caller paths. Every original caller retains its order; the Version callers and Root recovery caller are appended. Their corresponding registry changes belong to the separate Version and Root plans and must be combined, not overwritten.

The EXPECTED-only patch and complete postimage are saved beneath this evidence directory. They are **not** installed into the repository QA tree. Exact replay has zero offsets/fuzz; all 16 test-class bodies are byte-identical. This does not claim those 16 tests passed. No additional EXPECTED expansion was established for the other six files at the reviewed source state. Training v3 and the final Version/Root guard combination remain separate inputs.

## Actions capability observation

The exact-a96 workflow declares workflow_dispatch with no inputs and tests the selected GitHub SHA, preserving its required source/caller/native steps. Available GitHub tools expose GET and existing-run/job retry capabilities, but no callable new workflow dispatch. No workflow or job was started, retried or modified.

## Qualification

Ordinary NoUpdate: **0**. Ordinary Adopt: **0**. Complete daemon plus Root cold recovery: **0**.
