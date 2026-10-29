# V10 native CI and finalization

This directory is separate from the frozen `qualification/memory-cell-v10/`
research source. The push trigger is
`qualification/memory-cell-v10-ci/VERIFY_REQUEST.json` on
`research/memory-cell-v10-20261029`. No request or CI evidence is written inside
the research source directory.

## Verification request

Commit this exact shape after publishing the source and workflow:

```json
{
  "schema": "hepta.memory.v10.ci-request.v1",
  "mode": "verify",
  "request_id": "native-01",
  "baseline_commit": "0f41c4968eea63727c69e2b979491e94a99a9dbb",
  "source_manifest_sha256": "38559a7e81e22b6742febb4fdca9b52e567495cb0233eabd28aae9979c6c24b7",
  "protocol_sha256": "ecbf06ba74e51dae0f3d9d2eadde62aec97c4dbd05c32d3d520d2f1ff311b355",
  "tests_before_final_fix_and_format": true
}
```

The request pins the research manifest and protocol. The runner additionally
records its exact commit, tree, workflow, request, protected source inventory,
tool versions, installed dependency versions, process logs and native evidence.
It rejects a dirty checkout or a checkout different from `GITHUB_SHA`.

The workflow uses checkout depth one, Rust 1.95.0, nextest 0.9.131, and the
runtime `CARGO_TARGET_DIR` selected by `setup-ci`, with V9/V8 fallback cache keys.
`setup-ci` may override the initial target directory. Commands are passed as
argument lists. Rust tests run through `just test`.

The evidence working root is a fresh `/tmp/h10-<run-id>-<attempt>` directory.
This keeps both original and migrated owners' Unix socket paths within the
103-byte cross-platform bound. The driver checks the longest owner path before
any training. The portable archive still uses the stable
`memory-v10-ci-output/` member prefix; absolute paths in original receipts
remain unchanged.

Verification performs these steps:

1. Create a fresh Python 3.12 virtual environment; install the fixed minimal
   runtime closure, NumPy 2.3.5, ONNX Runtime 1.20.1, Tokenizers 0.21.0, and
   Torch 2.8.0+cpu from its official CPU index. Check the installed closure.
2. Verify the baseline archive index Git blob, every archive part, and the
   complete archive digest. Extract only the 14 names in `INPUT_PINS.json`:
   the seed-731 semantic/skill parameters, their original sources/features,
   and two source/encoder identity records. Other archive members are not
   extracted or parsed. Download the six encoder assets at the fixed model
   revision and check every byte count and SHA-256.
3. Verify the frozen research source. Build the same-source App Server needed
   by ordinary Agentd integration tests. Run all ordinary tests in the ten
   scoped Hepta packages inherited from the V9 verification boundary.
4. Run exactly the ignored
   `memory_inventory_actual_tests::memory_inventory_actual_trained_owner_lifecycle`
   parent test, with retries disabled and one test thread. Its private child
   tests are launched by that parent. Old V7/V8/V9 ignored qualification cases
   and old frozen holdouts are never selected.
5. Require completion of the five actual owner processes and the original
   checkpoint, correction, clean rebuild, migration and trained worker receipts.
   Require all three `RUST_NATIVE_PARITY.json` reports: 16, 16 and 15 supported
   addresses, both parameter kinds, and every row within the fixed absolute
   1e-4 / relative 1e-5 tolerance. Preserve both ordinary and actual JUnit files.

Nextest 0.9.131 resolves `store.dir` against the Cargo workspace, independently
of `CARGO_TARGET_DIR`. With the checked-in `local` profile inheriting the
default JUnit path, the report is
`codex-rs/target/nextest/local/junit.xml` under the checkout. Before each test
command, the driver resolves this configured path and removes any previous
report. It preserves a location receipt, then requires a fresh nonempty XML
report with no failures; the actual report must name the one selected parent.
Pinned upstream source identities are in `TEMPLATE_PROVENANCE.json`.

The actual test uses real SQLite, Agentd control sockets, process stops, signed
artifact ownership, and the existing same-host TCP migration path. Its App
Server readiness seam and authority keys are explicit test fixtures. A passing
CI run is not a production deployment or a claim of scientific superiority.
The full research comparison matrix runs separately.

## Separate finalization request

After a successful verify artifact has been retained, replace the request with
`mode: "finalize"`, a new request ID, the same source/protocol pins, and an
additional `verification` object:

```json
{
  "run_id": 123,
  "run_attempt": 1,
  "job_id": 456,
  "artifact_id": 789,
  "commit": "<40-character tested commit>",
  "tree": "<40-character tested tree>",
  "transport_sha256": "<SHA-256 of memory-v10-evidence.tar.xz>",
  "receipt_sha256": "<SHA-256 of receipt.json>"
}
```

The gate authenticates the completed successful GitHub run, attempt, job and
artifact for this workflow. The downloaded ZIP must match GitHub's size and
SHA-256; its three members and every archived file must match the transport
index. The receipt must show both exact test commands, clean source, and the
required native artifacts. The current protected source path/mode/blob/hash
inventory must equal the inventory from the successful verify run.

Only then does the runner execute scoped `just fix --locked` for the same ten
packages, followed by `just fmt --base 0f41c4968eea63727c69e2b979491e94a99a9dbb`.
It shallow-fetches only that baseline commit when necessary, using a temporary
child-only Git read credential. It never commits or pushes. It retains patches
and tree identities after each stage. No tests or model fits execute in this
mode, and no tests run after fix/format. Any modification outside the scoped
Rust sources, including changes to frozen research files, fails finalization.

## Evidence and limits

Each attempt uploads exactly `INDEX.json`, `receipt.json`, and
`memory-v10-evidence.tar.xz`, including failures and partial model/checkpoint
logs. Unix names such as `memory-bundle:...` remain unchanged inside the tar.
Symlinks, sockets and other nonregular entries are recorded without following
them. Evidence is uploaded before optional cache saving.

The source gate excludes only the triggering CI request and retained evidence
under `qualification/memory-cell-v10-ci/evidence/`. Research outputs, plots and
reports belong in `qualification/memory-cell-v10-results/`, outside the source
gate. Adding those results after verification is allowed; their contents are
not certified by Rust CI success. Do not add files to the frozen research source
directory or alter protected implementation files between verify and finalize.

Wrapper wall time, completed-child CPU, cumulative kernel child RSS high-water,
job-start boundary and packaging cost are retained with their scopes. Cumulative
RSS is not a sum or a whole-job measurement. VM provisioning, early setup CPU
and upload cost are not claimed as exact end-to-end lifecycle cost.

For a local CI-driver check without Rust, models or network:

```sh
python3 -B -m unittest discover -s qualification/memory-cell-v10-ci -p ci_tests.py
```

Reviewable stages are: fixed input preparation; verification and evidence
transport; authenticated finalization; workflow wiring and the exact new-test
nextest timeout. Each module remains small. `TEMPLATE_PROVENANCE.json` records
the fixed baseline files used to derive this driver.
