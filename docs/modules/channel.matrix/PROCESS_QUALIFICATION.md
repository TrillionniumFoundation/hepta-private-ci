# channel.matrix process crash-consistency qualification

Status: **closed external contract; no current candidate pass is implied**.

## Authoritative backend and transport

The production module owns one private per-Agent SQLite database in WAL mode behind
one `matrixd` process lock and one supervisor process lease. PostgreSQL is not a
`channel.matrix` storage backend, so a PostgreSQL run cannot qualify this module.
The transport scope is an authenticated Matrix/Synapse execution using the exact
statically linked `MatrixSdkClient`; an in-memory fake or source fixture is not a
target receipt.

`PROCESS_FAULT_MATRIX.json` is the canonical closed scenario and invariant
inventory. It covers process cuts before and after final-use entry, remote
acceptance with lost local outcome, lease/token/generation fencing, dual-writer
and recovery-writer contention, network partition, sync rollback and prefix
replay, WAL/SHM corruption and restore, transient and persistent store failure,
cancellation on both sides of entry, journal pressure, archive/tombstone,
long-unknown fairness, grant-claim persistence failure, clock discontinuity and
JIT-claim sustained pressure.

## Evidence command

A protected target runner creates one out-of-checkout manifest plus one distinct
artifact per scenario, then validates it:

```sh
python3 scripts/channel_matrix_process_qualification.py \
  --manifest /protected/evidence/process-fault.manifest.json \
  --expected-commit "$CANDIDATE_SHA" \
  --expected-tree "$CANDIDATE_TREE" \
  --output /protected/evidence/process-fault.validation.json
```

The manifest binds the exact candidate, run and attempt, host/runner/target,
pinned homeserver image, Agentd/Matrixd/test binary/configuration digests,
process-identity ledger, backend and transport. Every scenario must be present
exactly once, pass all of its required invariants and own a distinct canonical
artifact.

## Production-evidence join

`process-fault.validation.json` is the only acceptable artifact for the
`process_fault_matrix` row in `PRODUCTION_QUALIFICATION_PROFILE.json`.
`scripts/channel_matrix_production_qualification.py` parses and revalidates that
nested result against the current process profile and exact candidate; an opaque
JSON file cannot satisfy the row.

Repository CI, the hermetic runner source, unit tests and this contract do not
establish target execution. Missing, failed, stale, duplicate, mixed-attempt or
tampered evidence keeps `productionQualified`, `activation`, `promotion`,
`release` and `authorityGranted` false.
