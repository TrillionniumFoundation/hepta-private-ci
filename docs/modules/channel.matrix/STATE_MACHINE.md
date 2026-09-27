# channel.matrix durable state machine

The authoritative send truth is owned by `MatrixDurableStore`. The SDK sender, compatibility observer and runtime never own a second ledger. `send_observer.rs` is read-only projection over durable dispatch state.

## 1. Conceptual and native phases

```text
Prepared
  -> Claimed(attempt, lease_epoch, opaque_claim_token)
  -> Authorized(verified-use witness, revocation head)
  -> Dispatching(final revocation refresh)
  -> EnteredUse(non-constructible durable proof, sealed SDK permit)
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
| `matrix_dispatch_content_bindings` | canonical Matrix content and scope pin |
| `matrix_dispatch_use_entries` | exact non-constructible entered-use proof |
| `matrix_dispatch_legacy_content_holds` | sealed inherited unknown-effect identity |
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
- terminality belongs to the stable transaction: any exact matching entered-use proof from an attempt not newer than the observed dispatch attempt can qualify the server echo;
- the append-only terminal attempt event is attributed to the newest qualifying entered-use attempt, never to a later claim that did not cross the final-use boundary;
- each attempt has one immutable random claim capability and at most one immutable authority witness;
- grant ID, request/scope/payload digests, authority epoch, revocation frontier and absolute expiry are bound to the exact attempt;
- exact duplicate observations are idempotent; semantic drift is a conflict.

## 3. Allowed transitions

| Current | Trigger | Next | Required durable evidence |
|---|---|---|---|
| absent | outbox admission | prepared logical identity | stable transaction and canonical payload |
| queued | bounded claim | claimed | new attempt/lease, random capability digest, `claimed` event |
| claimed | durable final-use verification | authorized | witness digest, revocation-head digest, grant identity, `authorized` event |
| authorized | durable intent before final entry | dispatching | exact live token/lease, `dispatching` event |
| dispatching | final revocation/expiry check and token entry | entered-use proof | immutable proof bound to claim, authority, scope and canonical content |
| entered-use proof | sealed SDK permit polls transport | accepted/indeterminate/failed | typed physical-boundary observation; event ID is not terminal success |
| dispatching | timeout/reset/unknown response | indeterminate | typed failure class and optional retry hint |
| dispatching | proven pre-effect permanent rejection | failed | no earlier accepted evidence and `permanently_rejected` event |
| accepted/indeterminate | matching authenticated `/sync` event | succeeded | exact room, transaction and event plus any matching entered-use proof from `attempt <= current attempts`; the terminal attempt event records the newest qualifying entered attempt and all residual active claim state closes atomically |
| accepted/indeterminate | matching legacy event without current evidence | observed_unqualified | compatibility evidence only; never qualified success |
| succeeded/observed_unqualified | matching redaction | redacted/observed_unqualified | target event plus redaction digest; qualified redaction uses the same entered-attempt attribution rule |
| any terminal | exact replay | unchanged | full semantic equality |
| any terminal | contradiction | error | no mutation |

## 4. Monotonicity and uncertainty

- `TransportAccepted` is not terminal success.
- Only a trusted homeserver observation can produce `Confirmed`/`Succeeded`.
- Read timeout, connection reset, decode failure after adapter entry and lost acknowledgement remain `Indeterminate`.
- Unknown effects never receive a new transaction ID and are never converted to failure merely because retries are exhausted.
- A later rejection cannot erase an earlier accepted or unknown effect.
- Terminal states never reopen. Redaction is monotonic and cannot resurrect content.
- Cancellation, expiry and revocation before kernel final-use entry produce zero network calls and may release the exact live claim.
- Kernel final-use entry is itself monotone: after it succeeds, proof-persistence acknowledgement loss, absolute grant expiry, revocation/frontier change, transport identity drift, canonical payload drift, permit-construction failure, cancellation or lease expiry must carry the entered proof forward and preserve the same transaction as `Indeterminate`; none may be rewritten as a pre-entry cancel/revoke.

## 5. Final-use ordering

The physical path is:

```text
claim fenced outbox
-> recompute canonical final-use request
-> obtain independently signed grant
-> kernel claim burns single-use nonce
-> persist authority witness and absolute grant expiry
-> persist dispatching phase
-> refresh authenticated revocation frontier and check grant expiry
-> enter verified use with exact token/binding
-> persist the non-constructible entered-use proof under the live claim
-> recheck absolute grant expiry, revocation frontier, transport identity and canonical payload
-> construct the opaque MatrixSendPermit
-> repeat the same checks on every lazy Matrix transport poll
```

Entered-use proof persistence occurs before the transport future exists and therefore before any network effect. After the future is created, no unrelated persistence await precedes its first poll. The physical deadline is strictly shorter than the remaining lease. Because the proof write can commit while its acknowledgement is lost, any fault after kernel entry is conservatively reconciled as an entered unknown effect even when the adapter was not demonstrably polled.

## 6. Transaction boundaries

1. Attempt claim identity, active claim and `claimed` event commit together.
2. Authority witness, active-phase change and `authorized` event commit together.
3. Dispatching phase and event commit together before final revocation refresh.
4. Entered-use proof commits under the exact claim/content/authority tuple before permit construction.
5. Fenced outcome handling updates the outbox claim and append-only attempt history under the exact attempt/lease/token identity.
6. `/sync` reconciliation qualifies the stable transaction against every entered attempt up to the current attempt, attributes the terminal attempt event to the newest qualifying entered attempt, and commits terminal ledger mutation, removal of residual active claim state, outbox settlement, change record and sync checkpoint in one owner transaction.
7. Redaction, dispatch redaction and checkpoint advancement commit in one owner transaction under the same entered-attempt attribution rule.

The durable dispatch ledger also uses attempt CAS. Random capability fencing protects active attempt transitions; stale workers cannot close, retry or settle a newer claim.

## 7. Crash cuts

| Crash point | Recovery rule |
|---|---|
| before durable claim | queued outbox remains claimable |
| after queue claim, before capability transaction | ordinary lease expires; no network effect |
| after capability claim, before grant | active claim expires; next attempt mints a new token |
| after kernel nonce burn, before witness commit | nonce remains burned; no effect; retry uses a fresh grant |
| after witness, before dispatching | exact claim can only be canceled/revoked/expired or resumed under its lease |
| after token entry, before proof commit or proof acknowledgement | token remains consumed; the write outcome may be unknown, so the attempt cannot be downgraded to pre-entry release and retains the stable transaction for recovery/reconciliation |
| after proof commit, before transport poll | entered intent remains durable; no success is fabricated and reconciliation keeps the transaction unresolved |
| after adapter entry, before response | indeterminate; retain stable transaction |
| after a later retry claim but before its adapter entry | a delayed matching server echo is qualified by the earlier entered-use proof, records terminal history against that entered attempt, and atomically closes the newer claim without another send |
| after event ID, before local commit | retry/reconcile same transaction; `/sync` settles terminality |
| after `/sync` mutation, before commit | transaction and cursor roll back; event replays safely |
| after terminal commit | duplicate observations are idempotent |

## 8. Capacity and scheduling

Unresolved dispatch rows are capped at 4,096. Claim batches are bounded to 1-256, attempts to 1-64, network deadlines by lease, and retry delays by policy. Matrix `Retry-After` is normalized, bounded and given deterministic per-transaction jitter. Exhausted unknown effects park for reconciliation rather than spin or become false failures. Sealed legacy holds are materialized as accepted/indeterminate, stale claims are closed, and active queue rows are permanently parked until authenticated sync settles the original transaction.
