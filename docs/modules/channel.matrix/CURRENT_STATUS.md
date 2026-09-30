# channel.matrix current candidate status

Status: **source-composed candidate; exact native and external qualification not yet established**.

## Frozen source snapshot

The implementation map records an immutable ordinary-source ancestor. A commit
cannot embed its own future Git identity; the exact current candidate commit,
tree, workflow and inspected blobs are bound by the external lane receipts and
the generated `hepta.channel-matrix-readiness.v1` manifest.

## Repository source state

- Matrix apply/finalizer workflows and encoded staging sources are absent.
- Matrix qualification workflows are read-only and cannot commit or push source.
- Pull requests require three independently executed lanes from one workflow
  run and attempt: exact source head, deterministic base merge and GitHub's
  synthetic merge. The two merge lanes must have the same exact tree.
- Protected `main` pushes qualify the real integrated SHA and emit a separate
  post-merge readiness manifest. PR evidence is never reused as merge-SHA
  evidence.
- Every lane executes Rustdoc compile-fail boundaries proving that downstream
  safe code cannot import the final permit, forge the raw seal, override the
  authorized entry or escape to the raw Matrix client.
- Source closure discovers inputs only through `git ls-files -z`. Every reported
  path must pass `git ls-files --error-unmatch`, match the exact `HEAD:<path>`
  blob, be a canonical regular file below the checkout and remain unchanged
  before and after qualification. Generated directories, caches and downloaded
  artifacts are excluded from source closure by construction.
- The typed entered-use boundary remains intact. Post-entry proof, persistence,
  authority, session identity, cancellation, deadline, clock, store, permit and
  invariant faults retain distinct identity-free diagnostics while all remain
  conservative unknown effects.
- Fixed cumulative histograms cover claim-to-first-poll, final-use broker,
  SQLite owner operations, revocation refresh and physical transport. They are
  measurements, not target-host SLO claims.
- `PRODUCTION_QUALIFICATION_PROFILE.json` defines a closed external target and
  independent-acceptance evidence inventory. Candidate-authored CI cannot
  self-issue those results.

## Single readiness manifest

`scripts/channel_matrix_readiness.py` refuses mixed SHA, run, attempt, source
inventory, scenario registry, runner-image or target-triple evidence. Its output
contains at least:

```text
source_head_sha
frozen_source_sha
base_sha
deterministic_merge_sha
github_merge_sha
workflow_sha
final_merge_sha
workflow_run_id
attempt_id
runner_image
target_triple
Cargo.lock_hash
migration_hash
test_set_hash
qualification_profile_hash
implementation_map_hash
documentation_hash
source_tree_hash
artifact_hashes
```

Repository-controlled lane success may set `mergeReady=true`. It cannot set
`productionQualified=true`; target qualification and independent acceptance
remain separately governed. Missing, failed, skipped, canceled, stale or
cross-attempt evidence produces no readiness manifest and the required job fails.

## Evidence state

The current candidate must complete locked compilation, public-API negative
compile tests, all mapped Matrix native tests, all-target checks, strict Clippy,
rustfmt, Q01-Q29 JUnit accounting, tracked-only source provenance, clean-tree
verification and one non-mixable readiness manifest.

Real enrolled homeserver execution, encrypted-room and multi-device/session
rotation, protected restore, storage-fault recovery, sustained capacity/network
pressure, target-host measurements and distinct governed target/operator
signatures remain external gates. Therefore `productionImplementation`,
`productExecutionProved`, `deploymentQualificationComplete`,
`independentAcceptance`, `activation`, `promotion` and `release` remain false.
