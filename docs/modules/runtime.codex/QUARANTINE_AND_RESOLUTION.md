# runtime.codex quarantine and indeterminate-effect resolution

This document is the fail-closed operating contract for a runtime.codex request
whose physical `turn/start` outcome cannot be reconstructed from the original
App Server connection or from `thread/read(includeTurns=true)`. It does not
turn operator judgement into provider authority and it never authorizes replay
of the original operation.

The machine contract is
[`quarantine-resolution-v1.schema.json`](quarantine-resolution-v1.schema.json).
A repository test fixture or unsigned JSON file is not a valid production
resolution. Production decisions require an independently controlled signer,
monotonic authority state and an externally protected evidence archive.

## 1. Entry conditions

An operation enters quarantine when all of the following are true:

1. the native journal durably contains the exact runtime.codex dispatch and
   request correlation;
2. the local pre-effect proof is absent, because effect entry may have occurred;
3. no exact `turn/started` or terminal event can be recovered from the original
   connection;
4. reopen cannot find exactly one matching turn by stable
   `client_user_message_id` and original `UserMessage` content; and
5. there is no stronger typed App Server rejection proving refusal before
   admission.

Transport loss, timeout, process death, empty ephemeral history, an operator's
belief that the request probably failed, or elapsed wall-clock time are not
proof of non-application.

## 2. Quarantine invariant

While quarantined:

- the original operation ID remains permanently occupied;
- the durable execution slot remains unresolved unless a signed resolution is
  accepted;
- no code path may issue another `turn/start` for the original operation;
- no receipt may claim success, failure, interruption or zero usage without
  matching terminal evidence;
- cancellation and cleanup may stop future observation but cannot manufacture a
  provider terminal fact;
- human access is read-only except through the signed resolution port.

The owner may compact logs, but it must preserve request identity, authority
witness, source admission, provider binding, all evidence digests and the
quarantine lineage.

## 3. Allowed decisions

Exactly three decisions exist.

### `confirmed_terminal`

Use only when independent evidence identifies exactly one provider/App Server
turn for the original request and proves its terminal status. The decision must
include the exact turn ID and terminal-response digest. It closes the original
operation and never authorizes retry.

### `proven_not_applied`

Use only when an authoritative provider idempotency lookup, admission ledger or
other independently qualified negative oracle proves that the original request
did not cross the provider admission boundary. Absence from ephemeral App Server
history is insufficient.

The original operation closes as not applied. Any subsequent attempt is a **new
operation** with a new operation ID, new deadline, new final-use grant and new
authority witness. The signed decision binds the replacement operation ID; it
never revives or refunds the original grant.

### `permanent_quarantine`

Use when the available evidence cannot safely distinguish applied from not
applied. It is terminal for scheduling and capacity governance, but does not
assert a provider result. No replacement operation is authorized by this
decision.

## 4. Signed decision binding

The signature covers canonical bytes for every field except the signature
itself. The decision binds:

- original operation ID and runtime.codex request digest;
- durable source-admission digest;
- Agent identity and generation;
- App Server session and stable client message identity;
- provider operation identity when available;
- decision and retry disposition;
- terminal identity when applicable;
- all evidence-role digests;
- signer identity, authority epoch, decision revision, validity window and
  nonce; and
- replacement operation ID when and only when non-application is proven.

Unknown fields, duplicate evidence roles with conflicting digests, empty or
zero digests, expired decisions, stale epochs/revisions, nonce reuse, signer/key
mismatch and semantic inconsistencies fail closed.

## 5. Monotonic and anti-rollback requirements

The consumer keeps a durable resolution frontier containing at least:

```text
signer_id
key_id / verifying-key digest
authority_epoch
decision_revision
accepted nonces or an equivalent replay frontier
operation -> accepted decision digest
```

An update is legal only if it is identical and idempotent or strictly advances
the configured authority frontier. Restoring a local file is not an
anti-rollback oracle. Production qualification must bind this frontier to an
external CAS, TPM/TEE-backed monotonic value, append-only transparency log, or
another independently administered rollback-resistant system.

Key rotation increments the authority epoch and follows a separately approved
root-of-trust transition. A lower epoch or revision is never accepted after a
higher value has been observed.

## 6. Evidence requirements

At least one evidence item is mandatory. `proven_not_applied` requires a
qualified negative oracle such as `provider_idempotency_lookup` or
`network_admission_log`; an operator investigation by itself can only support
`permanent_quarantine`.

`confirmed_terminal` requires provider/App Server terminal evidence and exact
request correlation. Multiple matching provider operations, conflicting
terminal statuses, session drift, input drift or reused client message IDs are
hard conflicts and remain quarantined.

Sensitive payloads do not enter the resolution record. Evidence is retained in
a protected archive and referenced by digest and bounded location metadata.

## 7. Owner transition

The resolution consumer performs one atomic owner transaction:

1. lock the original unresolved record and current authority frontier;
2. verify signature, time, epoch, revision, nonce and exact operation binding;
3. verify semantic and evidence-role requirements;
4. append the decision and advance the external/local monotonic frontier;
5. close or permanently quarantine the original owner record;
6. release capacity only according to the accepted decision; and
7. emit an immutable audit receipt binding the previous state, decision digest,
   new state and frontier.

A crash before commit leaves the operation unresolved. A crash after commit is
idempotently recoverable from the exact decision digest. There is no partially
accepted state and no fallback to an unsigned operator override.

## 8. Separation from deployment authority

A signed quarantine decision resolves one historical operation only. It does
not establish target-host trust, provider qualification, canary acceptance,
promotion or release. The signer that resolves history must not implicitly gain
permission to issue model requests or alter unrelated Agentd state.

## 9. Required tests

Repository and target-host qualification must cover:

- forged signature, wrong key and wrong signer;
- stale authority epoch/revision and rollback after restore;
- nonce replay and same operation with different decision bytes;
- request, session, generation, source-admission and client-message mismatch;
- terminal decision without exact terminal evidence;
- non-applied decision based only on missing ephemeral history;
- replacement operation equal to the original operation;
- duplicate/concurrent resolution submissions;
- crash before and after decision/frontier commit;
- capacity release only after a valid atomic transition; and
- permanent quarantine surviving restart, compaction and backup restore.
