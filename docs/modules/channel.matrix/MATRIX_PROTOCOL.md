# channel.matrix protocol contract

## 1. Authenticated identity

Every active Matrix transport is bound to one homeserver URL, Matrix user ID, device ID, session generation, enrolled room set, room-binding revision and stable Matrix-plane generation. These values participate in the final-use scope digest. A changed room, device, session, binding or generation cannot reuse an old grant, witness or dispatch claim.

## 2. Ingress and terminal observation

Only durable `/sync` data is authoritative for ingress and send terminality. Timeline events, replacements and redactions are typed bounded mutations. Unknown critical fields, malformed identities, oversize payloads, stale generations and sender/scope mismatches fail closed. Message text is untrusted content, never administrative authority.

A matching outbound event must carry the stable transaction identity and be observed from the enrolled Matrix identity in the exact room/binding/generation. HTTP completion, SDK return, App Server completion and user read receipts do not establish `Confirmed`.

## 3. Egress identity

A logical send uses one stable Matrix transaction ID across retry, process restart and reconciliation. The canonical payload digest covers the exact event content, including replacement target where present. Changing content, room, device/session, binding revision, generation or attempt changes the signed final-use request.

The transport future is lazy: constructing it performs no external I/O. It is first polled only after the exact final-use token is revalidated and consumed.

## 4. Transport outcome taxonomy

| Result | Local meaning | Durable action |
|---|---|---|
| valid event ID returned | transport accepted, not terminal | record `accepted`; await matching `/sync` |
| Matrix `M_LIMIT_EXCEEDED` / HTTP 429 | rate limited | normalize `RetryAfter::Delay` or `DateTime`, bound it, add stable jitter |
| HTTP 408 | response timeout | indeterminate under the same transaction |
| HTTP 5xx | server unavailable | typed retry/reconciliation |
| DNS lookup failure | no usable connection | typed bounded retry |
| TLS/certificate/handshake failure | transport establishment failed | typed bounded retry; operator-visible class |
| connect timeout/refusal | connection did not establish | typed bounded retry |
| read timeout/reset/decode/response loss after entry | effect may exist | `indeterminate`; never terminal failure |
| authenticated permanent Matrix rejection with no prior effect evidence | rejected | terminal `failed` |
| later rejection after accepted/unknown effect | cannot erase possible effect | remain accepted/indeterminate and reconcile |

Unparseable server event IDs after SDK completion are response loss, not proof of failure. Exhausted uncertain attempts park for reconciliation instead of changing transaction identity or synthesizing failure.

## 5. Final-use broker

The broker protocol is bounded newline-delimited JSON over a private Unix socket. Request and response use schema version 1. The independently operated broker owns signing policy and key; matrixd holds only verifier material.

The request binds operation ID, stable transaction ID, logical outbox ID, attempt, subject, destination, homeserver, user, device, session generation, room, binding revision, Matrix-plane generation, request digest, scope digest and payload digest.

The physical sequence is:

```text
signed grant
-> kernel claim and nonce burn
-> durable witness
-> durable dispatching phase
-> authenticated revocation refresh
-> exact verified-use entry
-> poll lazy SDK future
```

No await or persistence occurs after verified-use entry and before transport poll.

## 6. Claim and lease protocol

Each physical attempt is fenced by `(stable_txn_id, attempt, lease_epoch, claim_token_sha256)`. The raw random capability remains process-private. Active transitions require the exact live identity, and the physical deadline is strictly shorter than remaining lease time. Clean shutdown releases only claims that have not entered physical I/O.

## 7. Limits

- identities and frames are bounded before allocation-heavy work;
- payloads use the registered Matrix boundary limit;
- sync batches and timeline windows are host-bounded;
- unresolved dispatches are capped at 4,096;
- claim batches are 1-256;
- attempts are 1-64;
- broker frames are at most 128 KiB;
- broker timeout is 100-10,000 ms;
- retry hints exceeding policy park for operator reconciliation rather than create an unbounded timer.
