# runtime.codex quarantine and release protocol

This protocol governs a `runtime.codex` operation whose physical provider effect cannot be proved terminal and cannot be proved absent. Its primary case is loss of the original App Server process or ephemeral thread history after a possible `turn/start` send. The safe default is quarantine: capacity remains owned, the operation is not replayed, and no success is fabricated.

## 1. Non-negotiable rules

1. Missing App Server history is not evidence that the provider request was absent.
2. Timeout, process death, socket reset, event lag, missing acknowledgement, or an empty `thread/read` result never make the same operation retry-safe.
3. A repository component cannot authorize its own release. Resolution authority must be independent of the worker, Agentd, adapter and journal writers whose state is being resolved.
4. A human comment, database edit, unsigned file, boolean flag, model output, or adapter receipt is not release authority.
5. A resolution cannot rewrite provider facts. If a late exact terminal observation arrives, it is appended and reconciled rather than overwritten.
6. Retrying work requires a new operation identity. The quarantined operation remains permanently non-replayable.

## 2. Quarantine record

A durable `QuarantinedEffectV1` record binds at least:

- operation id and source admission digest;
- runtime.codex request and payload digests;
- local dispatch digest and revision;
- Agentd run id, revision and dispatch digest;
- authority epoch, revocation revision, complete revocation-head digest and authority-witness digest;
- Agent generation, App Server session/version, Codex-home digest and connection identity;
- thread id, optional turn id, stable client user-message id and user-input digest;
- model and provider identities;
- first-unknown time, last reconciliation time and reconciliation attempt count;
- all observed transport, App Server and provider evidence digests;
- immutable reason code and bounded redacted diagnostics.

The record is append-only with monotonic revision. Identical re-publication is idempotent; any semantic drift for the same operation is a conflict.

## 3. Independent resolution envelope

A release decision is represented by a signed `QuarantineResolutionV1` envelope. Its canonical payload includes:

```json
{
  "schemaVersion": 1,
  "resolutionId": "stable-id",
  "operationId": "stable-id",
  "quarantineRevision": 7,
  "requestSha256": "64-hex",
  "dispatchSha256": "64-hex",
  "evidenceSetSha256": "64-hex",
  "authorityEpoch": 12,
  "resolutionSequence": 1042,
  "nonce": "64-hex",
  "notBeforeUnixMs": 0,
  "expiresAtUnixMs": 0,
  "disposition": "terminal_observed | abandon_without_replay | authorize_new_operation",
  "terminal": null,
  "newOperationConstraints": null,
  "reasonCode": "bounded-registered-code",
  "signerId": "independent-quarantine-authority"
}
```

The signature covers domain separation, the complete canonical payload and the current anti-rollback frontier. The verifier pins signer identity and public key through protected host configuration. The private key is never available to the worker or Agentd.

## 4. Allowed dispositions

### `terminal_observed`

Requires independently authenticated provider/App Server evidence that identifies the exact original request and terminal outcome. Success additionally requires exact terminal response correlation and must still respect sticky local cancellation, timeout and owner-loss semantics. A provider completion does not necessarily make the boundary successful.

### `abandon_without_replay`

Closes operational capacity while permanently recording that terminality is unknown. It must not create success, provider failure, or retry-safe evidence. This is appropriate only when independent policy accepts the unresolved external effect and explicitly forbids replay.

### `authorize_new_operation`

Allows a separate, newly admitted operation under explicit constraints. It never reopens or resends the quarantined identity. The envelope binds the new objective/request scope, earliest execution time, maximum attempts (normally one), provider idempotency key policy and any compensation prerequisites.

## 5. Verification and anti-rollback

Before applying a resolution, the owner verifies:

1. schema, bounds, canonical encoding and domain separation;
2. signer identity, signature and protected key configuration;
3. exact operation, request, dispatch and evidence-set digests;
4. exact current quarantine revision;
5. non-expired validity window using trusted-time policy;
6. monotonic authority epoch and strictly increasing resolution sequence;
7. nonce non-reuse;
8. that no newer terminal fact or resolution has already been committed;
9. disposition-specific evidence and policy constraints.

The sequence frontier is persisted with fsync and protected by an external anti-rollback mechanism. Restoring a local backup, moving a state directory or replacing a host is not sufficient authority to reduce the frontier. Recovery must obtain an independently signed frontier checkpoint before accepting further decisions.

## 6. Operational procedure

1. Fence automatic replay and retain the capacity slot.
2. Capture the exact quarantine record and all evidence digests.
3. Continue bounded same-operation reconciliation against the authenticated original generation when possible.
4. Escalate to the independent quarantine authority after the registered reconciliation window.
5. Require dual operator review for any `authorize_new_operation` decision unless an independently approved automated policy is registered.
6. Verify and durably apply the signed envelope transactionally.
7. Emit an audit receipt binding predecessor revision, decision, signer, frontier, resulting state and any new operation id.
8. Continue accepting late immutable provider facts; never delete the original quarantine lineage.

## 7. Alerts and service objectives

Alert immediately on signature failure, frontier rollback, nonce reuse, semantic conflict, attempted same-operation replay or a release without an exact current revision. Track quarantine age, unresolved capacity, reconciliation attempts, late-terminal rate, resolution disposition and independent-authority latency. Thresholds are deployment-profile facts and must not be invented by repository source.

## 8. Claim boundary

This document defines the repository protocol. It does not prove that an independent quarantine authority, trusted clock, signer-key custody, anti-rollback store, real-provider evidence source or operator process is deployed. Those remain target-host and independent-acceptance gates in `PRODUCTION_QUALIFICATION.md`.
