# Keyring / zbus 6 dependency candidate

This candidate removes the unmaintained standalone zvariant, zvariant_derive and
zbus_names implementations by using the actual zbus 6.1 implementation. It keeps
keyring 3.6.3's public API and platform code. It is ready for the parent's coherent
workspace candidate; it does not claim that the full repository advisory or
platform gates have passed.

## Production inputs

Copy `vendor/keyring-3.6.3` and `vendor/secret-service-4.0.0` to the corresponding
`codex-rs/third_party` paths. Apply `keyring-zbus6-manifest.patch` to activate the
two packages through `[patch.crates-io]`. The parent owns the workspace manifests,
Cargo.lock and MODULE.bazel.lock; this agent did not edit them.

Both directories include the exact upstream licenses and original manifests,
an explanation of the narrow port, and the normal Bazel crate rule. The local
Bazel feature select explicitly retains each configured platform backend,
crypto-rust and the credential-label package version, rather than silently
compiling the mock default. Official
crate downloads were verified against crates.io's published checksums.
`UPSTREAM_SOURCE_FILES.json` maps every original file to its candidate checksum.
All keyring Rust files, including macOS, Windows and native Linux implementations,
are byte-identical. `source-review.patch` is the review diff against those official
sources; `production-source.tar.gz` is the complete copyable vendor tree.

The candidate has two substantive parts. The keyring manifest directs all three
Unix Secret Service target selections to zbus 6.1 and keeps the existing runtime
feature names. Secret-service migrates its wire types/proxies and implements its
existing blocking API with zbus 6's runtime driver. Local wire-conversion errors
retain their explicit category despite the upstream error-type merge. Prompt,
session and lock semantics use the same async implementation from blocking calls.

## Actual local verification

| Evidence | Result and exact scope |
| --- | --- |
| `check-003` and later source-bound builds | Actual Rust compilation with zbus 6.1.0. No standalone zvariant, zvariant_derive or zbus_names in the isolated resolved lock. |
| `real-dbus-007` | Frozen async-persistent and sync-persistent binaries both passed Entry CRUD, Unicode/binary values, missing/ambiguous/deletion semantics, attributes, v1 no-target compatibility and eight concurrent clients. |
| `real-dbus-007` | Both directions of cross-backend stored-credential write/update/read/delete passed against the same real GNOME service. Actual daemon termination/restart retained and reread a credential. |
| `real-dbus-007` | Explicit native/composite classes passed dual writes, session-cache refill, binary errors, dual deletion, empty-secret errors and rollback after missing/ambiguous persistent writes, inside fresh user namespaces and anonymous session keyrings. |
| `real-dbus-007` | Plain and DH transport passed through both secret-service public APIs. A separate served real D-Bus interface passed prompt success, dismissal and wrong-type conversion errors. |
| `real-dbus-tokio-001` | The same lifecycle/native/composite/prompt/daemon-restart behavior passed with the optional Tokio feature compiled. |
| `actual-consumer-001` | Compiled the actual repository `codex-keyring-store` crate, then verified load's Option semantics, a synthetic serialized OAuth-style payload, and true/false deletion. |
| `native-only-check-002`, `async-only-check-001`, `sync-only-check-001` | Additional preserved native-only, async-only and sync-only feature selections compiled. |

The harness uses the complete production crates; it is not a copied function
smoke test. These are isolated executable integration checks, not a replacement
for the repository's `just test` gates. Every command has its actual exit code and
log hash. Later build receipts bind every source input. Fixture binaries are
content-addressed before launching any subprocess.

## Important compatibility boundaries

1. Published keyring 3.6.3's default composite builder returns `SsCredential`, not
   `KeyutilsPersistentCredential`. That existing behavior is preserved. Explicit
   composite-class tests prove the native cache/persistent-store behavior without
   mislabeling the default Entry test as a native-cache test.
2. The test kernel returns `EOPNOTSUPP` for the optional kernel persistent
   register in a fresh user namespace. The native session cache and durable Secret
   Service store are tested. This does not prove kernel-register persistence or
   reboot persistence on this host. There was no fallback to a real user's ring.
3. GNOME sometimes adds `xdg:schema` and reports `text/plain` even when a raw
   binary item requested `application/octet-stream`. The unchanged libdbus client
   independently reports the same values. All client credential fields are
   checked; production code was not changed to match the server behavior.
4. macOS, Windows and iOS source and dependency selections remain unchanged,
   but those operating systems were not executed here. The first-party login,
   secrets and OAuth suites and both repository lock systems remain remote gates.
5. The secret-service package's foreign zbus payload types move to zbus 6. The
   preserved application surface is keyring's Entry/CredentialApi/Error API;
   arbitrary external consumers of secret-service 4 low-level types need their
   own source compatibility review.

## Cargo and Bazel platform feature closure

`evidence/PLATFORM_FEATURES.json` comes from a separate minimal Cargo graph whose
consumer is the actual repository `codex-keyring-store`. It does not inherit
the integration harness's forced backend features. The three `cargo tree`
commands all completed successfully. This establishes dependency and feature
selection; it is not cross-platform compilation or execution.

| Configured platform | Effective Cargo keyring features | Explicit local Bazel features | Dependency closure to review after Bazel lock generation |
| --- | --- | --- | --- |
| Linux | `async-secret-service`, `crypto-rust`, `linux-native`, `linux-native-async-persistent` | Same four features | `linux-keyutils` with `std`; local `secret-service` with `crypto-rust`; zbus 6 with `comms`, `default`, `default-rt`, `object-manager`, `proxy`, `service`, `tracing` |
| macOS | `apple-native`, `crypto-rust` | Same two features | `security-framework` with `OSX_10_14`, `alpn`, `default`, `session-tickets`; no Secret Service backend |
| Windows | `crypto-rust`, `windows-native` | Same two features | `windows-sys` credential APIs, `byteorder`, and `zeroize`; no Secret Service backend |

The workspace crate macro takes local `crate_features` explicitly. Its empty
default would compile the keyring mock backend even with correct external
dependency labels. Both vendor `BUILD.bazel` files therefore provide the
required local features. The keyring rule also sets `CARGO_PKG_VERSION` to
`3.6.3`, which is read by unchanged credential-label code, and supplies its
README as compile data. The secret-service rule selects `crypto-rust`; its
generated external zbus dependency must retain the Cargo runtime/proxy feature
closure above. No additional compile-time source resources were found.

The Linux target is the configured default. The supplied select covers the
repository's configured Linux, macOS and Windows Bazel platforms. Cargo's BSD
and iOS selections remain in the untouched platform implementation and patched
manifest, but this does not create new Bazel platform support. The isolated
feature graph has a fresh lock and resolves, for example, security-framework
3.7.0; that is not a request to change the workspace's existing 3.5.1 lock entry.
The parent's integrated lock must be evaluated on its own effective graph.

Root still needs to review the generated external dependency features, local
platform selects, version environment and README resource in actual Bazel
analysis/builds. The current candidate does not mark that gate as passed.

## Independent evidence review

`evidence/PEER_KEYRING_PORT.json` records a separate read-only review that
rehashed 52 original/ported source entries, all 15 unchanged original keyring
Rust files, 39 final-run logs, four content-addressed executables and the daemon.
It agrees with the lifecycle, error, prompt and isolation findings and retains
the limits above. The earlier `real-dbus-007` compilation receipt did not bind
the input source files before compilation; later Tokio and actual-consumer
compilation receipts do. The review and saved binaries do not constitute a
reproducible-build proof for that earlier executable.

## Negative evidence retained

The early compiler failures identify actual upstream API differences and were
fixed in source. The initial content-type assumption failed (`real-dbus-001`),
GNOME's extra schema field failed an over-strict fixture comparison (`002`), and
the running daemon's direct `--unlock` command did not unlock the collection
(`003`). The final lifecycle uses a real daemon restart/unlock and checks its
result. `005` records the unsupported optional kernel persistent register.

`real-dbus-006` is explicitly invalidated: a development build replaced a mutable
binary path during the subprocess sequence. It is excluded from the final
verification. `007` and later runs first freeze content-addressed binaries. An
initial native-only Cargo command selected a dependency outside the workspace and
failed; `native-only-check-002` correctly compiles the root's library probe under
that feature selection. No failed run was deleted or relabeled as passing.

## Isolation and reproduction

The fixture creates its own D-Bus daemon with no service-activation directories,
private socket, GNOME process, control directory and XDG storage. HOME is not
modified. Credentials and unlock passwords are public synthetic fixture values.
Native tests require a different user-namespace inode before joining a fresh
anonymous session ring. Only processes created by the runner are terminated.
Original synthetic keyring files and daemon logs are retained after shutdown.

`harness/Cargo.toml` points to this candidate's vendor tree and optionally to the
adjacent checkout's actual `codex-rs/keyring-store`; adjust that path when moving
the candidate. The harness is Linux-only. `run_cargo.py` documents the actual
toolchain/cache/target setup used here. `run_fixture.py LABEL --binary PATH
--sync-binary PATH` verifies the two immutable binaries; add `--codex-store` for
the actual-consumer feature build. Downloads of the official GNOME fixture
packages are bound to an immutable Ubuntu snapshot and distribution SHA-256s.

`package_candidate.py` produces and restores the copyable vendor archive,
verifies every restored file against its manifest, and creates the upstream
review diff. The complete vendor tree and this diff are the final production
inputs. `port_sources.py` is retained as a development history artifact; it
predates the subsequent reviewed edits and is not a one-command reproduction
of the final port.

After integration, run the relevant first-party tests through `just test`, update
the Bazel lock with `just bazel-lock-update`, check lock drift and run the unchanged
advisory policy. Include normal Linux, macOS and Windows jobs. Keep any upstream
keyring/secret-service unit tests inside an isolated test keystore as well.
