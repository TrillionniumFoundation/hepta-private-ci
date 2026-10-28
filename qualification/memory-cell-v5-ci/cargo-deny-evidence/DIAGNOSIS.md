# cargo-deny failure diagnosis

The original PR job failed the advisory check: 16 vulnerability errors and 6 unmaintained errors. Bans, licenses and sources passed. The 22 error records are 22 distinct RustSec IDs affecting 16 distinct crate versions; repeated crates are rustls (4), zip (3) and zstd-safe (2).

The PR head, base and actually tested merge have identical Git blob IDs for Cargo.lock, the workspace Cargo.toml, deny.toml and the cargo-deny workflow. These are existing baseline dependency declarations and locked versions, not versions introduced by V5. This attribution does not waive the failed security check. The separate same-checksum Ubuntu zlib download recovery does not address any of these advisories.

## Run and integrity

- Original run: [40470653139](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40470653139/job/122077331825); job 122077331825.
- Head: `332d8156d081e22405450dd607023689f68f03e1`; tested merge: `bbe36d7c618860cd06da120469c15547aaca4a94`; base: `f8c9419df6ddeb36ff8b522a50219981fb8d9345`.
- Read-only collector: run 40473598340 / job 122086309675; source `ccdb7ea7cb9c4adecf6f6607ea1570cb81ae0f78`.
- ZIP: 1,567,767 bytes; SHA256 `c541979c81096ac2cf4effe9fb122bdc5bef282b008f266f636214a471ea964c`.
- Raw log: 19,295,233 bytes, 170,046 lines; SHA256 `6e331a7e7ee4fb769e2b70679eee407752fbca22cd98c736575c3bd26bd686f8`.
- Terminal result at raw log line 169986: `advisories FAILED, bans ok, licenses ok, sources ok`.

## All 22 errors

Every CI-reported patched range below now matches an independently parsed original RustSec advisory at pinned database commit `3279c99911354c400e1d41e47c7d60e39258b147`. All 22 source files have verified SHA256 and Git blob IDs; none has a withdrawn marker. These ranges do not establish a compatible Cargo solution or a tested upgrade. Six maintenance notices have `patched=[]`; this means the advisory records no patched release, not that replacing or migrating the dependency is impossible. Official `unaffected` ranges and architecture/function qualifiers are retained in DIAGNOSIS.json.

The 22 RustSec IDs are distinct, but `RUSTSEC-2026-0381`, `0382` and `0383` share alias `CVE-2026-111943`. Therefore the count is advisory records, not independent exploits. In particular `RUSTSEC-2026-0410` explicitly lists `wasm32`; the all-features Cargo check is not a runtime-exploitability assessment. Chains are the first displayed inverse-dependency path to a `codex-*` crate; `[dev]` identifies a development dependency. Other paths can exist, and cargo-deny's `(*)` notation omits repeated subtrees.

| RustSec ID | Installed crate | Official patched range, matched to CI | First displayed path to repository | Raw log line |
| --- | --- | --- | --- | --- |
| [RUSTSEC-2026-0319](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/anymap2/RUSTSEC-2026-0319.md) | anymap2 0.13.0 | No patched range recorded | anymap2 0.13.0 → matrix-sdk 0.18.0 → codex-hepta-matrix-sdk 0.0.0 | 155473 |
| [RUSTSEC-2026-0374](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/basic-toml/RUSTSEC-2026-0374.md) | basic-toml 0.1.10 | No patched range recorded | basic-toml 0.1.10 → i18n-config 0.4.8 → i18n-embed-fl 0.9.4 → age 0.11.2 → codex-secrets 0.0.0 | 155490 |
| [RUSTSEC-2026-0387](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/crypto-bigint/RUSTSEC-2026-0387.md) | crypto-bigint 0.5.5 | >=0.7.6 | crypto-bigint 0.5.5 → elliptic-curve 0.13.8 → ecdsa 0.16.9 → p256 0.13.2 → aws-config 1.8.12 → codex-aws-auth 0.0.0 | 155868 |
| [RUSTSEC-2026-0318](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/matrix-sdk-crypto/RUSTSEC-2026-0318.md) | matrix-sdk-crypto 0.18.0 | >=0.19.0 | matrix-sdk-crypto 0.18.0 → matrix-sdk-base 0.18.0 → matrix-sdk 0.18.0 → codex-hepta-matrix-sdk 0.0.0 | 156238 |
| [RUSTSEC-2026-0346](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/rustls/RUSTSEC-2026-0346.md) | rustls 0.23.45 | >=0.23.46 | rustls 0.23.45 → codex-exec-server 0.0.0 [dev] | 156261 |
| [RUSTSEC-2026-0347](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/rustls/RUSTSEC-2026-0347.md) | rustls 0.23.45 | >=0.23.46 | rustls 0.23.45 → codex-exec-server 0.0.0 [dev] | 157159 |
| [RUSTSEC-2026-0348](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/rustls/RUSTSEC-2026-0348.md) | rustls 0.23.45 | >=0.23.46 | rustls 0.23.45 → codex-exec-server 0.0.0 [dev] | 158071 |
| [RUSTSEC-2026-0349](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/rustls/RUSTSEC-2026-0349.md) | rustls 0.23.45 | >=0.23.46 | rustls 0.23.45 → codex-exec-server 0.0.0 [dev] | 158970 |
| [RUSTSEC-2026-0382](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/rustls-webpki/RUSTSEC-2026-0382.md) | rustls-webpki 0.103.15 | >=0.103.16, <0.104.0-alpha.1 OR >=0.104.0-alpha.8 | rustls-webpki 0.103.15 → rustls 0.23.45 → codex-exec-server 0.0.0 [dev] | 159883 |
| [RUSTSEC-2024-0449](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/unsafe-libyaml/RUSTSEC-2024-0449.md) | unsafe-libyaml 0.2.11 | No patched range recorded | unsafe-libyaml 0.2.11 → serde_yaml 0.9.34+deprecated → codex-core-plugins 0.0.0 | 160777 |
| [RUSTSEC-2026-0383](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/webpki-root-certs/RUSTSEC-2026-0383.md) | webpki-root-certs 1.0.5 | >=1.0.10 | webpki-root-certs 1.0.5 → rustls-platform-verifier 0.7.0 → reqwest 0.13.4 → matrix-sdk 0.18.0 → codex-hepta-matrix-sdk 0.0.0 | 161136 |
| [RUSTSEC-2026-0381](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/webpki-roots/RUSTSEC-2026-0381.md) | webpki-roots 1.0.9 | >=1.0.10 | webpki-roots 1.0.9 → hyper-rustls 0.27.7 → reqwest 0.12.28 → codex-code-mode 0.0.0 | 161528 |
| [RUSTSEC-2026-0371](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zbus_names/RUSTSEC-2026-0371.md) | zbus_names 3.0.0 | No patched range recorded | zbus_names 3.0.0 → zbus 4.4.0 → keyring 3.6.3 → codex-keyring-store 0.0.0 | 162366 |
| [RUSTSEC-2026-0367](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zip/RUSTSEC-2026-0367.md) | zip 2.4.2 | >=9.0.0 | zip 2.4.2 → codex-core-plugins 0.0.0 | 162747 |
| [RUSTSEC-2026-0368](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zip/RUSTSEC-2026-0368.md) | zip 2.4.2 | >=9.0.0 | zip 2.4.2 → codex-core-plugins 0.0.0 | 163086 |
| [RUSTSEC-2026-0369](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zip/RUSTSEC-2026-0369.md) | zip 2.4.2 | >=9.0.0 | zip 2.4.2 → codex-core-plugins 0.0.0 | 163425 |
| [RUSTSEC-2026-0391](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zstd/RUSTSEC-2026-0391.md) | zstd 0.13.3 | >=0.14.3 | zstd 0.13.3 → codex-app-server-protocol 0.0.0 | 163764 |
| [RUSTSEC-2026-0398](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zstd-safe/RUSTSEC-2026-0398.md) | zstd-safe 7.2.4 | >=8.2.0 | zstd-safe 7.2.4 → zstd 0.13.3 → codex-app-server-protocol 0.0.0 | 164554 |
| [RUSTSEC-2026-0403](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zstd-safe/RUSTSEC-2026-0403.md) | zstd-safe 7.2.4 | >=8.2.0 | zstd-safe 7.2.4 → zstd 0.13.3 → codex-app-server-protocol 0.0.0 | 165342 |
| [RUSTSEC-2026-0410](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zstd-sys/RUSTSEC-2026-0410.md) | zstd-sys 2.0.16+zstd.1.5.7 | >=2.1.2 | zstd-sys 2.0.16+zstd.1.5.7 → zstd-safe 7.2.4 → zstd 0.13.3 → codex-app-server-protocol 0.0.0 | 166138 |
| [RUSTSEC-2026-0370](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zvariant/RUSTSEC-2026-0370.md) | zvariant 4.2.0 | No patched range recorded | zvariant 4.2.0 → zbus 4.4.0 → keyring 3.6.3 → codex-keyring-store 0.0.0 | 166928 |
| [RUSTSEC-2026-0372](https://github.com/rustsec/advisory-db/blob/3279c99911354c400e1d41e47c7d60e39258b147/crates/zvariant_derive/RUSTSEC-2026-0372.md) | zvariant_derive 4.2.0 | No patched range recorded | zvariant_derive 4.2.0 → zvariant 4.2.0 → zbus 4.4.0 → keyring 3.6.3 → codex-keyring-store 0.0.0 | 167311 |

## Identical source objects

| File | Git blob ID, equal in head/base/tested merge |
| --- | --- |
| `codex-rs/Cargo.lock` | `8a9eab30d8957daab7dd027e86e88ca792e04a1c` |
| `codex-rs/Cargo.toml` | `d2703b590935ab17316e6c258657c0ce5ab7412a` |
| `codex-rs/deny.toml` | `677f941360b2d82ab96aa4d419d97f4616cc2194` |
| `.github/workflows/cargo-deny.yml` | `0b93acf955da200d7728b9a9e47b6118293701ab` |

The complete machine-readable evidence is in DIAGNOSIS.json and SOURCE_IDENTITIES.json. No dependency, lockfile or advisory-ignore policy was changed, and no CI job was rerun during diagnosis.
