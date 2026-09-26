# Privacy, export and delete runbook

## Export

Authenticate the requester and exact Agent/workspace scope.  Acquire one read snapshot, bind its cut digest and observation time, export only current permitted fields and citations, redact secrets/provider credentials, and emit a DENY_ALL export receipt.  Pagination must remain on the same cut; drift restarts the export rather than mixing generations.

## Logical delete

Record an explicit source event and append a successor tombstone with compare-and-swap predecessor.  Commit the empty fact set and projection update in the same transaction.  Revalidate retrieval and shared-use grants; revoked or stale consumers must stop using the record.

## Physical delete

Create a prune plan under ADR-0001, enumerate database/WAL/backups/derived artifacts, honor legal holds, obtain each owner’s receipt and publish a new exact-cut witness.  Do not claim physical erase while any required disposition is pending, unavailable or indeterminate.  Model unlearning is reported separately.

## Incident stop

On owner mismatch, rollback evidence, stale/revoked authority, pointer ambiguity or secret leakage: fence new writes, preserve descriptors and receipts, revoke the authority generation, mark host bootstrap state indeterminate where applicable, and require a new trusted recovery ceremony.
