# ui.native Rust development guide

This document is the executable-development companion to `docs/modules/ui.native/TECHNICAL.md`. It describes the selected native framework and the concrete Rust implementation under `apps/hepta-native`. It does not convert unsigned CI artifacts into release evidence.

## 1. Selected framework and platform matrix

The product shell uses `eframe 0.36.2` / `egui` with the native `winit` integration and AccessKit enabled.

| Platform | Product build | Accessibility | DPI/windowing | Platform effects | Packaging status |
| --- | --- | --- | --- | --- | --- |
| Windows x86_64 | first-class | AccessKit | native winit | open/reveal/clipboard; notifications remain packaged-AppUserModelID gated | CI unsigned zip |
| macOS arm64/x86_64 | first-class | AccessKit | native winit | open/reveal/clipboard/notification launcher | CI unsigned archive; signing/notarization external |
| Linux x86_64 | first-class | AccessKit | X11/Wayland via winit | open/reveal/clipboard/`notify-send` | CI unsigned archive |

The shell does not embed a browser and does not create a second Hepta execution spine. Runtime facts continue to come from the existing loopback-only Rust native gateway/runtime owners. The product shell requires the gateway's `keyring_bearer_v1` mode and refuses the legacy unauthenticated canary mode.

## 2. Source layout

- `src/runtime.rs` — session/view state machine, operation admission and reconciliation.
- `src/journal.rs` — bounded durable operation journal.
- `src/security.rs` — trusted Ed25519 key set and final-payload-bound grant verification.
- `src/platform.rs` — narrow local policy and OS adapters.
- `src/backend.rs` — authenticated loopback gateway client used for the native presentation state.
- `src/session_store.rs` — opaque session-reference persistence in the OS keyring.
- `src/updater.rs` — signed manifest verification, staging, predecessor backup and rollback.
- `src/bin/hepta-native-updater.rs` — separate update activator; the running GUI never self-replaces.
- `src/ui.rs` — eframe/egui product shell.
- `tests/runtime.rs` — session fencing, retry, restart and reconciliation tests.
- `tests/security_updater.rs` — signed grant and signed update tests.

The legacy `src/native.js` / `src/shell-runtime.js` tests remain compatibility/source-boundary fixtures until all registered callers and qualification maps point to the Rust product entrypoints.

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

## 4. Trusted grant boundary

`SignedPlatformGrantV1` binds:

- trusted key ID;
- session ID and generation;
- operation ID;
- registered action;
- SHA-256 of the final serialized `PlatformPayload` computed by Rust;
- expiration time.

The shell verifies an Ed25519 signature from an explicit absolute trusted-key-set path immediately before effect admission. The product verifier reloads that trust file for every platform effect, so adding a key ID to `revoked_key_ids` takes effect without restarting the shell. A matching caller-supplied pair of digests is not sufficient. Grants are short-lived and cannot be carried to a new session incarnation.

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

The UI currently consumes the existing read-only loopback gateway for runtime status. Mutating product workflows are added only when their owner exposes a registered grant/receipt contract; the shell does not invent a backend writer.

## 8. Development configuration

Required inputs:

- `--endpoint-manifest ABSOLUTE_JSON`
- `--trusted-keys ABSOLUTE_JSON`
- `--state-dir ABSOLUTE_PRIVATE_DIRECTORY`

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

## 9. Qualification

The native CI matrix must pass independently on Windows, macOS and Linux:

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo run --bin hepta-native -- --self-test
cargo build --release --bins
```

The runtime tests explicitly cover same-ID/new-session fencing, indeterminate retry without replay, process-restart reconciliation from the durable journal and close-with-pending behavior. Security/update tests cover Ed25519 final-payload binding, live signing-key revocation, selector/generator separation, stable-channel admission, stage digest, installed-predecessor fencing, independent updater activation and new-binary confirmation. The merge-candidate matrix starts the release binary again from each packaged artifact and emits an unsigned qualification receipt with checked-out SHA, source-head SHA and binary digests. A separate Ubuntu job checks out the exact PR head and reruns format, Clippy, tests, gateway tests and the product self-test.

CI output is not a production-release receipt. The generated artifacts are intentionally named `unsigned` until platform signing/notarization and independent acceptance are supplied.

## 10. Remaining external gates

Repository implementation cannot self-issue these facts:

- Apple Developer ID certificate custody and notarization result;
- Windows Authenticode certificate and packaged AppUserModelID/notification identity;
- Linux distribution signing/repository ownership;
- real target-host screen-reader acceptance evidence;
- observed OS notification/reveal terminality where the OS exposes no trustworthy transaction query;
- release-channel independent selection and operator acceptance.

Those gates must remain false in canonical qualification state until independently observed.
