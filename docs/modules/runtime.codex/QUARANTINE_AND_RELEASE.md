# runtime.codex quarantine and release protocol

This protocol governs operations for which a physical model/provider effect may have occurred but repository-controlled evidence cannot establish a terminal result. It is intentionally conservative.

## 1. Entry conditions

An operation enters quarantine when any of the following occurs after durable dispatch or effect entry:

- `turn/start` acknowledgement is lost and exact reconciliation finds no unique turn;
- App Server event delivery lags, disconnects or becomes ambiguous;
- process loss removes ephemeral App Server history;
- the owner generation, ingress identity or readiness is lost;
- duplicate, mismatched or incomplete history is observed;
- a terminal fact exists but its request/turn/transport correlation cannot be verified;
- the local and owner journals disagree and no exact pre-effect proof closes the discrepancy.

Quarantine retains the original operation identity and capacity. It never creates a replacement operation.

## 2. Non-authoritative signals

None of the following proves that an effect was not applied:

- elapsed time or a timeout;
- empty App Server history after process loss;
- absence of a provider bill at the time of inspection;
- an operator's recollection;
- process exit, restart or machine reboot;
- a missing log, metric or trace;
- a failed cancellation request;
- pressure to reclaim capacity.

These signals may trigger investigation but cannot authorize replay or release.

## 3. Resolution evidence classes

A quarantine may close only with one of these evidence classes:

### A. Exact provider terminal evidence

A provider/effect owner returns an authenticated terminal record bound to the original idempotency/operation key, request digest and provider account. The record must identify whether the effect completed, failed or was definitively rejected before admission.

### B. Exact App Server recovery

The authenticated original Agentd/App Server generation, or a qualified durable successor, returns one unique turn whose stable `client_user_message_id`, original input, thread/session, model/provider and terminal response all match the durable request.

### C. Definitive pre-admission rejection

A typed, authenticated rejection proves the handler did not admit the effect. Only registered rejection classes may release for a new operation; internal errors and unknown transport outcomes do not qualify.

### D. Signed independent disposition

An independently operated resolution authority issues a signed `RuntimeCodexResolutionV1`. This is an exceptional operational mechanism, not an unauthenticated manual override.

## 4. `RuntimeCodexResolutionV1`

The canonical record must bind at least:

```json
{
  "schemaVersion": 1,
  "operationId": "...",
  "requestSha256": "...",
  "dispatchSha256": "...",
  "agentId": "...",
  "agentGeneration": 1,
  "appServerSessionId": "...",
  "providerId": "...",
  "providerOperationId": "...",
  "disposition": "completed|failed|rejected_before_admission|remain_quarantined",
  "terminalEvidenceSha256": "...",
  "authorityEpoch": 1,
  "resolutionRevision": 1,
  "issuedAtUnixMs": 0,
  "expiresAtUnixMs": 0,
  "signerId": "...",
  "signature": "..."
}
```

The signer must be independent of the worker that requests the resolution. Revisions are monotonic; rollback or changed semantics under the same identity is a hard conflict.

A disposition of `remain_quarantined` records investigation progress but does not free capacity.

## 5. Release behavior

- `completed` and `failed` settle the original operation only; they never authorize replay.
- `rejected_before_admission` may release the original slot. A new attempt must use a new operation identity unless the downstream protocol itself supplies an idempotent retry contract.
- an unresolved or invalid record keeps quarantine active.
- operator tooling may attach notes and evidence digests but may not directly mutate the durable state.

## 6. Capacity and retention

Quarantined operations are bounded by configured count and bytes, but reaching the bound closes new admission rather than deleting uncertainty. Alerts must fire before exhaustion. Archival preserves all binding fields and signed evidence; restoring an archive cannot roll back the resolution frontier.

Recommended thresholds for a selected deployment must be measured, not copied blindly. At minimum alert on:

- first active quarantine;
- age exceeding the provider's normal terminal window;
- more than 50% of quarantine capacity consumed;
- any duplicate-effect conflict;
- any resolution signature, epoch or anti-rollback failure.

## 7. Anti-rollback

The resolution frontier must be anchored outside the writable worker filesystem, for example in a protected database with compare-and-swap revisioning, a transparency log, TPM-backed monotonic state, or an independently administered authority. Backups restore data but do not establish freshness by themselves.

## 8. Operator runbook

1. Fence automatic replay and confirm the original operation remains unique.
2. Capture exact local/owner/provider identities and current revisions.
3. Query the original App Server/provider with read-only reconciliation.
4. Validate evidence against the durable request and correlation digests.
5. Obtain an independently signed resolution when ordinary reconciliation cannot close the case.
6. Apply the resolution through the typed reconciliation API.
7. Verify both owner journals converge and capacity changes only after the durable commit.
8. Preserve the complete evidence bundle and post-incident analysis.

Deleting the record, editing the journal, changing the request ID, or issuing a replacement model call is not an incident response.
