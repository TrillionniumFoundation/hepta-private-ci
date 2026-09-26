# channel.matrix failure and recovery

## 1. Failure classes

| Class | Examples | Required response |
|---|---|---|
| invalid/rejected | malformed identity, stale binding, digest drift, wrong signer | fail closed; no network effect |
| authority unavailable | broker/feed/socket failure, corrupt authority state | stop dispatch; retain durable queue |
| pre-entry network establishment | typed DNS/TLS/connect timeout or refusal | bounded retry with same transaction and a fresh claim/grant |
| accepted-or-unknown | read timeout, reset, decode/ACK/response loss, cancellation after entry | indeterminate; reconcile only |
| permanent remote rejection | authenticated rejection with no earlier accepted/unknown evidence | terminal failed |
| store unavailable/corrupt | SQLite I/O, schema/integrity mismatch | stop writer; operator recovery |
| lifecycle fence | Agent generation, release, binding or process lease mismatch | drain/stop; supervisor reconciles |
| capacity | unresolved ledger/outbox/broker/claim limit | reject new work; preserve existing evidence |

## 2. Retry rules

Retries preserve the stable Matrix transaction ID and derive a fresh random claim capability, final-use request and grant. Attempts/lease epochs are monotonic. Matrix `RetryAfter::Delay` and `RetryAfter::DateTime` are normalized to milliseconds, bounded by host policy and given stable transaction-derived jitter. Exponential fallback is capped. Exhausted ambiguous effects park for reconciliation instead of becoming failed.

## 3. Shutdown

Before physical entry, cancellation releases the current claim and unstarted rows in the claimed batch through the typed fenced path. After verified-use entry or transport poll, cancellation is an unknown external result and is recorded as indeterminate. Shutdown drains within grace, aborts remaining tasks and closes SQLite; it never edits attempts or clears evidence manually.

## 4. Restart recovery

1. Supervisor validates Matrix process lease against Agent generation, release, binding digest, process incarnation and plane epoch.
2. An exact live orphan may be adopted; stale or unverifiable processes are killed/rejected.
3. Matrixd obtains the process lock, verifies migrations 1-7 and final-use state, completes an initial durable sync, resumes exact threads and recovers pending inbox work.
4. Expired active claims receive an append-only `expired` event before a later attempt mints a new capability.
5. Expired outbox leases are reclaimed with the same stable transaction and a higher attempt.
6. Accepted/indeterminate dispatches remain unresolved until authenticated sync supplies matching server evidence.

## 5. Corruption policy

Never delete the database, WAL, session store, authority state or audit rows to clear an error. Preserve the failed image, stop the writer and collect bounded schema/integrity diagnostics. Restore only from an authenticated compatible backup together with its authority/revocation frontier, then execute restore qualification.

## 6. Rollback

Binary rollback is allowed only when the predecessor understands every committed migration and durable record. Migrations 6-7 dispatch, claim, witness and attempt-event rows cannot be ignored by an older sender. Otherwise keep the current store owner and roll forward. Release rollback retains stable transaction identities, current redaction/revocation frontiers and unresolved effects.

## 7. Fault-injection points

Qualification injects failure:

- after queue claim and before random capability commit;
- after capability claim and before grant;
- after nonce burn and before witness commit;
- after witness commit and before dispatching;
- after dispatching and before final revocation refresh;
- immediately before lazy transport polling;
- after server acceptance and before SDK/local acknowledgement;
- after transport observation and before fenced retry/closure;
- after sync mutation and before transaction commit;
- after terminal commit and before caller acknowledgement;
- during supervisor process-lease persistence/adoption;
- during authenticated backup/restore with expired claims and redacted/revoked content.

Each fixture records whether adapter entry occurred, stable transaction, attempt/lease, claim-token digest, authority frontier/witness digest, typed failure class and final durable state.
