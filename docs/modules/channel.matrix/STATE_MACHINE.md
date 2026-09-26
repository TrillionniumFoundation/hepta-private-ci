# channel.matrix durable state machine

The authoritative send truth is owned by `MatrixDurableStore`. The SDK sender, compatibility observer and runtime never own a second ledger. `send_observer.rs` is read-only projection over durable dispatch state.

## 1. Conceptual and native phases

```text
Prepared
  -> Claimed(attempt, lease_epoch, opaque_claim_token)
  -> Authorized(verified-use witness, revocation head)
  -> Dispatching(final revocation refresh, token consumed)
  -> TransportAccepted
  -> Confirmed
  -> Redacted

Pre-entry exits: Revoked | Canceled | Expired | PermanentlyRejected
Post-entry uncertainty: Indeterminate
```

Native state is split deliberately:

| Surface | Responsibility |
|---|---|
| `outbox_messages` | bounded scheduling, lease and stable Matrix transaction identity |
| `matrix_dispatch_ledger` | one immutable logical-send identity and terminal truth |
| `matrix_dispatch_attempt_claims` | immutable `(transaction, attempt, lease_epoch, claim_token_sha256)` identity |
| `matrix_dispatch_active_claims` | current nonterminal claim and `claimed/authorized/dispatching` phase |
| `matrix_dispatch_authority_witnesses` | exact final-use witness and revocation-head digests |
| `matrix_dispatch_attempt_events` | append-only typed attempt history |
| `matrix_dispatch_observations` | transport, homeserver and redaction observations |

Only the claim-token digest is durable. The raw 32-byte capability is process-private and must accompany every active-claim transition.

## 2. Identity invariants

For each logical send:

- `operation_id = "matrix.send:" + stable_txn_id`;
- `stable_txn_id` never changes across retry, restart or reconciliation;
- operation ID and stable transaction ID are unique;
- accepted and terminal event IDs are unique where present;
- room, binding revision, Matrix-plane generation, canonical payload digest and replacement target are immutable;
- `attempt > 0`, `lease_epoch = attempt`, and attempts are monotonic;
- each attempt has one immutable random claim capability and at most one immutable authority witness;
- grant ID, request/scope/payload digests, authority epoch and revocation frontier are bound to the exact attempt;
- exact duplicate observations are idempotent; semantic drift is a conflict.

## 3. Allowed transitions

| Current | Trigger | Next | Required durable evidence |
|---|---|---|---|
| absent | outbox admission | prepared logical identity | stable transaction and canonical payload |
| queued | bounded claim | claimed | new attempt/lease, random capability digest, `claimed` event |
| claimed | durable final-use verification | authorized | witness digest, revocation-head digest, grant identity, `authorized` event |
| authorized | final persistence before I/O | dispatching | exact live token/lease, `dispatching` event |
| dispatching | SDK returns valid event ID | accepted | `transport_accepted` observation/event; not terminal success |
| dispatching | timeout/reset/unknown response | indeterminate | typed failure class and optional retry hint |
| dispatching | proven pre-effect permanent rejection | failed | no earlier accepted evidence and `permanently_rejected` event |
| accepted/indeterminate | matching authenticated `/sync` event | succeeded | exact room, transaction, event and qualified authority evidence |
| accepted/indeterminate | matching legacy event without current evidence | observed_unqualified | compatibility evidence only; never qualified success |
| succeeded/observed_unqualified | matching redaction | redacted/observed_unqualified | target event plus redaction digest |
| any terminal | exact replay | unchanged | full semantic equality |
| any terminal | contradiction | error | no mutation |

## 4. Monotonicity and uncertainty

- `TransportAccepted` is not terminal success.
- Only a trusted homeserver observation can produce `Confirmed`/`Succeeded`.
- Read timeout, connection reset, decode failure after adapter entry and lost acknowledgement remain `Indeterminate`.
- Unknown effects never receive a new transaction ID and are never converted to failure merely because retries are exhausted.
- A later rejection cannot erase an earlier accepted or unknown effect.
- Terminal states never reopen. Redaction is monotonic and cannot resurrect content.
- Cancellation, expiry and revocation before physical entry produce zero network calls. The same conditions after entry are uncertainty, not remote failure.

## 5. Final-use ordering

The physical path is:

```text
claim fenced outbox
-> recompute canonical final-use request
-> obtain independently signed grant
-> kernel claim burns single-use nonce
-> persist authority witness
-> persist dispatching phase
-> refresh authenticated revocation frontier
-> enter verified use with exact token/binding
-> poll lazy Matrix transport future
```

There is no `await`, persistence operation or mutable policy read between successful `enter_verified_use` and polling the transport future. The physical deadline is strictly shorter than the remaining lease.

## 6. Transaction boundaries

1. Attempt claim identity, active claim and `claimed` event commit together.
2. Authority witness, active-phase change and `authorized` event commit together.
3. Dispatching phase and event commit together before final revocation refresh.
4. Fenced outcome handling updates the outbox claim and append-only attempt history under the exact attempt/lease/token identity.
5. `/sync` reconciliation, terminal ledger mutation, outbox settlement, change record and sync checkpoint commit in one owner transaction.
6. Redaction, dispatch redaction and checkpoint advancement commit in one owner transaction.

The durable dispatch ledger also uses attempt CAS. Random capability fencing protects active attempt transitions; stale workers cannot close, retry or settle a newer claim.

## 7. Crash cuts

| Crash point | Recovery rule |
|---|---|
| before durable claim | queued outbox remains claimable |
| after queue claim, before capability transaction | ordinary lease expires; no network effect |
| after capability claim, before grant | active claim expires; next attempt mints a new token |
| after kernel nonce burn, before witness commit | nonce remains burned; no effect; retry uses a fresh grant |
| after witness, before dispatching | exact claim can only be canceled/revoked/expired or resumed under its lease |
| after dispatching, before transport poll | no effect if process dies before poll; recovery does not fabricate success |
| after adapter entry, before response | indeterminate; retain stable transaction |
| after event ID, before local commit | retry/reconcile same transaction; `/sync` settles terminality |
| after `/sync` mutation, before commit | transaction and cursor roll back; event replays safely |
| after terminal commit | duplicate observations are idempotent |

## 8. Capacity and scheduling

Unresolved dispatch rows are capped at 4,096. Claim batches are bounded to 1-256, attempts to 1-64, network deadlines by lease, and retry delays by policy. Matrix `Retry-After` is normalized, bounded and given deterministic per-transaction jitter. Exhausted unknown effects park for reconciliation rather than spin or become false failures.
