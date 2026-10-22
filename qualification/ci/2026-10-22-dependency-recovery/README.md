# Recovered dependency verification

This packet preserves actual executions after workspace maintenance. It does not reconstruct lost pre-maintenance evidence.

The Cargo resolver ran `cargo metadata --all-features --format-version 1` on local source `562ba6b46e24cb4cd2fc4bdd96c0000a7e3754e8`, resolving 193 workspace members and 1,503 packages. Its real lock change adds exactly three dependency edges and changes no package/version/source/checksum records.

Pinned cargo-deny 0.19.0 then ran all four checks with `--all-features --locked` on local source `1ef41d86467474655c3d023f7d90eaee1f7a7871`. Advisories, bans, licenses and sources all passed. Policy and ignores were unchanged. The fresh RustSec database was `4b587f00996ebe5c05a73eaef105ef241e876414`.

The remote source commit `45901e2137e1693d441c548769ef68457aa914fb` preserves the exact tested local tree `4f0652bdd530b9c0b41a692a41d94e70194d2f9c`. Its commit IDs differ because publication recreated commit metadata; the original ordered source parents and each intermediate tree were verified independently. The two-parent source baseline preserves both b841aaf175ce6a1d06524e6a2c19f7cab6a26c3b and d50f043a5017ff1315e8d40669c535fe89eb65bd.

The 811,596-byte archive contains 21 regular files, including complete Cargo metadata, the complete 12,842,515-byte cargo-deny log, source conservation decisions, tool/DB identities and execution receipts. Its SHA-256 is `7c2241dd799598231c83e8aa6341b7d0226ef6ca26dea3121fc4956946be6db1`. The enclosed evidence-manifest-1ef4.json records every other member's exact byte count and SHA-256. Root rechecked all members, the metadata denominators and the original deny conclusion before publication.

Bazel lock regeneration, native platform gates, the Windows deletion boundary and later source changes require separate results. This packet supplies no native or release qualification. Original logs and actual timestamps are retained in the archive.

## Bazel lock verification (2026-10-22)

The separate `verified-bazel-evidence-a431.tar.xz` packet records the original repository recipes on frozen source `d58e440a336af4a74861e96e06a219b5f973a5cc` (tree `8dac23139d68aff4b229acee567bb95a358e6a8e`), using the repository-pinned Bazel 9.3.0. Two `just bazel-lock-update` executions and two `just bazel-lock-check` executions exited 0. The second generation was byte-identical to the first; both checks kept the lock unchanged. No repository gate settings, Cargo lock, policy, skip conditions or native test requirements were changed.

The generated `MODULE.bazel.lock` has SHA-256 `b8a4a9d6546babb6b5593161f9ab209eee9c572dad46e1a6bf06d57a307e8683`. It is committed locally at `a431b8ecf3372649c8a213af297bbeee2940fd7c`; remote commit `db568358105f62ebfe80b7fd0462534990baf36e` preserves its exact tree `98b97a1a4a96b84eaf96d13b6c16089c9eef9627`.

The generated diff is five changed facts: the vendored i18n TOML dependency now disables default features and selects parse/serde/std; the vendored keyring store selects zbus unixexec/ibus; three registry fact keys now match the rustls-webpki 0.103.16 and webpki-roots/webpki-root-certs 1.0.10 versions already present in the original b841 Cargo lock. The three renamed fact values are byte-identical, 1,555 other common crate facts remain unchanged, and every other top-level lock section remains unchanged. The structured review records each assertion.

The initial attempt failed certificate validation in Bazel's embedded JDK. Its complete failure log is retained. Subsequent executions used the existing system Java trust store through the repository's ignored local runtime configuration; certificate verification remained enabled. The archive contains that configuration and its hash, the system trust-store identity, pinned tool identities, complete logs and receipts for all five attempts, disk samples, and each before/after lock. The idle Bazel server was stopped using the normal shutdown command after verification.

This 304,776-byte archive has SHA-256 `66976dece45427351251c733712fd1a66a20e94692e42a620accbdf860701b3b`. Its 42 regular files include `evidence-manifest-bazel-a431.json`; each other member was checked against the manifest by byte count and SHA-256 before publication preparation. The evidence covers dependency lock generation and checks. It supplies no native compilation, platform test, snapshot, Windows isolation or release qualification, and later source changes still require their own applicable checks.
