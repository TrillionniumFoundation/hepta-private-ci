# Current Matrix security and storage migration

This is an independently qualified successor to secure keyring source and lock
`2aea30d1e07288f059c9294f29a842c40b6c9416`. Historical PR #1333 is a source donor
for narrow reviewed patches and synthetic fixtures. Its previous green results
are not acceptance evidence for this tree.

## Production changes

- Upgrade official Matrix SDK, crypto and stores from 0.18.0 to exact SDK 0.19.1.
  This includes the upstream fix for RUSTSEC-2026-0318. Use the release's real
  Rust 1.96 requirement throughout executable Cargo, Bazel and workflow pins.
- Replace the SDK's abandoned `anymap2` event-context map with `anymap3` 1.1.0.
  Native Clone + Send + Sync and wasm Clone bounds remain explicit.
- Keep the SQLx 0.9 implementation and align its native SQLite requirement to
  exact libsqlite3-sys 0.38.2, shared with rusqlite 0.40.2. Remove only the obsolete
  Matrix SQLite 0.18 patch selector, while retaining that original source for the
  isolated historical fixture producer.
- Keep the Starlark 0.14.2 implementation and align its BLAKE3 exact pin to 1.8.7.
  The old imbl 6 patch selector is removed only after actual resolution proved
  that the new SDK graph exclusively uses maintained imbl 7.0.2.

The production `MatrixSdkPaths` implementation stays unchanged. Existing
`matrix-sdk-0.18/state`, `cache`, and `session.json` paths remain in use. No
high-entropy-passphrase feature is enabled. Upstream derived-cache resets and
sliding-sync-position migration are tested explicitly; they are not permission
to remove Hepta's authoritative inbox, outbox, cursor or authorization state.

## Source provenance and observed local checks

`official-packages.json` retains checksum-verified official package sources.
`vendor-member-provenance.json` accounts for all 951 official members: 630 exact
original bytes, 315 repository-formatting-only files, and six functional patch
files. Each formatting difference was independently replayed on the official
member with the same Rust 1.96 formatter and repository configuration. The
resulting functional diff is only 84 lines in `vendor-functional.patch`.

The actual full-workspace resolver first failed on the BLAKE3 exact-pin conflict,
then on SQLite's native `links` conflict. These failures remain in `resolver-*`.
After the narrow patches, real Rust 1.96 full-workspace all-features metadata
succeeded. Twelve attempts to retain selected older baseline transitive versions
were rejected by specific new minimum requirements; no constraint was weakened.

With unchanged deny policy and RustSec DB
`6c5fedf8ff03c485ed674d8f941e0180f3f72d70`, actual `cargo deny --all-features
--locked check --disable-fetch --show-stats` reduced four advisory errors to two:
RUSTSEC-2024-0449 (unsafe-libyaml) and RUSTSEC-2026-0387 (crypto-bigint). Those are
owned by separate YAML and AWS changes and are not silently imported here. Bans,
licenses and sources have zero errors. No ignore, allow or source-policy change
was made. Full compressed output and hashes are retained.

The isolated official Rust 1.96 installation was checked against its release
manifest and component hashes. `just fmt`, Python parsing and shell syntax checks
completed locally. Large native Matrix builds are intentionally executed in the
hosted qualification, with their actual failures retained.

## Required current-source runtime qualification

The branch workflow checks out the exact PR head and runs these independent modes:

| Mode | Actual scope |
| --- | --- |
| `owners` | Original protocol, SDK, durable-store and matrixd tests; unsigned-recipient regression through both affected crypto APIs; real SDK context replacement/type isolation; old derived-cache migration; scoped original Clippy fix must leave source unchanged. |
| `sqlite-starlark` | Original `codex-state` and `codex-execpolicy` library tests against the new SQLite/BLAKE3 graph. |
| `crypto-migration` | Separately locked actual SDK 0.18 producer creates synthetic encrypted data; the candidate opens it from the existing production state path twice and checks identity/cross-signing keys, old ciphertext decryption, pending gossip, unrelated metadata, session bytes, database integrity and authoritative Hepta cursor after closing and reopening its owner. |
| `synapse-protocol` | Pinned disposable Synapse on loopback only; actual encrypted send/sync, stable transaction replay, ciphertext observed at server, and SQLite/session reopen followed by another decrypted message. |
| `bazel` | Original `just bazel-lock-update` and `just bazel-lock-check`, actual SDK/SQLx/Starlark build, and the actual advisory/context/cache regression labels. |

Each native mode removes its old JUnit report before execution, rejects empty,
failed or skipped results, and checks source hashes before and after. Synthetic
fixtures never use live accounts. The old SDK producer has its own workspace and
does not enter the production dependency graph. The wrapper records failures even
when compilation stops before test execution.

The migration test constructs a synthetic session JSON and verifies only its byte
preservation; it does not establish production session restoration. The separate
Synapse qualification exercises real SDK session restoration. Source snapshots
also include the old patched SQLite package used by the isolated 0.18 producer.

Reproduce a mode with an official Rust 1.96 toolchain, `just` 1.51.0 and nextest
0.9.151 on PATH:

```bash
python3 qualification/matrix-sdk-019-current/run_qualification.py owners --output /tmp/matrix-owners
python3 qualification/matrix-sdk-019-current/run_qualification.py crypto-migration --output /tmp/matrix-crypto
python3 qualification/matrix-sdk-019-current/run_qualification.py synapse-protocol --output /tmp/matrix-synapse
python3 qualification/matrix-sdk-019-current/run_qualification.py sqlite-starlark --output /tmp/matrix-sqlite
python3 qualification/matrix-sdk-019-current/run_qualification.py bazel --output /tmp/matrix-bazel
```

## Acceptance state

**DRAFT / HOLD.** The current candidate's hosted native and Bazel results must be
collected, its actually generated MODULE.bazel.lock adopted and rechecked, and
the original full platform CI passed. Real paired-host Fleet qualification is an
additional deployment gate; isolated Synapse is not a substitute. The dependency
graph check and historical source provenance alone do not close those gates.
