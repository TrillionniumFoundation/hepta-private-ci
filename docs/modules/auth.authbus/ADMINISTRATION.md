# AuthBus administration tool

`hepta-authbus-admin` is the source-controlled, fail-closed administration
entrypoint for the single-owner authority store. It uses the public
`AuthBusAuthorityHost` boundary; it cannot construct or import the crate-private
`AuthBusAuthorityStore`.

The tool is intended to run with product traffic stopped. It acquires the same
process-local and Linux OFD owner fence as the product and keeps the host alive
for the full operation.

## Bootstrap

```text
hepta-authbus-admin bootstrap \
  --database /private/authbus/authority.sqlite \
  --checkpoint /independent/authbus/authority.checkpoint.json \
  --owner-id production-authbus-owner
```

Bootstrap succeeds only when both files are absent, both parents are canonical
private directories, and database/checkpoint parents are different. It creates
the migration-complete database, seeds the authority frontier and creates
generation 1 of the independent witness. Bootstrap is never a repair command.

## Backup

```text
hepta-authbus-admin backup \
  --database /private/authbus/authority.sqlite \
  --checkpoint /independent/authbus/authority.checkpoint.json \
  --owner-id production-authbus-owner \
  --database-out /backup-a/authbus/authority.sqlite \
  --checkpoint-out /backup-b/authbus/authority.checkpoint.json \
  --manifest /backup-manifests/authbus-2026-09-29.json
```

The command:

1. opens the production owner and acquires its single-writer fence;
2. reconciles the authority checkpoint;
3. runs `quick_check` and `foreign_key_check`;
4. checkpoints and truncates the WAL while no other owner operation exists;
5. copies the SQLite database and external witness to separate private
   directories with create-new, mode `0600`, file fsync and directory fsync;
6. writes a create-new manifest binding owner identity, paths, byte lengths,
   SHA-256 values and checkpoint generation/digest.

A partial backup is removed on error. The destination database and witness are a
pair; neither member is independently restorable.

## Restore check

Run restore-check only on a staged copy of the backup pair:

```text
hepta-authbus-admin restore-check \
  --database /restore-a/authbus/authority.sqlite \
  --checkpoint /restore-b/authbus/authority.checkpoint.json \
  --owner-id production-authbus-owner \
  --manifest /restore-manifests/authbus-2026-09-29.json
```

The command verifies manifest identity, lengths and SHA-256 values before
opening the pair through the production `AuthBusAuthorityHost::open` recovery
path. It then reconciles the checkpoint and emits a
`hepta.authbus.restore-check-receipt.v1` receipt.

The staged database may be forward-migrated by the checked binary. Never run
restore-check against the only retained backup copy. Production restore still
requires the exact qualified binary, target-host disk qualification, change
approval and an explicit traffic cutover decision.

## Safety rules

- All paths are absolute.
- New files are create-new; the tool never overwrites a backup or manifest.
- Database and checkpoint parents must be distinct private directories.
- The source owner fence remains held throughout backup.
- No missing witness is reconstructed for an existing database.
- A digest mismatch, owner mismatch, integrity failure, busy WAL checkpoint or
  unsafe path aborts the operation.
- Receipts are observations, not activation or release authority.

Unit qualification exercises bootstrap, matched backup creation and restore
verification through the real host.
