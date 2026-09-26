# channel.matrix security model

## 1. Assets

Protected assets are Matrix credentials/session keys, room membership, message content, stable transaction and event identities, Agent private state, final-use verifier state, signed grants, revocation frontier and durable audit records.

## 2. Principals and authority

- The supervisor has lifecycle authority only.
- Agentd owns Agent execution and private state.
- Matrixd translates enrolled Matrix events and executes authorized Matrix sends.
- `MatrixDurableStore` is the sole Matrix state writer.
- The final-use broker is independently operated and owns signing policy/key.
- `FinalUseAuthority` owns verification, nonce burn and revocation checks.
- The homeserver supplies transport and trusted persistence/redaction observations; it does not grant Agent authority beyond enrolled scope.

Matrixd must never self-issue a grant, embed the signing key, write Agentd state, treat message prose as authority or infer external success from local handler completion.

## 3. Send authorization

A physical send requires exact binding of subject, destination, homeserver, Matrix user, device, session generation, room, binding revision, Matrix-plane generation, stable transaction, attempt and canonical payload digest. The signed grant is short-lived and single-use. The immutable Matrix claim is persisted, the authenticated revocation feed is refreshed, and the exact-frontier token is consumed immediately before the lazy transport future is polled.

A witness/claim is audit evidence, not reusable authority. Any drift or stale frontier fails before network I/O.

## 4. Ingress threats

Controls cover malicious message text, event replay, duplicate sync pages, malformed/oversize JSON, room escape, sender spoofing, stale generation, correction/redaction races and restoration of deleted content. The adapter accepts only typed bounded events from enrolled rooms and commits mutations with the sync cursor.

## 5. Egress threats

Controls cover payload drift, transaction reuse across semantics, revoked grants, stale device/session, ACK loss, retry duplication, later rejection overwriting prior acceptance, second-writer observer state and forged terminal observations. Stable transaction IDs, immutable identities, append-only observations, exact attempt fencing and sync-based terminality address these threats.

## 6. Filesystem and process isolation

Matrix roots/secrets/sockets are absolute, canonical, user-owned and private. Files are opened without symlink following where applicable. One per-Agent process lock and supervisor lease prevent duplicate writers. Cross-Agent databases, credentials and sockets are never shared.

## 7. Data minimization

Logs and receipts use typed IDs, classifications and digests. Raw message content, credentials, session keys, access tokens, private signing material and full grants are excluded. Message content may remain in the owner store only under the Agent retention policy; it must not leak to learning or general telemetry.

## 8. Mandatory negative tests

- wrong signer, altered binding or payload digest;
- revoked/stale/expired grant at final entry;
- grant replay and cross-attempt reuse;
- room/device/session/generation drift;
- cross-Agent store/socket access;
- unknown critical fields and oversize frames/payloads;
- pre-entry cancellation produces zero network calls;
- post-entry loss remains indeterminate;
- conflicting event/transaction identities fail closed;
- redacted/revoked content cannot reappear after reconnect or restore.

## 9. Residual limits

The local compatibility authority constructor uses process time and no external rollback oracle; it is not a production trust composition. Production qualification requires protected time/frontier behavior, real secret provisioning, target-host isolation and independent security acceptance.
