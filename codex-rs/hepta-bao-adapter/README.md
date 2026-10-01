# Durable Bao runtime and credential consumer

The SQLite runtime owns each original operation and never re-enters the provider
or consumer during reconciliation. Quota admission, final-use authority and
independent approval remain required. The JSON owner supports reference tests
and migration; production SQLite uses the shared durable connection policy.

## Independent credential consumer on Linux

`hepta-secrets-runtime serve-consumer /etc/hepta-secrets-private-ci/consumer.json`
starts the concrete credential-consumer service. The configuration must be a
root-owned regular file in root-owned directories, with no group or other write
permission and no other read permission. Unknown JSON fields are rejected.

The installed roles for the local product qualification are:

| Role | UID / GID | Private state | Socket / public pin |
| --- | --- | --- | --- |
| OpenBao provider | 993 / 977 | `/var/lib/hepta-bao-provider` | pinned TLS at `127.0.0.1:18200` |
| Secrets runtime | 992 / 976 | `/var/lib/hepta-secrets-runtime` | consumer UID and ACK public key in root policy |
| Credential consumer | 983 / 972 | `/var/lib/hepta-secrets-consumer/private` | `/run/hepta-secrets-consumer/consumer.sock` |

The consumer's credential and 32-byte Ed25519 seed are separate regular files,
owned by UID 983, with mode `0600`, a single link and no symlink. The private
directory uses `0700`. Neither file is shared with the runtime. The runtime
receives only the independently installed consumer public key and the frozen
credential reference digest.

For socket access, run the consumer with primary process group 976. Its socket
directory must be owned by UID 983 / GID 976 with mode `0750`; the service creates
the socket with mode `0660`. The Linux kernel peer UID must equal the configured
runtime UID 992. Workload requests cannot select another consumer or peer.

The root configuration has these concrete fields:

```json
{
  "schema_version": 1,
  "consumer_id": "hepta.private-ci.credential-health",
  "socket_path": "/run/hepta-secrets-consumer/consumer.sock",
  "ipc_group_gid": 976,
  "allowed_caller_uid": 992,
  "database_path": "/var/lib/hepta-secrets-consumer/owner/consumer.sqlite",
  "credential_file": "/var/lib/hepta-secrets-consumer/private/credential",
  "credential_sha256": "replace with the 32-byte JSON integer array for the frozen KV version",
  "acknowledgement_signing_key_file": "/var/lib/hepta-secrets-consumer/private/ack-signing-key",
  "acknowledgement_verifying_key": "replace with the independently generated 32-byte JSON integer array",
  "request_timeout_ms": 2000,
  "shutdown_drain_ms": 5000
}
```

The two explanatory strings must be replaced with actual byte arrays before
loading. Private key material is never part of this configuration.

```ini
[Service]
User=hepta-secrets-consumer
Group=hepta-secrets-runtime
UMask=0077
RuntimeDirectory=hepta-secrets-consumer
RuntimeDirectoryMode=0750
ExecStart=/opt/hepta-secrets/current/hepta-secrets-runtime serve-consumer /etc/hepta-secrets-private-ci/consumer.json
TimeoutStopSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/hepta-secrets-consumer /run/hepta-secrets-consumer
```

The consumer authenticates an operation-bound HMAC using its actual credential,
then commits an immutable original-operation ACK under SQLite FULL durability.
Only after that commit does it send its independently signed ACK. Requests carry
the HMAC proof rather than secret bytes. The runtime verifies that signature,
the original operation and semantic digest, and the pinned peer UID.

The prepared runtime callback connects and checks the peer before final-use
entry. Its first nonblocking write crosses the effect boundary synchronously;
it never waits or retries that initial write. The remaining write, framed read
and ACK verification share the original deadline. A lost reply remains Unknown;
Status reads the same original signed ACK and cannot authenticate again. Missing
Status never proves absence of an effect or permits quota release.

SIGTERM stops admission immediately. Existing requests share a bounded physical
join and pool close. A timed-out transaction fences new authentication while
original Status remains available. The admission guard only bounds in-flight
ports; durable operation identity remains owned by the SQLite runtime.

## Qualification boundary

Native tests exercise an independent consumer process, real credential
authentication, signature rejection, private file and kernel-peer boundaries,
cross-restart original ACKs, cancellation and physical shutdown. Another native
test joins the provider TLS fixture, AuthBus, production SQLite runtime and this
independent consumer, then queries the original terminal result after both
external processes have stopped. A TLS fixture does not establish installed
OpenBao daemon qualification.

The consumer component is a production entry point. Installed runtime ingress,
independent authority/evidence producers and their protected clock/frontier must
be qualified together before activating provider operations. Dynamic issue,
renew, revoke and the remaining provider capabilities stay closed until their
individual production consumers and restart behavior are implemented and
qualified. No configuration-only deadline DTO represents implemented execution.

## Existing bounded integration APIs

The legacy `resolve` and `assess_secret_boundary_v1` remain metadata-only;
`PROVIDER_DISPATCH_ENABLED` remains false for that API. A caller-provided
`Granted` observation cannot enable this separate client.

`BaoClient::consume_kv_v2` is the executable host integration point. It reads
`GET /v1/{mount}/data/{path}?version=N`, supplies `X-Vault-Token` and
`X-Vault-Namespace`, requires a configured CA and hostname-valid HTTPS, disables
redirects and ambient proxies, and caps the complete response at 1 MiB.
An empty namespace denotes root and omits the namespace header.
The supported consumer contract is one string field from one exact KV v2
version. Other field types and other secrets engines are not silently coerced.

The adapter uses the approved `codex-http-client` owner through
`HttpClientBuilder::build_pinned_https_direct`; it has no direct `reqwest`
dependency. This narrow host-enrolled transport trusts only the supplied CA,
ignores ambient CA files and system roots, disables proxies, redirects and
protocol retries, and applies one deadline through response-body reads. It
also disables request diagnostics and ambient OTel trace/baggage injection,
so a global propagator cannot replace the explicitly bound provider headers.
Construction and transport errors become fixed adapter error categories;
error responses are never read into diagnostics. The shared client's normal
proxy, tracing and trust behavior remains unchanged for other callers.

Before dispatch, `kernel.authority` (`hepta-contracts::FinalUseAuthority`)
verifies an independent Ed25519 signature and claims a single-use nonce. The
grant binds the subject, HTTPS origin, CA, namespace, mount, path, field,
version, expected secret digest and consumer identity. The adapter owns no
signing key. The host pins the public key, epoch and revocation head; request
JSON must never supply or replace these trust inputs.

After the network response and digest/version validation, the kernel checks
current time, epoch and revocation again. The synchronous consumer executes
under that revocation lock. It must be bounded, must not reenter the authority,
and must not copy secret bytes into model context, logs or receipts. Response
buffers and decoded secret strings are zeroized on drop; TLS/HTTP libraries
may retain internal copies, so this is not a locked-memory guarantee.

Secret/value SHA-256 fields are sensitive metadata, not public identifiers. For
low-entropy secret material they can enable offline guessing, so hosts must use
bounded retention, exclude them from general telemetry/exports and avoid
cross-context reuse as stable fingerprints. A future audit profile may replace
raw value digests with a keyed digest when cross-system equality is unnecessary.

## Host integration

```rust,ignore
let binding = client.binding(&request)?; // metadata for the external issuer
// The host obtains a SignedFinalUseGrant for this exact binding.
let receipt = client.consume_kv_v2(&authority, &grant, &request, |secret| {
    registered_consumer.use_credential(secret)
}).await?;
// Publish only receipt: request/body/secret digests, version and byte count.
```

The example `cargo run -p codex-hepta-bao-adapter --example consume_secret --
binding HOST_CONFIG.json` prints the exact binding without a request. With
`consume HOST_CONFIG.json`, it reads the provider token from stdin and runs a
local consumer, printing only the metadata receipt. This is an executable
integration example, not an automatically enrolled global provider. A host
must connect its actual registered consumer at the shown function call.
The callback and authority configuration are trusted host inputs; the signed
consumer ID does not authenticate an arbitrary plugin-supplied closure. Keep
this API behind the host composition boundary and choose that callback from
the host registry.

The config contains `endpoint`, `ca_pem_file`, `signer_id`, `verifying_key`
(32-byte array), `authority_state_dir`, `authority_epoch`, `revocation_revision`,
`revoked_grant_ids`, `request`, and nullable `grant`. `request` contains
`subject_id`, `consumer_id`, `namespace`, `mount`, `path`, `field`, `version`,
and `expected_secret_sha256` (32-byte array). Public trust configuration must
be delivered through the host's protected configuration channel.

## Independent issuer and revocation

The separate `hepta-final-use-signer` binary in `hepta-supervisor` is enabled
only by the existing `production-authority` build feature. Explicit command:

```text
hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE < grant-proposal.json
```

The key is exactly 32 raw seed bytes in a Unix regular, non-linked, owner-only
file; symlink opens and group/world permissions are rejected. This command
signs the complete proposal from stdin, never creates a permissive grant from
a boolean. The proposal supplies `schema_version: 1`, `signer_id`,
`authority_epoch`, `grant_id`, a fresh nonzero 32-byte `nonce`, the complete
`binding`, `not_before_unix_ms`, and `expires_at_unix_ms`. Maximum lifetime is
five minutes. Signing material remains outside the adapter and normal runtime.

`FinalUseAuthority::update_revocations` accepts only monotonic trusted host
updates. Within one epoch, revoked IDs cannot be removed. `open_state_dir`
requires a Unix owner-only state directory (0700), creates private regular
files (0600), and holds an operating-system process lock until exit. Claims are appended to a fixed-width fsynced replay journal; revocation updates use an atomic snapshot replacement before success.
The example automatically reopens this state: used nonces remain rejected
after restart without a manual epoch change. Corrupt, missing previously
initialized state, unsafe permissions, or a concurrent owner cause denial.
Storage errors fence that authority instance until recovery. Preserve this
state across deployments; deleting or restoring it from an old backup is an
authority reset and requires an independently changed issuer trust/epoch.
Other platforms fail closed until an equivalent owner ACL store exists.
The replay journal never evicts claims silently. Claims are bounded independently at 1,048,576 per authority epoch; revoked grant IDs retain the separate 16,384-entry bound. Exhaustion rejects new dispatch until a trusted epoch transition. A failed/timeout request does not
refund its nonce or retry automatically. A new grant requires owner action.

Provider 401/403 is denied; missing data, invalid TLS, timeout, oversize,
malformed response, wrong version and digest mismatch never invoke the
consumer. If the consumer reports failure after entry, the outcome is
`ConsumerIndeterminate`; do not infer no effect or blindly repeat it.
`lease_lifecycle.rs` now provides a durable metadata-only lifecycle owner for issue/renew/revoke intents and observations. It enforces operation-id idempotency, semantic-conflict rejection, explicit Unknown states, restart recovery and provider-observation reconciliation. It deliberately does not dispatch provider mutation APIs: the OpenBao compatibility registry still marks dynamic lease issuance/renew/revoke as a blocking partial surface, so provider-native mutation remains fail-closed until that endpoint contract is qualified.
