# Cargo-deny remediation boundaries

This is a read-only plan, not a remediation result. No dependency updates, lock
refreshes, compiler checks or new audit run have been performed for this plan.
The original security gate remains failed.

## Evidence and attribution

The reviewed repository source is
`ccdb7ea7cb9c4adecf6f6607ea1570cb81ae0f78`. The proposed isolated TLS experiment
will start from the later delivery commit
`90816a3d20bbba0d9d3acca451d30f328e5df7c5`.

The original job reported **22 advisory records: 16 vulnerability records and
6 unmaintained records, across 16 locked crate/version pairs**. These are not
22 independent CVEs. Three TLS records, 0381/0382/0383, share CVE-2026-111943.
The sibling diagnosis and source identity report establish that Cargo.toml,
Cargo.lock, deny.toml and the original audit workflow have identical Git blobs
at the original PR base, head and tested merge. This plan does not attribute
those dependencies to the research changes or assess runtime exploitability.

All official advisory texts are fixed at
[RustSec 3279c999](https://github.com/RustSec/advisory-db/tree/3279c99911354c400e1d41e47c7d60e39258b147).
Release metadata is fixed at
[crates.io index 0f21f981](https://github.com/rust-lang/crates.io-index/tree/0f21f981c599971052bd855aa0fea6cc3f5e0c23).
INPUTS.json retains selected release fields, exact source Git blobs and
canonical hashes of the complete selected registry rows. Its 18 repository
source texts have independently recomputed Git blob identities. Current
registry-parent requirements come from the repository's locked rules_rs facts.

## Small first transaction: four TLS packages

| Locked package | Target | Original records addressed | Static constraint result |
| --- | --- | --- | --- |
| rustls-webpki 0.103.15 | 0.103.16 | 0382 | All observed current parents admit it |
| webpki-roots 1.0.9 | 1.0.10 | 0381 | Current parents use compatible 1.x requirements |
| webpki-root-certs 1.0.5 | 1.0.10 | 0383 | Current parents use compatible 1.x requirements |
| rustls 0.23.45 | 0.23.46 | 0346, 0347, 0348, 0349 | All observed parents, including pinned Git forks, admit it |

For rustls and rustls-webpki, the selected registry rows change only version,
archive checksum and publication time. Normal dependency requirements remain
unchanged for both root packages too. Their maximum stated minimum Rust version
is 1.71, below the repository's pinned 1.95.0 toolchain.

This supports a focused lock-only candidate. It does **not** prove Cargo can
resolve the entire workspace or that the resulting code compiles. Perform real
updates in the table's order, rereading Cargo.lock before each command. Stop and
report any additional package addition, removal or upgrade; do not silently
accept resolver changes outside the four declared packages.

If these four updates remove exactly the intended records under the same
database and graph, the original set would fall from 22 to **15 records
(9 vulnerability records and 6 unmaintained records)**. That is an unmeasured
expectation, and it would still be a failed advisory gate.

## Remaining changes require separate review

| Family | Records | Concrete boundary |
| --- | ---: | --- |
| Matrix crypto | 1 | The 0.18 SDK/base/indexeddb/local SQLite bounds reject 0.19. Published 0.19.0/0.19.1 requires Rust 1.96, beyond current 1.95. The vendor's rusqlite 0.39 adjustment shares native SQLite with SQLx; upstream 0.19 uses rusqlite 0.40.2 and needs a fresh native-links review. |
| anymap2 | 1 | No patched release. Even Matrix SDK 0.19.1 still uses anymap2. Port the parent to a maintained alternative; the SDK version update alone will not clear this record. |
| basic-toml | 1 | No patched release. Latest i18n-config 0.4.8 still uses it, and newer age/i18n-embed-fl releases still reach that parent. A maintained parent/parser migration is needed. |
| crypto-bigint | 1 | elliptic-curve 0.13 requires bigint 0.5; the patched range starts at 0.7.6. Even aws-config 1.13.0 credentials-login still requires p256 0.13.2. Updating aws-sigv4 alone does not remove this independent path. |
| unsafe-libyaml | 1 | No patched release. Port the actual serde_yaml plugin parser to a maintained implementation and check its semantics. The advisory explicitly says serde_yaml_ng still uses unsafe-libyaml. |
| zbus split types | 3 | keyring 3.6.3 uses secret-service/zbus 4. Names, wire types and derive code moved to zbus 6. Even keyring 4.2.0's published zbus backend still requests zbus 5; a blind keyring major update is not a demonstrated solution. |
| zip | 3 | Workspace zip 2.x excludes patched 9.x. zip 9.0.0 still requests zstd 0.13; published zip 9.1.2 uses zstd 0.14 and is the better combined-migration candidate, subject to real API checks. |
| zstd / zstd-safe | 3 | Workspace zstd 0.13 rejects 0.14.3, and its safe wrapper 7.x rejects 8.2.0. Update the stack and zip together so an old parallel branch does not remain. |
| zstd-sys | 1 | The current parent admits 2.1.2 as a leaf update, but the repository applies a native build.rs patch and injects zstd 1.5.7. Real patch/native validation remains necessary. This advisory concerns wasm32, not proof of a Linux exploit. |

The complete per-family evidence and validation scopes are in
REMEDIATION_PLAN.json. Do not disable credentials-login, persistent desktop
credential backends or compression features to erase the dependency graph.
No advisory ignore or global gate relaxation is proposed.

## Commands for the bounded TLS experiment

These commands are proposed, not executed by this analysis. Run from the
repository root with Rust 1.95.0. The helper should choose each package's actual
current locked version immediately before its update.

```sh
cargo +1.95.0 update --manifest-path codex-rs/Cargo.toml -p rustls-webpki@0.103.15 --precise 0.103.16
cargo +1.95.0 update --manifest-path codex-rs/Cargo.toml -p webpki-roots@1.0.9 --precise 1.0.10
cargo +1.95.0 update --manifest-path codex-rs/Cargo.toml -p webpki-root-certs@1.0.5 --precise 1.0.10
cargo +1.95.0 update --manifest-path codex-rs/Cargo.toml -p rustls@0.23.45 --precise 0.23.46
just bazel-lock-update
bazel mod deps --lockfile_mode=error
cargo +1.95.0 check --manifest-path codex-rs/Cargo.toml --locked --lib -p codex-utils-rustls-provider -p codex-http-client -p codex-websocket-client
cargo-deny --format json --log-level warn --manifest-path codex-rs/Cargo.toml --all-features --locked check advisories --disable-fetch --config codex-rs/deny.toml
```

The pinned cargo-deny action in the original workflow uses **cargo-deny 0.19.0**
and defaults to **--all-features**. A comparable advisory rerun must retain that
graph and the original deny.toml, pin the official database commit above, and
record the real nonzero exit. An advisory-only diagnosis is not a claim that the
original full advisories/bans/licenses/sources workflow passes.

The three selected compiler targets cover the actual Rustls provider,
HTTP client and WebSocket client. They use native trust roots, so this check
does not guarantee either root-store crate was compiled, and it does not test a
live TLS handshake. Record the resolved dependency graph and actual coverage.
Save complete command logs, pre/post locks, package-level differences, and
policy identities. Include a successful real MODULE.bazel.lock refresh in any
eventual dependency commit; never synthesize that lock by hand.
