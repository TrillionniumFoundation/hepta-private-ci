# ui.native Rust development guide

This document is the executable-development companion to `docs/modules/ui.native/TECHNICAL.md`. It describes the selected native framework and the concrete Rust implementation under `apps/hepta-native`. It does not convert unsigned CI artifacts into release evidence.

## 1. Selected framework and platform matrix

The product shell uses `eframe 0.36.2` / `egui` with the native `winit` integration and AccessKit enabled.

| Platform | Product build | Accessibility | DPI/windowing | Platform effects | Packaging status |
| --- | --- | --- | --- | --- | --- |
| Windows x86_64 | first-class shell | AccessKit | native winit | kernel final-use durable store + local effect adapters are source-composed; installed notification identity/target-host permission evidence remain external | CI unsigned zip |
| macOS arm64/x86_64 | first-class | AccessKit | native winit | open/reveal/clipboard/notification launcher | CI unsigned archive; signing/notarization external |
| Linux x86_64 | first-class | AccessKit | X11/Wayland via winit | open/reveal/clipboard/`notify-send` | CI unsigned archive |

The shell does not embed a browser and does not create a second Hepta execution spine. Runtime facts continue to come from the existing loopback-only Rust native gateway/runtime owners. The product shell requires the gateway's `keyring_bearer_v1` mode and refuses the legacy unauthenticated canary mode.

## 2. Source layout

- `src/runtime.rs` — session/view state machine, operation admission and reconciliation.
- `src/journal.rs` — bounded durable operation journal.
- `src/security.rs` — signed endpoint/update trust plus the adapter from `kernel.authority::FinalUseAuthority` to the exact native platform binding.
- `src/platform.rs` — narrow local policy and OS adapters.
- `src/backend.rs` — authenticated loopback gateway client used for the native presentation state.
- `src/session_store.rs` — opaque session-reference persistence in the OS keyring.
- `src/updater.rs` — signed manifest verification, staging, predecessor backup and rollback.
- `src/bin/hepta-native-updater.rs` — separate update activator; the running GUI never self-replaces.
- `src/ui.rs` — eframe/egui product shell.
- `tests/runtime.rs` — session fencing, retry, restart and reconciliation tests.
- `tests/security_updater.rs` — signed grant and signed update tests.

The former JavaScript `src/native.js` / `src/shell-runtime.js` boundary has been retired from this candidate; the Rust executable and its integration tests are the only canonical `ui.native` product surface.

## 3. Runtime correctness and crash semantics

Operation identity is:

```text
(session_id, session_generation, operation_id)
```

A reused `operation_id` in a new backend session cannot return an earlier session's receipt. Durable operation phases are monotonic:

```text
Prepared -> Invoking -> Indeterminate -> Terminal
                 \---------------------> Terminal
Prepared ------------------------------> Terminal
```

The journal writes and fsyncs `Invoking` **before** the adapter call. Therefore:

- a prior-session `Prepared` record is known not to have entered the adapter and is quarantined on reconnect;
- `Invoking` and `Indeterminate` records are never replayed after retry/restart;
- the platform adapter's `reconcile` method is the only route from an uncertain record to terminal state;
- close/reconnect never erases pending records;
- terminal records cannot be downgraded to a non-terminal phase.

For current local OS effects, open/reveal/notification launch success is intentionally not treated as observed terminal success. The underlying OS launch APIs do not provide a trustworthy transaction-observation query. Clipboard writes can become terminal only when an immediate readback matches. After process loss the payload body is deliberately absent from the journal, so uncertain local effects remain indeterminate instead of leaking content or replaying them.

## 4. Kernel final-use authority boundary

Platform mutation authority is not defined by `ui.native`. The shell consumes the existing kernel-owned `FinalUseAuthority` from `codex-rs/hepta-contracts`.

For each effect the Rust shell computes a `FinalUseBinding` that binds the principal, session ID and generation, operation ID, displayed revision, registered action, destination and SHA-256 of the final serialized `PlatformPayload`. The execution order is:

```text
durable Prepared
-> FinalUseAuthority::claim(signed_grant, exact_binding)
   (signature/epoch/revocation/time checks + durable single-use nonce)
-> durable Invoking
-> FinalUseAuthority::with_verified_use(token, exact_binding)
   (current epoch/revocation/time checked again)
-> local platform policy check at adapter entry
-> physical OS adapter
-> durable observation/reconciliation
```

`VerifiedUseToken` is non-cloneable and non-serializable; the UI cannot mint one. A matching pair of caller-supplied digests is not authority. Revocation is loaded from the explicit absolute `--final-use-authority` host configuration before claim and again before physical adapter entry. Trust identity or state-directory changes in place fail closed.

If no final-use authority is composed, the shell records a rejected no-dispatch terminal result. The kernel authority store has platform-specific durable implementations for Unix and Windows. Unix uses owner-only/no-follow file semantics plus file/directory fsync; Windows uses the `hepta-private-state` private-directory boundary and dedicated durability tests. Neither platform falls back to a native-local signer or weaker replay registry.

The local platform policy is a second ceiling, not authority. Paths must be absolute, canonicalizable and underneath one of the explicitly configured roots. Clipboard/notification classes are disabled unless their local policy switches are present.
## 5. Session/keychain and loopback authentication boundary

Only opaque `SessionIncarnation` references, the manifest digest, and a random loopback gateway bearer capability are persisted through `codex-keyring-store`, which uses the platform keyring backend. Domain facts, model/provider credentials and signing private keys are never stored by `ui.native`.

The gateway bearer capability is provisioned by the separate `hepta-native-credential` helper using the OS CSPRNG. The helper prints only the keyring account and SHA-256 token digest; the bearer itself never appears on stdout. The existing Rust gateway accepts `--auth-keyring-account ACCOUNT`, loads the same secret from service `hepta.native.gateway.v1`, and requires `Authorization: Bearer ...` before serving authenticated product-shell requests.

The endpoint configuration is separately signed as `hepta.endpoint-manifest.v1`. Its digest/signature bind endpoint ID, loopback address, protocol version, gateway keyring account, issue/expiry times and trusted signing key. The GUI verifies that manifest before reading the bearer from the keyring. A process merely listening on the expected localhost port therefore cannot satisfy the new product-shell bootstrap unless it also proves the configured bearer capability.

A keyring error, unsigned/tampered endpoint manifest, legacy `native_auth=disabled` health response, or credential mismatch fails application bootstrap instead of silently falling back to plaintext credentials or trusting localhost.

## 6. Signed updater and rollback

`SignedUpdateManifestV1` binds package/predecessor/evidence digests, platform, architecture, backend protocol, channel, selector, generator, issue/expiry times and signing key. The selector and generator principals must differ.

Update flow:

1. Verify the stable product channel, target tuple, time bounds and Ed25519 signature.
2. Hash the package and require the signed package digest.
3. Copy to the private staging directory, fsync, and hash again.
4. Write `pending-update.json` atomically.
5. A separate `hepta-native-updater` process re-verifies the signed manifest and staged digest.
6. Hash the installed target and require the signed predecessor digest before any replacement; then back up that exact predecessor.
7. Replace from a temporary file; on replacement or post-copy digest failure restore the predecessor.
8. Leave the state `ActivatedUnconfirmed` until the new process confirms its own running binary digest, then clear the pending record.

This is repository-controlled update mechanics. Production signing certificate custody, Apple notarization, Windows signing/AppUserModelID registration, package repository/TUF-like channel governance and actual release selection remain external deployment evidence.

## 7. UI and accessibility

The selected shell has four views: runtime, operations, updates and accessibility. Pending/indeterminate status is visible instead of converted to success. Navigation uses standard focusable egui controls. AccessKit is compiled in; Tab/Shift+Tab and Enter/Space follow the native control focus order. Winit/eframe own per-monitor DPI scaling. Shell copy is localized for English and Chinese using `LC_ALL`, `LC_MESSAGES` or `LANG`.

The Updates view accepts absolute signed-manifest/package paths, performs signature/target/predecessor staging through `UpdateManager`, and can request activation. Activation first closes the GUI; only after `eframe::run_native` returns does `main` spawn the independent updater helper. The helper re-verifies the pending record and new binary, rolls back on failure, and uses a bounded Windows permission-denied retry to bridge the executable-file-lock handoff.

The runtime view consumes the existing read-only loopback gateway. Platform mutation consumption is source-composed behind the kernel final-use boundary. The product authority ingress is deliberately separate: the GUI accepts an independently issued `SignedFinalUseGrant` file for the exact displayed binding. Automated Agentd/gateway grant delivery is not required for source closure and must not turn the read-only gateway into an authority issuer or mutation owner.

## 8. Development configuration

Required inputs:

- `--endpoint-manifest ABSOLUTE_JSON`
- `--trusted-keys ABSOLUTE_JSON`
- `--state-dir ABSOLUTE_PRIVATE_DIRECTORY`

Required for platform mutations on a host with a qualified kernel authority store:

- `--final-use-authority ABSOLUTE_JSON`

Optional host/update configuration:

- `--updater-helper ABSOLUTE_EXECUTABLE` (otherwise the packaged sibling/Helper location is resolved)

Optional local ceilings:

- repeatable `--allow-root ABSOLUTE_PATH`
- `--allow-clipboard`
- `--allow-notifications`

Provision the gateway capability first:

```sh
cargo run --bin hepta-native-credential -- provision gateway.local
hepta --serve-ui --listen 127.0.0.1:7373 --auth-keyring-account gateway.local
```

Signed endpoint manifest shape:

```json
{
  "schema": "hepta.endpoint-manifest.v1",
  "endpoint_id": "runtime.local",
  "address": "127.0.0.1:7373",
  "protocol_version": 1,
  "gateway_credential_account": "gateway.local",
  "issued_unix_ms": 0,
  "expires_unix_ms": 0,
  "key_id": "release.key.1",
  "manifest_digest": "<sha256 of the canonical endpoint payload>",
  "signature_base64": "<Ed25519 signature>"
}
```

The zero timestamps above are shape placeholders only and will fail verification; an actual manifest must carry a current bounded issue/expiry window and valid signature.

Trusted public keys example:

```json
{
  "schema": "hepta.native-trusted-keys.v1",
  "keys": {
    "release.key.1": "<base64 32-byte Ed25519 public key>"
  },
  "revoked_key_ids": []
}
```

Private signing keys do not belong in this repository or in the native state directory.

Kernel final-use host configuration example:

```json
{
  "schema": "hepta.native-final-use-authority.v1",
  "signer_id": "authority.native",
  "verifying_key_base64": "<base64 32-byte Ed25519 public key>",
  "state_dir": "/absolute/private/kernel-final-use-state",
  "head": {
    "authority_epoch": 1,
    "revision": 1,
    "revoked_grant_ids": []
  }
}
```

The final-use signer remains the independent supervisor-owned `hepta-final-use-signer`; its private seed never belongs in the GUI, keyring session store, or native state directory. Windows uses the kernel-owned durable authority store added in this candidate; production trust roots and target-host acceptance remain separately governed.

## 9. Qualification

The native CI matrix must pass independently on Windows, macOS and Linux:

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo run --bin hepta-native -- --self-test
cargo run --bin hepta-native -- --qualification-e2e
cargo build --release --bins
```

The release binary also exposes an explicit authority-free `--qualification-e2e` profile. It uses the product runtime, durable journal, kernel final-use store and updater state machine with deterministic fake backend/platform adapters inside an isolated temporary root; it never invokes real OS effects. The profile forks and kills packaged child processes to prove an `Invoking` parent-death cut reconciles without replay and an `ActivatedUnconfirmed` updater-death cut restores the admitted predecessor. It also verifies authenticated runtime-view composition, same-ID/new-generation fencing, permission denial before dispatch, current grant revocation immediately before effect entry, and durable `RecoveryRequired` when rollback evidence is destroyed.

The runtime tests explicitly cover same-ID/new-session fencing, indeterminate retry without replay, process-restart reconciliation from the durable journal, close-with-pending behavior and no-dispatch when kernel authority is unavailable. Security/update tests cover exact kernel final-use binding, live grant revocation before adapter entry, selector/generator separation, stable-channel admission, stage digest, installed-predecessor fencing, independent updater activation and new-binary confirmation. The merge-candidate matrix starts the release binary again from each packaged artifact and emits an unsigned qualification receipt with checked-out SHA, source-head SHA and binary digests. A separate Ubuntu job checks out the exact PR head and reruns format, Clippy, tests, gateway tests and the product self-test.

CI output is not a production-release receipt. The generated artifacts are intentionally named `unsigned` until platform signing/notarization and independent acceptance are supplied.

## 10. Remaining external gates

Repository-controlled closure now uses the operator-selected independently issued `SignedFinalUseGrant` as the product authority ingress and includes durable kernel final-use stores for Unix and Windows. Remaining repository gates are reproducible dependency locking and current exact-head/merge-candidate execution receipts. The packaged fault/restart profile is now source-composed but does not become evidence until the final packaged artifacts execute it successfully.

Repository implementation cannot self-issue these facts:

- Apple Developer ID certificate custody and notarization result;
- Windows Authenticode certificate and packaged AppUserModelID/notification identity;
- Linux distribution signing/repository ownership;
- real target-host screen-reader acceptance evidence;
- observed OS notification/reveal terminality where the OS exposes no trustworthy transaction query;
- release-channel independent selection and operator acceptance.

Those gates must remain false in canonical qualification state until independently observed.
