# Matrix SDK maintained map dependency

Source: crates.io `matrix-sdk 0.19.1`, SHA-256
`2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e`.

The only semantic Rust source change is the Matrix project's own migration from
unmaintained `anymap2` to `anymap3`, upstream commit
[`9c5fdd2cf5be1b7b8b20541e56d7a109db968534`](https://github.com/matrix-org/matrix-rust-sdk/commit/9c5fdd2cf5be1b7b8b20541e56d7a109db968534).
Both Cargo manifests express the same dependency/features as that commit.
All imported Rust files are mechanically normalized by the repository's
`just fmt` policy. The source-normalization receipt reconstructs the official
crate plus this exact patch, applies the same formatter, and verifies every
Rust file byte for byte; the imported files are not claimed to be byte-identical
to their pre-format upstream originals.
`BUILD.bazel` supplies the upstream Markdown files used by compile-time docs.

The upstream Rust 1.96 minimum is preserved. This backport neither suppresses
the advisory nor substitutes a package name while retaining the old map code.

This source update does not rename or reset existing Matrix SDK store paths.
Store migration and cryptographic compatibility must pass the consumer tests
and the pinned dependency/CI checks before deployment.
