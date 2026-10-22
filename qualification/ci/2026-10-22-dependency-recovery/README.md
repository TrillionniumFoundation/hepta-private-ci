# Recovered dependency verification

This packet preserves actual executions after workspace maintenance. It does not reconstruct lost pre-maintenance evidence.

The Cargo resolver ran `cargo metadata --all-features --format-version 1` on local source `562ba6b46e24cb4cd2fc4bdd96c0000a7e3754e8`, resolving 193 workspace members and 1,503 packages. Its real lock change adds exactly three dependency edges and changes no package/version/source/checksum records.

Pinned cargo-deny 0.19.0 then ran all four checks with `--all-features --locked` on local source `1ef41d86467474655c3d023f7d90eaee1f7a7871`. Advisories, bans, licenses and sources all passed. Policy and ignores were unchanged. The fresh RustSec database was `4b587f00996ebe5c05a73eaef105ef241e876414`.

The remote source commit `45901e2137e1693d441c548769ef68457aa914fb` preserves the exact tested local tree `4f0652bdd530b9c0b41a692a41d94e70194d2f9c`. Its commit IDs differ because publication recreated commit metadata; the original ordered source parents and each intermediate tree were verified independently. The two-parent source baseline preserves both b841aaf175ce6a1d06524e6a2c19f7cab6a26c3b and d50f043a5017ff1315e8d40669c535fe89eb65bd.

The 811,596-byte archive contains 21 regular files, including complete Cargo metadata, the complete 12,842,515-byte cargo-deny log, source conservation decisions, tool/DB identities and execution receipts. Its SHA-256 is `7c2241dd799598231c83e8aa6341b7d0226ef6ca26dea3121fc4956946be6db1`. The enclosed evidence-manifest-1ef4.json records every other member's exact byte count and SHA-256. Root rechecked all members, the metadata denominators and the original deny conclusion before publication.

Bazel lock regeneration, native platform gates, the Windows deletion boundary and later source changes require separate results. This packet supplies no native or release qualification. Original logs and actual timestamps are retained in the archive.
