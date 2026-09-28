# channel.matrix failure and recovery

## 1. Failure classes

| Class | Examples | Required response |
|---|---|---|
| invalid/rejected | malformed identity, stale binding, digest drift, wrong signer | fail closed; no network effect |
| authority unavailable | broker/feed/socket failure, corrupt authority state before kernel entry | stop dispatch; retain durable queue |
| pre-entry network establishment | typed DNS/TLS/connect timeout or refusal before any possible adapter write | bounded retry with same transaction and a fresh claim/grant |
| entered-or-unknown | proof-write acknowledgement loss, grant expiry/revocation/identity/payload change after kernel entry, read timeout, reset, decode/ACK/response loss, cancellation after entry | indeterminate; retain the exact transaction and reconcile only |
| permanent remote rejection | authenticated rejection with no earlier accepted/unknown evidence | terminal failed |
| store unavailable/corrupt | SQLite I/O, schema/integrity mismatch | stop writer; operator recovery |
| lifecycle fence | Agent generation, release, binding or process lease mismatch | drain/stop; supervisor reconciles |
| capacity | unresolved ledger/outbox/broker/claim limit | reject new work; preserve existing evidence |

## 2. Retry rules

Retries preserve the stable Matrix transaction ID and derive a fresh random claim capability, final-use request and grant. Attempts/lease epochs are monotonic. Matrix `RetryAfter::Delay` and `RetryAfter::DateTime` are normalized to milliseconds, bounded by host policy and given stable transaction-derived jitter. Exponential fallback is capped. Exhausted ambiguous effects park for reconciliation instead of becoming failed.

A claim may be released through the pre-entry path only while kernel final-use entry has not succeeded. After entry, even when no transport poll is demonstrated, the proof write or its acknowledgement may be uncertain; the exact attempt must remain monotone and cannot be rewritten as canceled, revoked or expired pre-entry work.

## 3. Shutdown

Before kernel final-use entry, cancellation releases the current claim and unstarted rows in the claimed batch through the typed fenced path. After kernel entry or transport poll, cancellation is an entered/unknown external result and is recorded as indeterminate. Shutdown drains within grace, aborts remaining tasks and closes SQLite; it never edits attempts or clears evidence manually.

## 4. Restart recovery

1. Supervisor validates Matrix process lease against Agent generation, release, binding digest, process incarnation and plane epoch.
2. An exact live orphan may be adopted; stale or unverifiable processes are killed/rejected.
3. Matrixd obtains the process lock, verifies migrations 1-13, exact schema SQL and final-use/legacy-hold/terminal-qualification/recovery invariants, completes an initial durable sync, resumes exact threads and recovers pending inbox work.
4. Expired active claims that never crossed kernel entry receive an append-only `expired` event before a later attempt mints a new capability.
5. A dispatching attempt with a possible entered-use write or unknown proof acknowledgement is retained as unresolved; recovery never releases it by inference from process death.
6. Expired outbox leases are reclaimed with the same stable transaction and a higher attempt only when the durable state permits another attempt, except sealed legacy holds.
7. Migration 11 closes stale legacy claims, records claimed-only work as expired and later phases as indeterminate, materializes the unresolved ledger, and parks the queue row at the non-runnable maximum schedule.
8. Accepted/indeterminate dispatches remain unresolved until authenticated sync supplies matching server evidence. If a later attempt is merely claimed when the echo arrives, migration 12 qualifies the stable transaction with the earlier matching entered-use proof and closes the current claim without another effect.
9. Migration 13 preserves each pending inbox event identity while recording bounded recovery attempts, next-due time, closed-set failure class and monotone quarantine. Restart never manufactures a replacement event or clears quarantine by inference.

## 5. Corruption policy

Never delete the database, WAL, session store, authority state or audit rows to clear an error. Preserve the failed image, stop the writer and collect bounded schema/integrity diagnostics. Restore only from an authenticated compatible backup together with its authority/revocation frontier, then execute restore qualification.

## 6. Rollback

Binary rollback is allowed only when the predecessor understands every committed migration and durable record. Migrations 6-13 dispatch, claim, witness, canonical-content, entered-use, legacy-hold, remediation, cross-attempt terminal and inbox-recovery scheduling semantics cannot be ignored by an older runtime. Otherwise keep the current store owner and roll forward. Release rollback retains stable transaction identities, current redaction/revocation frontiers, parked legacy holds, recovery/quarantine state and unresolved effects.

## 7. Fault-injection points

Qualification injects failure:

- after queue claim and before random capability commit;
- after capability claim and before grant;
- after nonce burn and before witness commit;
- after witness commit and before dispatching;
- after dispatching and before final revocation/expiry refresh;
- after kernel final-use entry and before entered-use proof commit;
- after entered-use proof commit but before its acknowledgement is observed;
- while revocation refresh or identity/content validation consumes the remaining grant lifetime;
- immediately before lazy transport polling;
- after server acceptance and before SDK/local acknowledgement;
- after transport observation and before fenced retry/closure;
- after sync mutation and before transaction commit;
- after terminal commit and before caller acknowledgement;
- during supervisor process-lease persistence/adoption;
- during authenticated backup/restore with expired claims and redacted/revoked content.

Each fixture records whether kernel entry occurred, whether adapter polling occurred, stable transaction, attempt/lease, claim-token digest, authority frontier/witness digest, typed failure class and final durable state. A missing adapter poll does not authorize pre-entry release once kernel entry is known or its durable proof-write acknowledgement is uncertain.

## Bounded ingress recovery

[Recovery and diagnostics](RECOVERY_DIAGNOSTICS.md) defines migration-13 scheduling,
per-event backoff/quarantine, fatal owner errors, exact-thread reconciliation,
cooperative cancellation boundaries and the unresolved-association limitation.
