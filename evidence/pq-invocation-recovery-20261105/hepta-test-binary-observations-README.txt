Hepta local test-binary observations
===================================

Tool: observe_hepta_test_binaries.py

Run only after the intended source is frozen and the relevant native commands
have finished. The tool reads Git, receipts, logs, Cargo fingerprint metadata,
dependency files and executable bytes. It does not invoke Cargo, nextest, tests
or the observed executables. Only the JSON observation file is written.
The default output name includes the requested source SHA prefix. Existing output
files are never overwritten; supply a fresh --output name for a later observation.

Example from /workspace/scratch/768fd621f7e2 (replace the receipt paths with the
actual completed corrected-source receipts; do not relabel an earlier receipt):

  python3 -B evidence-prep/observe_hepta_test_binaries.py \
    --source-sha ff19c86b7190204e9172a1595a58d8eb9f897c6d \
    --receipt hepta-receipts/hepta-dispatcher.json \
    --receipt ACTUAL_CORRECTED_OWNER_RECEIPT.json \
    --receipt ACTUAL_CORRECTED_SIGNED_RECEIPT.json

The old dispatcher receipt records 97ae5b4bf5e5f0d0589c1c653f1861e1d9c1242f.
Its 14 results cannot qualify ff19c86b or any later source. The JSON keeps each
receipt's source separate and flags whether it matches the requested source.

Completion and association rules:

* An existing test-lib JSON, complete Cargo fingerprint marker, dependency file,
  regular executable ELF and stable metadata are required before streaming SHA256.
* A supplied running receipt for a package suppresses all artifact hashing for
  that package. Missing/incomplete outputs stay pending. No partial logs are read.
* A binary newer than its completed fingerprint is pending. The executable and
  watched Cargo metadata are checked again after the streaming hash.
* Cargo .d relative source paths are never expanded into purported provenance.
  Actual absolute paths are recorded verbatim. A matching evidence-library
  fingerprint and its .d paths are only indirect local dependency association.
* The old nextest dispatcher log has no Running line naming an executable path.
  Its candidate therefore remains package/target association, not exact execution
  binding. The tool records real Running lines when present; it invents none.
* A current file newer than a historical receipt cannot be assigned to that run.
  Earlier mtimes may mean Cargo cache reuse, not an independently rebuilt binary.
* Ordinary bin-codex-hepta-agentd artifacts are excluded. The removed aa11... main
  executable and relocated static archives remain separate cache records.
* The output contains no native-test PASS conclusion. Exit zero only means that
  the observation file was written. Roster checks and source acceptance remain
  separate. These are debug test artifacts, not deployment release binaries or
  independent builds. Physical free bytes and unprivileged available bytes are
  recorded separately as f_bfree_bytes and f_bavail_bytes.

Nextest list exploration (local 0.9.151 help and repository wrapper inspected):

* Ordinary `cargo nextest list` explicitly builds test binaries. It must not be
  invoked as a supposedly read-only post-run operation, even if a cache exists.
* The local help names `--list-type binaries-only` and `--message-format json`;
  selecting binaries-only does not itself disable Cargo's build phase.
* The help exposes `--cargo-metadata` and `--binaries-metadata` under reuse-build
  options. An already retained original pair is the possible reuse route; this
  tool neither creates replacement metadata nor invokes that route. Its exact
  no-build behavior must be confirmed before use with the actual retained inputs.
* scripts/run-nextest.py always constructs `cargo nextest run`. Its scoped
  cargo-metadata JSON is temporary and removed on exit. It is not a list-only
  wrapper and does not retain an original binaries-metadata JSON.

No native command or list operation was run to prepare this tool. Only nextest's
`list --help` was read. A final original runner binary list, if retained later,
can strengthen association without turning this file into a pass certificate.
