# channel.matrix current candidate status

Status: **source-composed exact candidate; repository execution and external production qualification are not yet established**.

## Frozen ordinary-source snapshot

The current implementation map observes ordinary-source commit
`32656ca556a11a0bcfd1e62dc7b4dd3a5bdb5fb4`, tree
`ee0e65127881b3d502e91f2b2454b50ccfff1d63`. That commit is the immutable
source snapshot for this evidence cycle. The metadata commit containing this
status file cannot embed its own future Git identity; the exact current
candidate commit/tree, the map bytes and every inspected source blob are bound
by `scripts/verify_channel_matrix_candidate.py` and the out-of-tree lane
receipts.

## Repository source and evidence state

- Source-writing/apply/finalizer workflows and encoded staging payloads are absent.
- Matrix qualification is read-only (`contents: read`), uses exact source-head
  and deterministic-merge lanes, and reruns on the real protected `main` SHA
  after integration. PR-head evidence is never reused as merge-SHA evidence.
- The closed source snapshot includes Matrix protocol/store/SDK/matrixd,
  Supervisor lifecycle composition, final-use contracts, operation/state SQLite
  owners, documentation/evidence tooling, workflow bytes and the real Synapse
  runner.
- Both lanes retain first-class command receipts for locked all-target
  compilation, Rustdoc public-API compile-fail proofs, the locked mapped Matrix
  native test set plus nextest JUnit, strict Clippy and rustfmt.
- The version-2 paired verifier revalidates both artifact manifests, Q01-Q29,
  transitive source closure and the API compile-fail command/log identity before
  emitting one paired receipt.
- The canonical target runner is
  `codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh`; the historical
  `tests/fixtures/run-hermetic-synapse.sh` path is a transparent compatibility
  delegator and is independently source-bound.
- The typed `Admission` / `EnteredSend` boundary, distinct post-entry diagnostic
  fault classes, stable transaction reconciliation and bounded latency
  histograms remain unchanged by the evidence-only closure.

## Evidence still required

For the current metadata candidate, source-head and deterministic-merge must
both reach terminal success for all command receipts, Q01-Q29 native execution,
clean-source snapshots and the paired receipt. Queued, skipped, canceled,
superseded, stale-SHA, partial or tampered evidence is not a pass.

Real enrolled homeserver execution, encrypted room and multi-device/session
rotation, protected restore, ENOSPC/permission/WAL-SHM/stale-snapshot recovery,
sustained capacity and network-pressure measurements, target-host binding and
distinct governed target/operator signatures remain external gates. Therefore
`productionImplementation`, `productExecutionProved`,
`deploymentQualificationComplete`, `independentAcceptance`, `activation`,
`promotion` and `release` remain false.
