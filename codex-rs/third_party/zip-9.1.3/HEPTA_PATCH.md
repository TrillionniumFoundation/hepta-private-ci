# ZIP 9.1.3 feature repair

Source: the unmodified registry archive
<https://static.crates.io/crates/zip/zip-9.1.3.crate>, verified against the official
Cargo registry index checksum
`1156b39d142a34b999c2310a50455e0cb3760bf7efad0122f796d813bee26ccb`.
Upstream commit: `af2ed2a3e12af1fdd733b1886b3e9067bf510be5`.
The original MIT license and all 66 registry files are retained.

The only dependency behavior changes are one character in each of `Cargo.toml` and
`Cargo.toml.orig`: the `bzip2-rs` feature forwards `bzip2?/bzip2-sys` instead of
`bzip2/bzip2-sys`. The feature already explicitly activates `dep:bzip2`.
The strong forwarding form additionally enables the same-named local `bzip2`
feature, which enables the dependency's default Rust backend. The weak form
selects the intended existing C backend without that unintended local feature.
A real offline Cargo resolution of the minimal reproducer confirmed both paths.
See <https://doc.rust-lang.org/cargo/reference/features.html#dependency-features>.

The repository-required `just fmt` also mechanically formatted 37 upstream Rust
files. `HEPTA_FORMATTING.json` records the exact before/after hashes, sizes and
formatter. No Rust behavior, extraction policy, codec, archive format,
cryptographic behavior, or cargo-deny rule is changed by this local patch. The workspace preserves AES,
bzip2, deflate, deflate64, LZMA, PPMd, time, XZ and Zstandard support. The upstream
9.1.3 release also contains its published extraction and cryptographic fixes:
<https://github.com/zip-rs/zip2/releases/tag/v9.1.3>.

`BUILD.bazel` provides a production library with the same resolved features and
the upstream README needed by `include_str!`. It does not invent upstream test
resources omitted from the published crate. The existing first-party ZIP
compatibility tests and unchanged full cargo-deny policy still must execute.
The immutable candidate recipe inventories every file and requires regenerated
Cargo and Bazel locks before qualification or integration.
