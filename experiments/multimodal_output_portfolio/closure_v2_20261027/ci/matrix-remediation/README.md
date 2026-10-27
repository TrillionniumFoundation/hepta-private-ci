# Matrix 0.19.1 / anymap3 candidate — Rust execution pending

Use CURRENT.json: the active vendor is matrix-vendor-v2.tar.gz. Review caught
empty Bazel crate_features in the initial vendor. The v2 bundle provides explicit
production library/build-script features and version 0.19.1, and emits no
upstream dev-test targets. The initial bundle and inventory remain retained.

This packet prepares the two remaining Matrix dependency repairs. It is not a
compilation, migration, security-scan or CI pass. The shared production
manifests, lockfiles, toolchains and ZIP/i18n candidate pipeline were not edited.

## Source and repair

| Item | Candidate | Reason and boundary |
| --- | --- | --- |
| Matrix SDK / crypto | Published 0.19.1 | RUSTSEC-2026-0318 requires crypto >=0.19.0. The actual published crypto source contains the upstream no-identity panic fix. |
| anymap2 | Actual anymap3 1.1.0 | Backport official commit 9c5fdd2. Use its real CloneAny implementation, retaining native Send + Sync requirements. |
| Matrix SQLite | Published 0.19.1, rusqlite exactly 0.39.0 | Preserve SQLx 0.9's libsqlite3-sys 0.37 native links graph. All upstream Rust storage code, SQL migrations and SQLite features are retained. |
| HTTPS | Explicit rustls-aws-lc-rs feature | Matrix 0.19 moved the provider out of the previously unconditional reqwest feature set. |
| Persistence path | Existing matrix-sdk-0.18 directory | Reopen existing identities and sessions; changing the directory would silently create a different store. |
| imbl | Upstream >=7.0.2 | New Matrix/common/eyeball-im no longer require the old imbl 6 compatibility override. Validate absence of imbl 6 in the resolved graph. |
| Rust / Bazel | Rust 1.96.0 | Required by the published 0.19.1 crates. Core and CI pins are separate patches. |

The SDK vendor contains the complete published package with three modified
upstream files: the two manifests and event_handler/mod.rs. The SQLite vendor
contains the complete published package with only its two manifests modified.
Each adds BUILD.bazel, the exact upstream root LICENSE and a patch note.
VENDOR_INVENTORY.json identifies every unchanged, changed and added file.
Original crate archives and official source/metadata responses are retained in
upstream-evidence.tar.gz. Both archives were reopened and every member hashed.

Upstream intentionally rebuilds the event cache during the 0.19 migration.
This packet does not claim that every cache row survives. The new cross-version
test checks identity public keys, complete session, stored state and the separate
authoritative Hepta cursor/inbox/outbox, then continues a batch and checks dedup.
The existing human-passphrase API is retained.

## Review stages

1. Apply matrix-fixture-tests.patch only to an independent checkout using the
   original Matrix 0.18 lock and Rust 1.95. Run its explicit producer test.
   Retain that source, lock, binary hash, command log and entire database fixture.
2. In a separate checkout, extract matrix-vendor-v2.tar.gz, apply the manifest,
   production, context-tests, fixture-tests and core toolchain patches, then
   resolve Cargo and regenerate the Bazel lock. Qualify this actual repository.
   Copy the sealed old fixture to a new writable directory before consuming it.
3. Apply matrix-toolchain-ci.patch when coordinating the global Rust migration.
   It only changes active compiler/action pins, including the old candidate
   workflow's compiler pin. It has not changed the currently running workflow.
   The exact official 1.96 action commit is d86e0fa8f147d6539442c26a61ebba8becc19489.

Never generate a replacement old fixture with the new candidate. The ordinary
restart test only proves same-version restart. The two ignored phase tests are
intentional explicit invocations; their skipped status is not a migration pass.
The consumer must pass exactly reopen_old_version_fixture against a producer
whose resolved Matrix/crypto/SQLite packages were 0.18.0.

The tests live in the existing codex-hepta-matrix-sdk workspace member and
exercise real SDK/store/HTTP paths. Do not claim that invoking an upstream
nonmember package with -p tests its dev-dependencies: Cargo refuses this, as the
prior i18n candidate demonstrated. Additional upstream unit tests need a
separately recorded qualification-only workspace overlay. Do not silently add
the SDK's default features to production workspace builds to obtain such tests.

Required execution and graph assertions are in QUALIFICATION_PLAN.json.
Rust compilation, both phase tests, real Synapse, lock generation and unchanged
cargo-deny remain pending. Do not change scan scope or ignore either advisory.

## Primary references

- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://github.com/matrix-org/matrix-rust-sdk/commit/01b45b51299821ab03fecf46741392780f118d49
- https://github.com/matrix-org/matrix-rust-sdk/commit/9c5fdd2cf5be1b7b8b20541e56d7a109db968534
- https://crates.io/api/v1/crates/matrix-sdk/0.19.1
- https://crates.io/api/v1/crates/matrix-sdk-sqlite/0.19.1
- https://crates.io/api/v1/crates/rusqlite/0.39.0
- https://crates.io/api/v1/crates/rusqlite/0.40.2
- https://static.rust-lang.org/dist/channel-rust-1.96.0.toml
