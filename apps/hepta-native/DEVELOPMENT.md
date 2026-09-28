# ui.native current-source development guide

Canonical candidate: `work/ui-native-qualified-integration-20260928`, PR #1139.
The described implementation anchor is `a0d911f50bddf35da7b3a8cd7e671373a3c128fb`.
This is committed source awaiting successful native qualification, not a release.
Read the current [technical guide](../../docs/modules/ui.native/TECHNICAL.md)
and [delivery ledger](../../docs/modules/ui.native/CURRENT_DELIVERY.json) first.
The former guide is retained byte-for-byte at
[history/DEVELOPMENT-before-supervised-readiness.md](../../docs/modules/ui.native/history/DEVELOPMENT-before-supervised-readiness.md).
Dated earlier closure ledgers describe history; they do not override current
journal v6, segmented retirement v2 or the present verification limitations.

## 1. Product and owner topology

`src/main.rs` constructs the verified endpoint, keyring-authenticated loopback
backend, one `NativeShellRuntime`, `OperationJournal`, private root, optional
kernel final-use gate, local OS policy, update manager and eframe/egui GUI.
The independent kernel owner issues and validates execution authority. UI
selection, authentication to read runtime status and local permission flags do
not issue that authority. The three binaries are `hepta-native`,
`hepta-native-updater` and `hepta-native-credential`.

The UI has one supervised worker slot. Runtime-bound work waits at most 30
seconds before admission and consumes `TaskAdmission::begin()` exactly once.
An admitted task is not detached or replayed when a UI request times out.
A failed shutdown prohibits update activation. The current GUI startup/update
recording also uses this supervisor; it no longer performs those writes directly
inside the frame callback.

## 2. Build the exact candidate

Start from a clean checkout and record the exact commit and tree:

```sh
git rev-parse HEAD HEAD^{tree}
git status --porcelain
rustc +1.95.0 -vV
cargo +1.95.0 build --manifest-path apps/hepta-native/Cargo.toml \
  --locked --release --bins
```

These are required commands, not a claim that the current source has passed.
Do not regenerate locks opportunistically inside qualification. Dependency or
format corrections must become reviewed ordinary commits before requalifying.
The native standalone graph and the relevant owner workspace both retain their
own committed lock context.

## 3. Configure authenticated read-only startup

Provision one selected loopback capability through the system credential store:

```sh
apps/hepta-native/target/release/hepta-native-credential provision gateway.local
```

The helper prints the account and token digest, not the capability value. Do not
put signing keys or capability values in repository files, diagnostics or UI
records. Use the same account for the normal gateway and signed endpoint:

```sh
cargo +1.95.0 build --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway --bin hepta-native-gateway
codex-rs/target/debug/hepta-native-gateway \
  --listen 127.0.0.1:7373 \
  --state-root /absolute/owner-provisioned-state \
  --auth-keyring-account gateway.local
```

The existing owner entry `hepta --serve-ui --listen 127.0.0.1:7373
--auth-keyring-account gateway.local` is the alternative documented product
composition. Do not create another domain database for the native shell.

Supply a trusted Ed25519 public-key set and a signed endpoint manifest binding
the loopback address, endpoint identity, protocol **2**, account and validity.
The product uses `keyring_mac_v2`; protocol-1/bearer fallback is not admitted.
See [GATEWAY_V2.md](../../docs/modules/ui.native/GATEWAY_V2.md) for exact proofs.
The private local state root must be absolute and current-principal private.
Unix owner/no-follow and Windows protected-DACL/no-reparse checks remain required.

```sh
apps/hepta-native/target/release/hepta-native \
  --endpoint-manifest /absolute/config/endpoint-v2.json \
  --trusted-keys /absolute/config/trusted-keys.json \
  --state-dir /absolute/private/hepta-native-state
```

Installed launches can use `--config /absolute/config.json`. With no arguments,
configuration is selected from the platform user configuration directory:
Linux XDG config (or `~/.config/hepta-native/config.json`), macOS
`~/Library/Application Support/HeptaNative/config.json`, or Windows
`%APPDATA%/HeptaNative/config.json`.

```json
{
  "endpoint_manifest": "/absolute/config/endpoint-v2.json",
  "trusted_keys": "/absolute/config/trusted-keys.json",
  "state_dir": "/absolute/private/hepta-native-state",
  "allow_clipboard": false,
  "allow_notifications": false,
  "allowed_roots": []
}
```

The bounded configuration reader rejects unknown fields and unsafe inputs.
Optional final-use authority, updater-helper and font paths are absolute. The
restart handoff freezes expanded arguments, so later edits to the config file
cannot silently change a selected update's endpoint or local authority context.
Font fallback is optional; no font files are redistributed by this revision.

`--check-connection` runs the normal signature/keyring/gateway/session/view path
and closes it without claiming a GUI callback. A static `--self-test` is also
not installed-process update readiness.

## 4. Execute an independently authorized operation

A mutation additionally requires an independently provisioned final-use owner
and explicit local policy ceilings, for example `--final-use-authority
/absolute/config/final-use-authority.json --allow-clipboard`.
Omitting that owner allows read-only startup but cannot authorize an effect.

Prepare the exact binding in Operations, obtain a signed grant from the actual
independent authority owner, then select that grant file. The GUI must not sign
or invent the grant. Each request freezes owned input and binds endpoint,
session incarnation, displayed revision, view/content, operation, payload and
applicable resource identity before final use.

OpenPath/RevealPath remain explicitly unavailable. `--allow-root` does not enable
a mutable path-string launcher. Clipboard reports terminal success only after
exact immediate readback; notification launcher exit does not establish delivery.
Unknown results must be reconciled without resending the effect. Closing
observation means the outcome remains UNKNOWN and replay is forbidden.

## 5. File selection, focus and GUI readiness

Choose-file buttons now invoke concrete platform dialogs with an exact
single-use target ticket. Linux requires `/usr/bin/zenity`; a missing executable
reports adapter unavailability. macOS and Windows use static platform dialog
invocations. These adapters do not interpolate selected paths into commands.

Results are limited to one absolute UTF-8 path and a bounded output size.
Cancelled/replaced/wrong-target/stale callbacks cannot populate another field or
consume a newer intent. Switching screens invalidates the previous intent.
Accepted results restore focus to the selected field; drag/drop uses the same
ticket contract. The actual grant/manifest/package is still reopened by the
bounded file reader. Choosing a file is not a verified resource handoff.

Dialog processes and their bounded output readers remain owned until observed
and joined. The 120-second observation budget is not a guarantee that every OS
reaping operation can be force-terminated. Shutdown still refuses activation
while admitted work remains unresolved.

A first successful GUI callback remembers the exact authenticated view. A later
callback for the same view produces a private readiness witness. The existing
worker rechecks that witness against the current owner before recording startup
or confirming update readiness. This keeps file I/O off the paint path while
retaining actual callback identity. It proves neither physical display nor
screen-reader/IME acceptance. A readiness persistence/read error causes safe
shutdown rather than an apparently successful empty update state.

## 6. Journal and retirement recovery

The current journal writer is v6; retirement uses immutable v2 segments.
Active limits remain 4096 records and 8 MiB. The old 32768-identity legacy vector
ceiling does not describe segmented retirement. Memory and startup work still
grow with the retained chain; there is no implemented disk-index or constant-
memory claim in this revision.

A mixed batch cannot attach a newly supplied receipt to an old identity-only
tombstone. The whole batch is checked before record writes, and the two
`retirement_claim_tests.rs` tests are explicitly mounted in the parent module.
Previously committed exact archived duplicates still return their original
receipt without another permission request, authority claim or OS dispatch.

On corruption or persistence uncertainty preserve the journal, previous forensic
snapshot, retirement segments/head and update records. Do not restore an older
checkpoint merely because it parses. Do not delete the journal or retirement
store to regain capacity. Reopen/reconcile through the existing owner. Restoring
all local files together still needs independent anti-rollback authority.

History presentation uses 64-row pages with stable operation control identity.
Paging does not remove records or release replay fences. Owner-mediated closed
history compaction retains archived identities and receipts. The runtime still
copies its bounded active history; active-log indexing, append/checkpoint writes
and allocation reduction remain unimplemented optimization work.

## 7. Signed update and rollback

A signed stable-channel update binds candidate and predecessor digests, target,
protocol, evidence and independent selector/generator identities. Verify/stage
uses the existing update lock. Activation requests safe GUI shutdown; the helper
may start only after admitted work is joined and runtime close is confirmed.

The helper rechecks the manifest, staged bytes and installed predecessor. A
candidate remains ActivatedUnconfirmed until normal process/handoff/view/GUI
readiness is established. It cannot use `--self-test` or exit zero as that proof.
A read failure is not absence, and an unrelated newer binary cannot be replaced
by stale rollback. Failed or uncertain recovery stays RecoveryRequired.

Use the release contract for operational promotion and rollback. Real signed
installers, release-artifact upgrades, Windows replacement details, macOS bundle
signing/notarization, production key rotation/revocation and physical-host crash
cuts are not qualified merely by these source state machines.

## 8. Required verification commands

```sh
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml \
  --locked --lib -- --list
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features -- -D warnings

cargo +1.95.0 fmt --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state -- --check
cargo +1.95.0 test --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state --all-targets --all-features
cargo +1.95.0 clippy --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state --all-targets --all-features --no-deps \
  -- -D warnings
```

The compiled test listing must include
`legacy_tombstone_cannot_acquire_an_uncommitted_receipt_in_a_mixed_batch` and
`exact_archived_duplicate_still_returns_the_same_receipt_after_restart`.
Then execute them, not merely a text search. New readiness, pagination and picker
parser/owned-process tests also require actual compilation and execution.
Source-inventory Python tests and generated lexical test registries are not
substitutes for the compiler's discovery list.

The historical Linux feedback run `36450557375` on `6ff6cd0...` failed formatting
and compiled test discovery. Native tests and Clippy were skipped. Infrastructure
success from that run is neither current-source success nor product acceptance.
All later source needs fresh exact-source results. Global derived document/source
indexes still require regeneration and verification; this guide is not evidence
that their drift checks passed.

## 9. Packaging and installed-product qualification

```sh
python3 apps/hepta-native/tools/package_unsigned.py --self-test
python3 apps/hepta-native/tools/package_unsigned.py \
  --platform linux --architecture x86_64 \
  --release-dir apps/hepta-native/target/release --out-dir native-package
```

Use the appropriate macOS/Windows values on those runners. Deterministic unsigned
ZIPs contain the shell, updater, credential helper and platform metadata. Run the
packaged binary's self and crash profiles, not only the source-tree executable.
The package validator's checksums are not production signatures.

The full remediation workflow requires Linux/macOS/Windows × exact head/fixed-
base deterministic merge. The fast read-only source-integrity lane is diagnostic
feedback, not a replacement for those six subjects. Qualification cannot patch
or push its candidate. The retired source writers must not be re-enabled as a
way to obtain a green check.

The installed Linux exercise uses the normal gateway, an isolated real keyring,
a verified unpacked GUI and an owner-format fixture under Xvfb. It observes
virtual focus, lifecycle and owner-state immutability, but does not prove physical
keyboard/display, screen-reader, Chinese IME, mixed DPI, endurance or production
key custody. See [RELEASE_AND_PLATFORM_CONTRACT.md](../../docs/modules/ui.native/RELEASE_AND_PLATFORM_CONTRACT.md).

## 10. Completion and remaining engineering

Retain source implementation, compiled-test reachability, exact-head execution,
merge execution, target-host acceptance and independent release as separate
states. This revision has not completed all of them. In particular, the disk
retirement index, active-journal write-amplification work, million-record/native
performance measurements, verified-handle path effects and production installer
lifecycle remain open, as do final native/projection checks.

Current guides replace conflicting old candidate/protocol statements while
preserving the old documents under `history/`. This is a documentation correction,
not a passing receipt. Production, deployment, independent acceptance and release
flags must remain false until their own real evidence is retained and reviewed.
