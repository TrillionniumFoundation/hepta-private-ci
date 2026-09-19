# Authorized HeptaBao HTTPS consumer

The legacy `resolve` and `assess_secret_boundary_v1` remain metadata-only;
`PROVIDER_DISPATCH_ENABLED` remains false for that API. A caller-provided
`Granted` observation cannot enable this separate client.

`BaoClient::consume_kv_v2` is the exact-version static integration point. The same enrolled client also implements the bounded dynamic SecretLease profile through `request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease`, `lookup_secret_lease` and `reconcile_lease_operation`. It reads
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
current time, epoch and revocation again. Final secret delivery resolves the
signed `consumer_id` through a host-built `TrustedConsumerRegistry`; request
data cannot supply an executable closure. The synchronous registered consumer
executes under the in-process and cross-process revocation fence. It must be
bounded and must not reenter the authority. Response buffers, decoded strings
and dynamic secret payloads are zeroized on drop; TLS/HTTP/allocator/kernel
internals may retain temporary copies, so this is not a complete-RAM-secrecy or
locked-memory guarantee. Stable secret/body SHA-256 values are omitted from
serialized/debug receipts to avoid turning low-entropy secrets into long-lived
fingerprints.

## Host integration

```rust,ignore
let consumers = TrustedConsumerRegistry::new(host_registered_consumers)?;
let client = BaoClient::new_with_consumers(endpoint, ca, token, timeout, consumers)?;
let binding = client.binding(&request)?; // metadata for the independent issuer
// The host obtains a SignedFinalUseGrant for this exact binding.
let receipt = client.consume_kv_v2(&authority, &grant, &request).await?;
// Serialized receipts contain request identity/version/byte-count metadata;
// provider-body and secret-value fingerprints are intentionally omitted.
```

The example `cargo run -p codex-hepta-bao-adapter --example consume_secret --
binding HOST_CONFIG.json` prints the exact binding without a request. With
`consume HOST_CONFIG.json`, it reads the provider token from stdin and runs a
local consumer, printing only the metadata receipt. This is an executable
integration example, not an automatically enrolled global provider. A host must construct the actual `TrustedConsumerRegistry` at composition
time. The registry and authority configuration are trusted host inputs; the
signed consumer ID selects a registry entry but does not authenticate arbitrary
plugin-supplied code.

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
updates. Within one epoch, revoked IDs cannot be removed. The authority store
uses an owner-only schema-v2 head snapshot plus an append-only checksummed
`claims.log`. A claim appends and syncs one fixed-size record; it does not
rewrite the entire nonce set and no longer has the former 16,384-claim
per-epoch admission ceiling. Multiple active processes may open one qualified
POSIX state directory. Claim, revocation mutation and final synchronous secret
delivery serialize through a short cross-process OS lock and each owner
incrementally refreshes journal records appended by peers.

This is local shared-state concurrency, not distributed consensus. Independent
node-local copies, object storage and unqualified NFS are not one replay domain.
Multi-host active-active requires a separately qualified strongly consistent
state backend or filesystem semantics.

### Dynamic SecretLease lifecycle

`BaoLeaseRegistry` is a private metadata-only registry. It records operation
digest/state and provider lease identity/TTL/renewability/generation; it never
stores provider tokens, raw dynamic secret bytes or secret fingerprints.

Every issue/renew/revoke operation is durably prepared before authority
admission and durably marked `Dispatched` before network I/O. Confirmed
provider results transition to `Succeeded` or `Rejected`. Timeout, transport
loss, 5xx/unexpected status, malformed/oversized success responses and crashes
after `Dispatched` are `Indeterminate`. The same operation ID cannot dispatch
again while indeterminate.

Known lease IDs can be inspected through `lookup_secret_lease`. A lost issuance
response may also lose the newly created lease ID, so V1 deliberately has no
automatic "retry issuance" fallback. External provider/audit reconciliation
must establish whether the effect occurred and submit a separately signed
`BaoLeaseReconciliationObservation`. Only a signed `NotApplied` observation
returns that operation to `Prepared`, after which a fresh grant is still
required.

The V1 dynamic issue profile is intentionally GET-only and accepts a map of
string secret fields. Engines needing POST issue bodies, nested secret values
or different semantics require another versioned typed profile.

See the module's
[CURRENT_IMPLEMENTATION.md](../../docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md),
[SECRET_LEASE_DESIGN.md](../../docs/modules/secrets.heptabao/SECRET_LEASE_DESIGN.md),
[FAILURE_RECOVERY.md](../../docs/modules/secrets.heptabao/FAILURE_RECOVERY.md)
and [HA_AND_STORAGE.md](../../docs/modules/secrets.heptabao/HA_AND_STORAGE.md).

## Verification

Targeted tests cover a real loopback TLS exchange, exact request headers and
version, forged signature rejection, nonce replay rejection, provider denial,
revocation during a network wait, incorrect trust root and response bounds.
Kernel tests cover signed-field changes, wrong issuer, expiry and epoch fences.
Focused source tests now also cover dynamic issue/renew/revoke, durable
indeterminate no-blind-retry behavior, signed reconciliation, concurrent
authority owners, replay-journal migration and receipt fingerprint suppression.
The dedicated `.github/workflows/heptabao-qualification.yml` checks out the
exact candidate SHA, runs the focused tests plus package fmt/strict Clippy, and
uploads a machine-readable receipt containing that SHA and hashes of each
retained command record.

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
