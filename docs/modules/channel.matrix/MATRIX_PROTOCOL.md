# channel.matrix protocol contract

## 1. Authenticated identity

Every active transport is bound to one homeserver URL, Matrix user ID, device ID, session generation, enrolled room set, room-binding revision and stable Matrix-plane generation. These values participate in the final-use scope digest. A changed device/session/binding cannot reuse an old grant or dispatch claim.

## 2. Ingress

Only durable `/sync` data is authoritative for ingress and send terminality. Timeline events, replacements and redactions are typed mutations. Unknown critical fields, malformed identities, oversize payloads, stale binding generations and sender/scope mismatches fail closed. Message text is untrusted content, never administrative authority.

## 3. Egress

A logical send uses one stable Matrix transaction ID across retries. The canonical payload digest covers the exact bytes passed to the SDK adapter; changing content, room, device/session, binding revision, generation or attempt changes the signed final-use request.

The transport return is classified separately from terminal observation:

| Result | Local meaning | Durable action |
|---|---|---|
| event ID returned | transport accepted | record `accepted`; await matching `/sync` |
| HTTP 429 | rate limited | honor bounded `retry_after_ms`, add jitter, retain transaction |
| 5xx / unavailable | retryable or unknown | append classification and retry/reconcile |
| DNS/TLS/connect failure before request bytes | safe-before-entry only when adapter proves it | bounded retry |
| read timeout/reset/response loss | effect may exist | `indeterminate`; never terminal failure |
| authenticated Matrix permanent rejection before any prior acceptance | rejected | terminal `failed` |
| later rejection after prior acceptance | cannot erase effect | remain `accepted`/reconciliation |

Transport implementations must be lazy: constructing the future performs no network I/O. The future is polled only after the exact final-use entry succeeds.

## 4. Final-use broker

The broker protocol is bounded newline-delimited JSON over a private Unix socket. Request and response use schema version 1. The broker validates the complete `MatrixFinalUseRequest` before signing. Matrixd holds only verifier keys; it never holds the signing key.

The request binds operation ID, stable transaction ID, logical outbox ID, attempt, subject, destination, homeserver, user, device, session generation, room, binding revision, Matrix-plane generation, request digest, scope digest and payload digest.

## 5. Trusted terminal observation

A matching `/sync` event must contain the stable transaction identity and come from the enrolled Matrix identity in the exact room/binding/generation. HTTP completion, SDK return, App Server completion and user read receipts do not substitute for homeserver persistence. Redaction targets the confirmed event and is a separate monotonic observation.

## 6. Limits

- identities are bounded and validated before allocation-heavy work;
- payloads use the registered Matrix boundary limit;
- sync batches and timeline windows are bounded by host configuration;
- unresolved dispatches are capped at 4,096;
- claim batches are 1–256;
- retry count is 1–64;
- broker frames are at most 128 KiB;
- broker timeout is 100–10,000 ms;
- physical send deadline must be strictly shorter than the outbox lease.
