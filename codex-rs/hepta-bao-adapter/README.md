# Authorized HeptaBao HTTPS consumer

The legacy `resolve` and `assess_secret_boundary_v1` remain metadata-only;
`PROVIDER_DISPATCH_ENABLED` remains false for that API. A caller-provided
`Granted` observation cannot enable this separate client.

`BaoClient::consume_kv_v2` is the exact-version KV v2 integration point. Provider-native dynamic credentials use the separate `request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease` and `reconcile_secret_lease` lifecycle in `src/lease_lifecycle.rs`. The KV path reads
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

## Provider-native dynamic SecretLease lifecycle

Dynamic issuance accepts one bounded provider path, GET or POST, an optional
bounded string request map and an explicit bounded list of string response
fields for the registered final consumer. The grant binds the exact origin,
pinned CA, namespace, path, logical lease key, complete request and selected
fields; it does not pretend to bind credential bytes that do not exist until
the provider creates them.

The durable lifecycle is owned by `SecretLeaseRecord` and `SecretLeaseStore`.
The current `HeptaEvidenceStore` implementation uses SQLite migration 0011
and revision compare-and-swap. Issuance creates `Requesting` before dispatch
and only the caller that wins the durable insert is allowed to contact the
provider. Renewal and revocation write `Renewing` or `RevokePending` before
their provider call.

Successful dynamic issuance persists `Active` metadata before selected secret
strings enter the synchronous trusted `BaoSecretFields` callback. Raw values
are not stored in the lease registry and the dynamic path deliberately does
not retain a per-value SHA-256 fingerprint.

There is no automatic provider mutation retry. Transport loss, timeout,
provider 5xx or an unusable successful response moves the durable operation
toward `Unknown` when that transition can be recorded. Known provider lease
IDs can be reconciled through `/v1/sys/leases/lookup`. Generic issuance whose
response was lost before a lease ID was observed returns
`ReconciliationRequired`; it is never reissued blindly.

Renewal uses `/v1/sys/leases/renew` and treats the provider-returned TTL and
renewable value as authoritative. Revocation uses
`/v1/sys/leases/revoke` with `sync=true`. A provider lease ID, once observed,
is immutable in the local lifecycle record.

The checked-in SQLite owner coordinates multiple handles/processes sharing one
database but is not a multi-host consensus backend. See
`docs/modules/secrets.heptabao/{CURRENT_IMPLEMENTATION,SECRET_LEASE_DESIGN,FAILURE_RECOVERY,HA_AND_STORAGE,SECURITY_INVARIANTS}.md`.

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
files (0600), and holds an operating-system process lock until exit. Revocation-head updates are synced and atomically replaced before success;
nonce claims are appended as fixed-width durable records before success.
The example automatically reopens this state: used nonces remain rejected
after restart without a manual epoch change. Corrupt, missing previously
initialized state, unsafe permissions, or a concurrent owner cause denial.
Storage errors fence that authority instance until recovery. Preserve this
state across deployments; deleting or restoring it from an old backup is an
authority reset and requires an independently changed issuer trust/epoch.
Other platforms fail closed until an equivalent owner ACL store exists.
Schema 2 stores the bounded revocation head separately from an append-only
`authority.claims` nonce journal. Claims no longer rewrite the complete JSON
state and there is no former 16,384-claim logical ceiling. Revoked grant IDs
remain separately bounded, and long epochs still consume memory/disk. A
failed/timeout request does not refund its nonce or retry automatically. A new
grant requires owner action.

Provider 401/403 is denied; missing data, invalid TLS, timeout, oversize,
malformed response, wrong version and digest mismatch never invoke the
consumer. If the consumer reports failure after entry, the outcome is
`ConsumerIndeterminate`; do not infer no effect or blindly repeat it.
Dynamic lease mutation APIs use their own durable CAS lifecycle and explicit
uncertainty/reconciliation semantics; they do not reuse read retry rules.

## Verification

Targeted tests cover a real loopback TLS exchange, exact request headers and
version, forged signature rejection, nonce replay rejection, provider denial,
revocation during a network wait, incorrect trust root and response bounds.
Dynamic lifecycle tests cover the one-durable-insert issuance winner and
ambiguous lost-response quarantine. Kernel tests cover signed-field changes,
wrong issuer, expiry, epoch fences and schema-1 replay-state migration; evidence
store tests cover exact-idempotent lease creation and revision CAS. Run
`cargo test --locked -p codex-hepta-contracts -p codex-hepta-bao-adapter -p codex-hepta-evidence`
and the repository formatting/lint gates before merging.

For the separate real service check, build this crate's `consume_secret`
example and the supervisor's `hepta-final-use-signer` binary with
`--features production-authority`, then run:

```text
python codex-rs/hepta-bao-adapter/qa/real_service_smoke.py \
  --service-checkout /absolute/HeptaBao \
  --server /absolute/heptabao-server \
  --consumer /absolute/consume_secret \
  --signer /absolute/hepta-final-use-signer \
  --work-dir /absolute/new-private-test-directory
```

This fixture requires Python `cryptography`, `openssl`, and the reviewed Bao
checkout's `qa/single-node/smoke.py`. It initializes a new isolated service
with synthetic credentials, signs grants in the separate process, verifies
consumer receipts, rejects replay across consumer process restarts, rejects
forged signatures and denied provider tokens, and reads again after killing
and unsealing the real service. It leaves only synthetic owner-protected test
state and writes `result.json` containing scenario names and digest metadata.
It never connects to an existing production service.

## Recorded candidate verification

[Validation status](qa/evidence/validation-20260908.json) separates the initial
20 real service checks, 28 source-linked behavioral cases, and source-linked
all-target Clippy from the normal workspace gates. Clippy reported one existing
`provider_effect.rs` warning under Rust 1.98; no new-source warnings remained.
The global/module/readiness document verifiers passed.

The initial normal locked three-package `just test` reached contracts compilation after
363 compilation log entries, then was interrupted because the shared disk
remained full. It executed zero tests and is recorded as `blocked_space`, with
no compiler error observed. The normal workspace signer build was not started;
the independently built signer had already passed the real process fixture.
Cargo metadata updated only 17 dependency edges without changing package
versions, sources or checksums.

After the approved HTTP client migration, the normal locked workspace run
executed 243 tests: 237 passed and six existing shared-client TLS
classification/fallback tests failed. All 132 contracts tests, 18 adapter
tests, the new isolated transport test, and ten CA subprocess tests passed.
An independent checkout of the prior source `91bcc46` reproduced all six
failures both with inherited environment and with only the application CA
environment variables removed. Their cause remains unresolved; this is not
an all-pass workspace gate and the CA hypothesis was not established.

The new consumer then built successfully in the normal workspace and passed
[all 20 real service checks again](qa/evidence/real-consumer-http-client-20260908.json).
Its binary digest begins `f160211f`; the receipt records the full digest,
tested source tree `4f1a0be353ddcb5617de193487f11c72de9c9206`, and unchanged
issuer and Bao binary identities. That tree precedes final formatting and
evidence edits; the binary is not claimed to come from the final commit.
Normal Cargo metadata changed three added and one removed dependency edges,
with no dependency version/source/checksum changes. The resolved graph has
zero disallowed first-party `reqwest` owners under the existing deny rules;
the full `cargo-deny` command and current-head CI remain separate gates.
The required scoped `just fix` completed without warnings. Its only manual
lint correction was a test-only type alias; final formatting and documentation
did not change the recorded production source hashes. Tests were not rerun
after lint/format cleanup.

The local Bazel lock update was blocked. Automatic approval review rejected
an attempted telemetry request with an unauthorized unknown metadata payload.
The safer retry disabled that telemetry through documented environment inputs,
then encountered LLVM archive ownership extraction errors and a cancelled
network approval. `MODULE.bazel.lock` was not fabricated or marked synchronized.
Separately, the downloaded diagnostics for
[GitHub workflow run 34169739488](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/34169739488)
verified that the old source `20ede7c31dfc162bf231d50c875416f3d83714dc` passed
the real Bazel check/update/check commands, including
`mod deps --lockfile_mode=error`; all three commands exited zero and generated
no lock change. That old-source result does not validate the subsequent HTTP
client dependency migration, which requires its own current-head CI check.
The full formatter was also blocked at the Bazel/Starlark step because
`dotslash` was unavailable; Rust and Python formatting completed. These open
workspace gates remain separate from the bounded integration results.
