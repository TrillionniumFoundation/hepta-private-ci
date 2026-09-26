# channel.matrix configuration

Configuration is immutable for one `matrixd` process generation. Changes to authority, binding, credentials, homeserver, device/session, schema or resource policy require a new configured generation and supervisor reconciliation.

## 1. Runtime inputs

`MatrixdConfig` supplies:

- Agent ID and attached Agentd spawn generation;
- release ID, process incarnation and plane epoch;
- canonical fleet/workspace/Matrix roots and control sockets;
- public `MatrixBindingV1` with expected Matrix user, allowed rooms and binding revision;
- sync timeline limit and timeout;
- device display name;
- credential handles for Matrix password and encrypted session-store passphrase.

The supervisor derives these values from the active immutable release, current Agent record and public binding. Callers cannot choose another Agent scope at runtime.

## 2. Final-use files

Under the private Matrix secrets root:

### `final-use.json`

```json
{
  "schema_version": 1,
  "signer_id": "registered-owner",
  "verifying_key": [0, 1, 2],
  "broker_socket": "/absolute/private/path/broker.sock",
  "request_timeout_ms": 5000
}
```

The real key array is exactly 32 bytes. The file must be an absolute canonical regular file, owned by the effective user, mode 0600 or stricter, single-linked and within the size limit. The broker socket and parent must be canonical, private and user-owned.

### `final-use-revocations.json`

Contains `FinalUseRevocations { authority_epoch, revision, revoked_grant_ids }`. Updates are monotonic. Rollback, duplicate revision with drift, or epoch regression fails closed. The file is re-read immediately before physical send entry.

### `final-use-authority-state/`

Kernel-owned durable nonce/revocation state. It must live under the private Matrix root and survive `matrixd` restarts. Deleting it is not a retry or recovery mechanism.

## 3. Dispatch defaults

| Setting | Default | Constraint |
|---|---:|---|
| outbox lease | 30 s | > 1 ms |
| initial retry delay | 2 s | > 0 |
| maximum retry delay | 5 min | >= initial |
| maximum attempts | 8 | 1–64 |
| claim batch | 32 | 1–256 |
| idle poll | 100 ms | > 0 and <= 5 s |
| shutdown grace | 5 s | bounded |
| inbox recovery limit | 1,024 | bounded |

A target host may use stricter values. A physical-send timeout must be less than the remaining lease. Rate-limit hints are bounded by host policy and do not authorize unbounded sleeps.

## 4. Secrets

Matrix credentials, session-store passphrase, signing keys and bearer tokens must never be accepted through ordinary command output, logs, receipts, prompts or learning artifacts. Matrixd may hold Matrix client credentials and final-use verifier keys; it must not hold the final-use signing key.

## 5. Validation and reload

Startup validates all paths, ownership, permissions, binding identities, limits and exact Agent generation before network activation. There is no hidden live reload. Public binding or authority revisions are adopted through their explicit monotonic protocols; other changes require controlled daemon replacement.
