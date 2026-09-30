# channel.matrix current candidate status

Status: **source-composed exact candidate; repository execution and external production qualification are not yet established**.

## Frozen ordinary-source snapshot

The current implementation map observes ordinary-source commit
`2dcf4538708a9a271d06eb48356dab2c201e9edc`, tree `c39603fab28b00366ec13ca953ea4f5f2460339c`. This is the immutable source snapshot for
the next evidence cycle. The metadata commit containing this status cannot embed
its own future Git identity; `scripts/verify_channel_matrix_candidate.py` and the
out-of-tree lane receipts bind the exact metadata candidate, tree, map bytes and
all inspected source objects.

## Repository source and evidence state

- Source-writing/apply/finalizer workflows, encoded payloads and staging bundles
  are absent. Matrix qualification is read-only (`contents: read`).
- The closed source inventory covers protocol/store/SDK/matrixd, final-use
  contracts, operation/state SQLite owners, Supervisor lifecycle composition,
  documentation/evidence tooling, workflow bytes and the canonical real-Synapse
  runner.
- Both immutable lanes retain canonical command receipts for locked all-target
  compilation, public-API compile-fail Rustdoc proofs, the locked mapped Matrix
  native test set plus nextest JUnit, strict Clippy and rustfmt.
- The paired verifier revalidates both manifests, Q01-Q29, transitive source
  closure and API compile-fail command/log identity before emitting one receipt.
- `codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh` is canonical;
  `tests/fixtures/run-hermetic-synapse.sh` is a transparent compatibility entry.
- The typed `Admission` / `EnteredSend` boundary, distinct post-entry diagnostic
  fault classes, stable transaction reconciliation and bounded identity-free
  latency histograms remain unchanged.

## Evidence still required

The metadata candidate that binds this source snapshot must obtain terminal
success for source-head, deterministic-merge and paired repository receipts.
Queued, skipped, canceled, superseded, stale, partial or tampered evidence is not
a pass.

Real enrolled homeserver execution, encrypted room and multi-device/session
rotation, protected restore, ENOSPC/permission/WAL-SHM/stale-snapshot recovery,
sustained capacity/network pressure, target-host measurements and distinct
governed target/operator signatures remain external gates. Therefore
`productionImplementation`, `productExecutionProved`,
`deploymentQualificationComplete`, `independentAcceptance`, `activation`,
`promotion` and `release` remain false.
