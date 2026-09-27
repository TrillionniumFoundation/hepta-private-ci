# auth.authbus operations

## Deployment topology

Run one `AuthBusAuthorityHost` per authority database. Place the SQLite database and its owner-lock database in a private local directory. Place the checkpoint in a separate private filesystem or independently retained volume so one rollback cannot restore both domains. Agentd owns signed-message replay/outbox state; Bao is a product caller and never becomes an AuthBus writer.

The production topology has four named roles:

- **authority owner:** opens `AuthBusAuthorityHost`, holds the owner fence and publishes checkpoints;
- **trusted-time verifier:** verifies signed monotonic time attestations before maintenance or mutations;
- **settlement signer:** HSM/KMS-backed signer enrolled only for `Settlement` purpose;
- **observer/exporter:** reads the bounded operational snapshot and exports metrics without write capability.

## Startup

1. Verify private directory ownership and modes.
2. Resolve immutable database/checkpoint paths and owner identity.
3. For first installation only, call the explicit bootstrap path when neither database nor checkpoint exists.
4. For every later start, call open; never recreate a missing witness.
5. Acquire the single-owner fence before database recovery or checkpoint publication.
6. Verify SQLite integrity, migrations, live schema and checkpoint generation/digest.
7. Run one bounded restart-reconciliation and expiration-maintenance batch.
8. Keep write admission fail-closed while `recovery_required` remains true; the authority worker continues bounded batches.
9. Export the operational snapshot and evaluate alerts before declaring ready.

Readiness requires: owner fence held, checkpoint not dirty, `recovery_required=false`, zero expired active holds, current trusted-time source, and no critical AuthBus alert.

## Authority worker

The named authority worker is the only periodic maintenance path. Every tick receives a freshly verified `TrustedTimeSample`, performs bounded restart reconciliation, bounded expired-reservation sweep, checkpoint publication, operational snapshot generation and SLO evaluation. Batch size is in `1..=1024`; missed ticks are skipped rather than accumulated. A worker error is a readiness failure and pages the authority owner.

## Routine procedures

### Enroll or rotate an issuer

Follow `KEY_ROTATION.md`. Enroll only an explicit purpose. Publish the new registry/checkpoint state before enabling a signer. Revoke the predecessor before retirement. Never edit public-key bytes in place.

### Compact terminal reservations

Compact only `Settled`, `Released`, `Expired` or `Cancelled` rows older than the approved retention window. Keep operation identity and terminal evidence digest in the archive. Run bounded batches and verify checkpoint publication after each batch.

### Backup

Take a consistent SQLite backup and capture the current external checkpoint separately. Label both with authority store identity, source SHA, schema digest, checkpoint generation and timestamp. A backup without its matching witness is not restorable.

## Incident classes

- **Owner collision:** do not steal the lock. Identify the live PID/service generation. Stop the duplicate deployment.
- **Checkpoint dirty/publish failure:** stop new mutations, preserve database and external witness, then follow `RECOVERY.md`.
- **Expired-active growth:** verify authority worker health and trusted time; increase batch frequency, not unbounded batch size.
- **Indeterminate reservation:** do not refund automatically. Reconcile with authenticated terminal provider evidence.
- **Issuer verification spike:** revoke the affected epoch if compromise is suspected and preserve rejected message digests for investigation.
- **Schema/integrity failure:** isolate the store; never auto-recreate or migrate around a failed check.

## Shutdown

Stop new admission, complete or fence in-flight owner calls, run one final maintenance tick, require a clean checkpoint, close the SQLite pool and then release the owner fence. Forced termination is safe only because the OS releases the fence and restart reconciliation preserves ambiguous effects as indeterminate.
