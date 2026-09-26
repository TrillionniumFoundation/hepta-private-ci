# channel.matrix failure and recovery

## 1. Failure classes

| Class | Examples | Required response |
|---|---|---|
| invalid/rejected | malformed identity, stale binding, digest drift, wrong signer | fail closed; no network effect |
| authority unavailable | broker/feed/socket failure, corrupt authority state | stop dispatch; retain durable queue |
| safe pre-entry transport failure | proven DNS/connect failure before effect entry | bounded retry with same transaction |
| accepted-or-unknown | read timeout, reset, ACK loss, cancellation after entry | indeterminate; reconcile only |
| permanent remote rejection | authenticated rejection with no earlier acceptance | terminal failed |
| store unavailable/corrupt | SQLite I/O, schema/integrity mismatch | stop writer; operator recovery |
| lifecycle fence | Agent generation, release, binding or process lease mismatch | drain/stop; supervisor reconciles |
| capacity | unresolved ledger/outbox/broker claim limit | reject new work; preserve existing evidence |

## 2. Retry rules

Retries preserve the stable Matrix transaction ID and derive a fresh per-attempt final-use request and grant. Exponential delay is bounded. Matrix `retry_after_ms` takes precedence after validation and bounding; deterministic or random jitter prevents synchronized retry storms. Exhausted ambiguous effects park for reconciliation instead of becoming failed.

## 3. Shutdown

Before physical effect entry, cancellation releases the current claim and every unstarted row in the claimed batch back to retry state using the exact attempt fence. After effect entry, cancellation is an unknown external result and must be recorded as indeterminate. Shutdown drains within the configured grace, aborts remaining tasks and closes SQLite.

## 4. Restart recovery

1. Supervisor validates the persisted Matrix process lease against Agent generation, release, binding digest, process incarnation and plane epoch.
2. An exact live orphan may be adopted; stale or unverifiable processes are killed/rejected.
3. Matrixd obtains the process lock, verifies the store and final-use state, completes an initial durable sync, resumes exact threads and recovers pending inbox work.
4. Expired outbox leases are reclaimed with the same stable transaction.
5. Accepted/indeterminate dispatches remain unresolved until sync supplies matching server evidence.

## 5. Corruption policy

Never delete the database, authority state or journal to clear an error. Preserve the failed image, stop the writer and collect schema/integrity diagnostics. Restore only from an authenticated compatible backup together with its authority/revocation frontier, then run the restore qualification matrix.

## 6. Rollback

Binary rollback is allowed only when the predecessor understands every committed migration and durable record. Migration 6 dispatch records and authority claims cannot be ignored by an older sender. Otherwise keep the new store owner and roll forward. Release rollback must retain stable transaction identities and current redaction/revocation frontiers.

## 7. Fault-injection points

Qualification must inject failure:

- before dispatch row commit;
- after nonce burn and before Matrix claim commit;
- after claim commit and before final revocation refresh;
- immediately before lazy transport polling;
- after server acceptance and before SDK response;
- after transport observation and before retry scheduling;
- after sync mutation and before transaction commit;
- after terminal commit and before caller acknowledgement;
- during supervisor process-lease persistence/adoption;
- during backup/restore with redacted and revoked content.

Each fixture records whether network entry occurred, the stable transaction, attempt, lease fence, authority frontier and final durable state.
