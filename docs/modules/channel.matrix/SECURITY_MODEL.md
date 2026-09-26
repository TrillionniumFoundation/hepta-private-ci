# channel.matrix security model

## 1. Assets

Protected assets are Matrix credentials/session keys, enrolled-room membership, message content, stable transaction and event identities, Agent private state, final-use verifier state, signed grants, revocation frontier, random claim capabilities and durable audit records.

## 2. Principals and authority

- The supervisor has lifecycle authority only.
- Agentd owns Agent execution and private state.
- Matrixd translates enrolled Matrix events and performs authorized Matrix effects.
- `MatrixDurableStore` is the sole Matrix state writer.
- The final-use broker is independently operated and owns signing policy/key.
- `FinalUseAuthority` owns verification, nonce burn and revocation checks.
- The homeserver supplies transport plus authenticated persistence/redaction observations; it grants no Agent authority outside enrolled scope.

Matrixd never self-issues a grant, embeds the signing key, writes Agentd state, treats message prose as authority or infers terminal success from local completion.

## 3. Send authorization

A physical send requires exact binding of subject, destination, homeserver, Matrix user, device, session generation, room, binding revision, Matrix-plane generation, stable transaction, attempt and canonical payload digest. The grant is short-lived and single-use.

The owner:

1. claims the outbox with a random opaque capability;
2. obtains and kernel-claims an independently signed grant;
3. persists witness and revocation-head digests under the exact claim;
4. records dispatching;
5. refreshes authenticated revocations;
6. consumes the exact-frontier token immediately before polling the lazy transport future.

The raw 32-byte claim capability is process-private. Only its SHA-256 digest is durable. Every active-claim mutation is fenced by transaction, attempt, lease epoch and capability digest; the ledger additionally enforces monotonic attempt CAS.

## 4. Ingress threats

Controls cover malicious message text, event replay, duplicate sync pages, malformed/oversize JSON, room escape, sender spoofing, stale generation, correction/redaction races and restoration of deleted content. Typed enrolled-room mutations commit with the sync cursor, so a cursor cannot outrun the durable projection.

## 5. Egress threats

Controls cover payload drift, transaction reuse across semantics, revoked grants, stale device/session, ACK loss, retry duplication, later rejection overwriting prior acceptance, stale lease holders, capability replay, second-writer observer state and forged terminal observations.

Mitigations are stable transaction IDs, immutable logical identity, random attempt capabilities, append-only events, exact final-use entry, typed uncertainty and sync-based terminality. `TransportAccepted` is not success; unknown post-entry outcomes are never converted to failure.

## 6. Filesystem and process isolation

Matrix roots, credential/session files and sockets are absolute, canonical, user-owned and private. One per-Agent process lock and supervisor process lease prevent duplicate writers. Session files are bounded, single-link and private where the platform exposes those controls. Cross-Agent databases, credentials and sockets are never shared.

## 7. Data minimization

Logs and receipts retain typed IDs, error classes and digests. They exclude raw claim capabilities, raw grants/tokens, credentials, session keys, access tokens, signing material and message content. Claim, witness, revocation and payload digests are sufficient for audit without turning evidence storage into an authority source.

## 8. Mandatory negative tests

- wrong signer, altered binding, scope or payload digest;
- revoked, stale or expired grant at final entry;
- grant replay and cross-attempt reuse;
- wrong/random claim capability, stale attempt or expired lease;
- room/device/session/generation drift;
- cross-Agent store/socket access;
- unknown fields and oversize frames/payloads;
- pre-entry cancellation/revocation produces zero network calls;
- post-entry timeout/reset/response loss remains indeterminate;
- conflicting event/transaction identities fail closed;
- redacted/revoked content cannot reappear after reconnect or restore.

## 9. Residual gates

Source composition does not establish production authority. Production qualification still requires protected time/frontier behavior, real secret provisioning, target-host process/filesystem isolation, real enrolled homeserver/device identity, encrypted-room rotation, authenticated backup/restore, sustained-rate/capacity evidence and independent security/operator acceptance. Until those receipts pass at the exact candidate, `productionImplementation`, `activation`, `independentAcceptance` and `release` remain false.
