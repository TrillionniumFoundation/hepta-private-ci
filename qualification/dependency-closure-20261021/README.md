# Dependency blocker closure — 2026-10-21

This qualification applies to the dependency changes based on
`b11459f46519e814ab9036c34a0cd7d3c3028e2b`. The source and lock hashes are in
`source-review.json` and `locks-and-inputs.json`; raw command receipts and output
are retained beside this file (raw logs are gzip-compressed without edits). It closes the four remaining dependency-policy
findings for basic-toml, zbus_names, zvariant, and zvariant_derive without adding
advisory exceptions or removing credential features.

## Changes and provenance

1. The narrow i18n-config 0.4.8 parser backport from owner PR #2961,
   `c210d26350ac57e527b4ff59663e5c8d518ff95a`, reuses the maintained TOML parser
   already resolved by the product. It follows the
   [upstream parser fix](https://github.com/kellpossible/cargo-i18n/commit/2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4).
   The broader workspace/edition/API modernization in owner #2976 was not needed.
   Cargo's real resolver retains the TOML 1.1.8 dependency edges; they are not
   manually trimmed. All six configuration-parser regression tests passed.
2. [Secret Service upstream PR #122](https://github.com/open-source-cooperative/secret-service-rs/pull/122),
   commit `7a91b597904c1847f18a06b72a19ee8153e0a578`, supplies the compatibility
   migration to the published zbus 6.0.0 release, which incorporates the former
   name/variant crates. This upstream PR was open and had no submitted reviews
   when inspected; the vendored package is explicitly identified as a backport,
   not a published Secret Service release.
3. The original zbus-secret-service-keyring-store 1.0.1 changes only dependency
   versions and the moved object-path imports, plus repository formatting.
   Its `unixexec` and `ibus` transport support is explicitly retained. The
   product's `keyring-store/src/lib.rs` is byte-identical to the baseline: keyring
   4.2's v1 factory, caller-installed stores, platform selection, default
   collection, service/username/target matching, mutex serialization, labels,
   ambiguity handling, and product error mapping remain in place.

The maintained zbus 6 API is asynchronous. The upstream compatibility layer
uses zruntime to preserve the blocking Secret Service API. A local adjustment
creates its connection on a short-lived initialization thread so optional zbus
Tokio feature unification cannot bind I/O to an ambient current-thread Tokio
runtime which the synchronous call then blocks. zruntime's helper drives the
independent connection after that thread or the caller's Tokio runtime exits.
Thread initialization failures remain errors. Operations still block and hold
the existing store mutex; no new cancellation promise, secret-retaining worker
queue, plaintext fallback, or in-memory fallback is introduced.

The MIT/Apache license files of both credential crates and the i18n-config MIT
license were verified byte-for-byte against their published sources. A trial
dbus-secret-service backend was rejected even though cargo-deny passed: its
vendored libdbus-sys included libdbus 1.14.4 with an AFL-2.1/GPL-2.0-or-later
license choice not represented by the bindings' Cargo license metadata. That
backend and its dependencies are absent from the final graph.

## Executed gates

| Gate | Actual result |
| --- | --- |
| `cargo update -p i18n-config -p zbus-secret-service-keyring-store` | Resolver completed; no hand-edited Cargo dependency graph |
| `cargo-deny --locked check` | Advisories, bans, licenses, and sources all passed |
| RustSec policy guard and its unit suite | Guard passed; 4 tests passed; policy files unchanged |
| `just test -p codex-keyring-store --locked` | 1 integration test passed, 0 skipped |
| `just test` on byte-identical isolated i18n-config source | 6 parser tests passed, 0 skipped |
| `just test` on the isolated Secret Service prompt filter | 4 selected protocol tests passed; 74 unrelated upstream tests excluded by the explicit filter |
| Original/patched native credential probes | 23 process cases passed on a private D-Bus/GNOME Keyring fixture |
| `just bazel-lock-update` | Completed using the final Cargo graph and actual applied zlib patch |
| Repeated `just bazel-lock-update` | Completed successfully |
| Original `just bazel-lock-check` | Error-mode lock drift gate passed |
| `just fix -p codex-keyring-store --locked` | Completed without source rewrites |
| `just fmt` | Completed after semantic tests, as required by AGENTS.md |

The isolated vendor workspace is necessary because Cargo refuses to test a
non-workspace dependency with dev-dependencies from the main workspace. The
source-copy receipt records byte-identical test inputs. The temporary workspace
uses a minimal two-thread `local` nextest profile: the main workspace's package
filters refer to packages that do not exist in this vendor-only workspace.
All Rust test execution went through `just test`. Tests were not rerun after the
final purely mechanical format pass.

The first Bazel invocation failed because its embedded Java CA store lacked the
environment's existing trusted system roots. Successful invocations used
`/etc/ssl/certs/java/cacerts`, retaining TLS certificate verification, a 1536 MiB
heap, two jobs, and dedicated caches. After the combined source added the V8
proof-of-concept crate's default `sandbox` feature to match its linked runtime,
the real update/repeat/error-mode checks passed again with identical lock hashes
(`final-bazel-idempotence.json`). V8 native execution is recorded by the main
combined-source qualification, not by this dependency probe. Actual patched
`rules_rs/rs/private/rustc_repository.bzl` contained the verified Ubuntu zlib
2.2 URLs and both architecture hashes. This was dependency resolution and patch
application verification; it does not claim a full Bazel application build.

## Native semantics exercised

The probe directly includes the unchanged product store source. The baseline
has its own Cargo graph pinned to keyring 4.2.0, Secret Service 5.2.0, and zbus
5.19.0; the candidate uses the final path patches and zbus 6.0.0. The standalone
locks were seeded from the corresponding product locks to retain their versions.
The baseline intentionally retains retired packages solely as an interoperability
control and is outside the product workspace.

The 23 process cases covered:

- Original backend writes, candidate reads/updates, original reads the update,
  candidate deletes, and original observes absence.
- Unicode and binary secrets, invalid UTF-8 error propagation, account/service
  isolation, complete application attributes, default labels, and rejection of
  changes to controlled attributes.
- Target-qualified items in the default collection and ambiguous untargeted
  reads, writes, and deletes, preserving both existing entries.
- A complete GNOME Keyring daemon restart followed by reads from both versions.
  The fixture used a nonempty synthetic keyring password; its persistent file
  contained none of the known synthetic secret plaintexts.
- Synchronous calls, current-thread Tokio, multi-thread Tokio, and Tokio
  `spawn_blocking`, both with and without the optional zbus Tokio feature.
  Further operations after the originating Tokio runtime was destroyed also
  passed.
- Initialization on an exiting native thread, followed by four concurrent
  credential workers on the shared store; cached initialization failures on an
  absent bus stayed errors for all product operations.

The private session bus and XDG/control/data paths were disposable. No real
credential data or user session bus was accessed. Initial probe attempts found
that GNOME's own `xdg:schema` annotation can be absent or added by the daemon;
the final probe validates that annotation if present and compares every
application attribute exactly. Those baseline-only fixture assertion failures
are retained in the attempt logs.

Prompt cancellation/disconnect/malformed-message cases use serialized D-Bus
protocol fixtures. Interactive desktop prompt UI and the unselected upstream
test suite were not claimed as executed. Existing Apple/Windows backend
dependencies are unchanged; their native execution belongs to the platform
qualification gates.

## Reproduction

Use the repository's Rust 1.95 toolchain and installed `just`/nextest/cargo-deny.
Keep `CARGO_BUILD_JOBS=2`, disable development debug info if resources are limited,
and preserve each compiled candidate binary before building the next feature
variant:

```sh
cargo build --locked --manifest-path qualification/dependency-closure-20261021/baseline/Cargo.toml
cargo build --locked --manifest-path qualification/dependency-closure-20261021/candidate/Cargo.toml
cargo build --locked --manifest-path qualification/dependency-closure-20261021/candidate/Cargo.toml --features zbus-tokio
```

Run `run_native.py --help` for the three binary paths, extracted GNOME Keyring
prefix, and output directory. The script launches its own `dbus-run-session` and
requires `dbus-send`; it fails on unexpected Secret Service ownership and applies
an external timeout to every probe. GNOME packages were downloaded from signed
Ubuntu package indexes, hash-verified, and unpacked without installing system
packages; `gnome-packages.json` records the exact artifacts.

After changing dependency inputs, use `just bazel-lock-update` from the repo root
and the original `just bazel-lock-check`, then `cargo-deny --locked check` from
`codex-rs`. Remove the path patches together when compatible maintained upstream
releases pass the same semantic qualification.
