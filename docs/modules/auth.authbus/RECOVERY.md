# auth.authbus recovery

Status: production recovery procedure

Recovery is fail-closed. The objective is to re-establish the authoritative
frontier without inventing issuer trust, releasing ambiguous quota, lowering a
generation or rewriting history.

## Roles and approvals

Every recovery requires:

- incident commander;
- AuthBus authority owner;
- security approver for any checkpoint, issuer or quota repair;
- evidence recorder responsible for immutable command/output hashes.

No individual may both propose and approve manual state mutation.

## Initial containment

1. Mark the product caller unready and stop new admission.
2. Preserve the process, database, WAL/SHM files, checkpoint, owner-lock file and
   relevant logs. Do not delete or overwrite them.
3. Record source SHA, binary digest, service identity, host boot ID, owner ID,
   file metadata and current time from an independent clock.
4. Confirm whether a process still holds the owner lock. Kill only through the
   service manager and preserve its exit evidence.
5. Copy artifacts to a read-only incident directory and hash every file.

## Classification

### A. Clean restart with unresolved dispatch

Symptoms: database/checkpoint integrity passes; `dispatch_attempted` reservations
remain after an unplanned stop.

Procedure:

1. Start the same qualified binary with the same database, checkpoint and owner
   ID.
2. Let startup reconciliation mark unresolved post-dispatch work
   indeterminate in bounded batches.
3. Run maintenance until startup backlog is zero.
4. Reconcile each indeterminate operation against provider receipts using exact
   operation/reservation/digest binding.
5. Resume admission only when checkpoint dirty duration is zero and all critical
   alerts clear.

Never release indeterminate quota merely because its reservation expired.

### B. Expired held-reservation backlog

Symptoms: held reservations have passed expiry; no dispatch attempt exists.

Procedure:

1. Verify a fresh trusted-time attestation.
2. Run bounded sweeps; record each sweep receipt, counts and remaining backlog.
3. Confirm quota conservation before and after every batch.
4. Stop and escalate on a negative balance, revision conflict or digest mismatch.
5. Resume normal cadence when the remaining count is zero.

### C. Checkpoint behind database

Symptoms: authoritative database frontier is exactly one supported publish step
ahead and the database records a dirty/pending checkpoint state.

Procedure:

1. Acquire the normal owner lock with the qualified recovery binary.
2. Allow the normal compare-and-publish path to write the next checkpoint.
3. Verify file fsync, parent-directory fsync, re-read and digest equality.
4. Record old/new generation and digest.

Do not hand-edit checkpoint JSON.

### D. Checkpoint ahead, digest mismatch or generation rollback

Symptoms: witness generation is ahead of the database, a same-generation digest
differs, or either generation regresses.

Procedure:

1. Keep service unready.
2. Preserve all artifacts and storage snapshots.
3. Determine whether the database, witness or storage snapshot was restored
   independently.
4. Reconstruct the last mutually attested frontier from immutable release,
   backup and audit receipts.
5. Restore database and witness as one approved pair into new private paths.
6. Run offline integrity/schema verification and full qualification replay.
7. Obtain security approval before replacing production paths.

There is no automatic “choose the newer file” rule.

### E. Missing checkpoint

A missing witness for an existing authority is a critical incident. Automatic
bootstrap is allowed only for a demonstrably new database with no prior
checkpoint metadata. Otherwise follow classification D and restore an attested
pair.

### F. SQLite integrity or schema failure

1. Stop all writers and acquire an offline snapshot.
2. Run `quick_check`, `integrity_check`, `foreign_key_check`, migration history
   verification and schema digest comparison on the copy.
3. Prefer restoration of the last verified database/checkpoint pair.
4. Logical export/import is allowed only with a versioned repair tool that
   validates every ID, width, enum, revision, quota invariant and digest.
5. Never issue ad hoc `UPDATE` or `DELETE` statements against production state.

### G. Owner-lock collision

1. Identify both process identities, namespaces and database paths.
2. Do not remove the lock file.
3. Terminate the non-designated process through its supervisor.
4. Verify that the designated owner still holds the original lock inode.
5. If two processes performed mutations, classify as checkpoint/database
   divergence and follow D.

### H. Issuer compromise

Follow `KEY_ROTATION.md` emergency revocation. Stop affected admissions, revoke
that exact purpose/issuer/epoch, quarantine outstanding deliveries only through a
sealed revoked registration or issuer-retirement receipt, and investigate all
operations admitted under the epoch.

## Disk-full and fsync failure

- Treat any database, checkpoint-file or checkpoint-directory fsync error as a
  failed mutation acknowledgement.
- Stop new admission and preserve the dirty state.
- Restore capacity without deleting authority, WAL, checkpoint or audit files.
- Retry only through the normal host synchronization path.
- If caller outcome is unknown, classify the related operation indeterminate.

## Recovery completion criteria

Recovery is complete only when:

- exactly one owner is active;
- pre/post-migration integrity and schema checks pass;
- database and checkpoint generation/digest agree;
- checkpoint dirty duration is zero;
- expired-held and startup-recovery backlogs are zero or within approved bounded
  continuation;
- every ambiguous operation is explicitly indeterminate or reconciled;
- current issuer/trusted-time state is verified;
- a recovery receipt records source SHA, schema digest, artifact hashes, commands,
  approvals and resulting frontier;
- exact-head focused qualification passes for the recovered binary.

## Prohibited actions

- deleting the owner-lock path to “unlock” a live process;
- fabricating an issuer registration or setting a revoked flag in caller memory;
- copying only the database or only the checkpoint from backup;
- decrementing generations or revisions;
- releasing quota for an unknown post-dispatch outcome;
- treating cancelled, skipped or static qualification as recovery success.
