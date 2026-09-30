# channel.matrix current candidate status

Status: **source-composed candidate; exact native and external qualification not yet established**.

## Frozen source snapshot

The implementation map observes source commit
`d58ca90b779c851ab7f7f9676356471f3d17795b`, tree
`07f52d905672e4482c3c0feb12bf38e355640ad2`. That snapshot is the frozen
ordinary-source ancestor for the current evidence cycle. The commit containing
this status file cannot embed its own future Git identity; the exact current
candidate commit/tree and every inspected blob are bound by
`scripts/verify_channel_matrix_candidate.py` and the out-of-tree evidence
receipts.

## Repository source state

- Matrix apply/finalizer workflows and encoded staging sources are absent.
- Matrix qualification workflows are read-only and use exact source-head and
  deterministic-merge lanes plus one paired acceptance receipt.
- The typed entered-use boundary remains intact. Post-entry proof, persistence,
  authority, session identity, cancellation, deadline, clock, store, permit and
  invariant faults retain distinct identity-free diagnostics while all remain
  conservative unknown effects.
- Fixed cumulative histograms cover claim-to-first-poll, final-use broker,
  SQLite owner operations, revocation refresh and physical transport. They are
  measurements, not target-host SLO claims.
- `PRODUCTION_QUALIFICATION_PROFILE.json` and
  `scripts/channel_matrix_production_qualification.py` define a closed external
  target and independent-acceptance evidence inventory. Candidate-authored CI
  cannot self-issue those results.

## Evidence state

The current source-head and deterministic-merge lanes must both complete locked
compilation, all mapped Matrix native tests, all-target checks, strict Clippy,
rustfmt, Q01-Q29 JUnit accounting, clean-tree verification and the paired
receipt. Queued, skipped, canceled, stale-SHA or partial runs are not passes.

Real enrolled homeserver execution, encrypted-room and multi-device/session
rotation, protected restore, storage-fault recovery, sustained capacity/network
pressure, target-host measurements and distinct governed target/operator
signatures remain external gates. Therefore `productionImplementation`,
`productExecutionProved`, `deploymentQualificationComplete`,
`independentAcceptance`, `activation` and `release` remain false.
