# ZIP 9.0.0 backend compatibility patch

Source: the official `zip 9.0.0` crates.io release, archive SHA-256
`711e8c9646791c49b7eb799a19c4ae70a9b8372ddc6a1fa4778defd1e2aa5d5e`.
The complete MIT license and all published Rust sources are retained. The
upstream standalone lock is omitted; the product Cargo lock resolves the
actual dependencies.

Both published manifests change only the `bzip2-rs` feature forwarding from
`bzip2/bzip2-sys` to `bzip2?/bzip2-sys`. The preceding `dep:bzip2` already
activates the optional dependency. Weak forwarding selects the existing C
backend without also activating ZIP's identically named `bzip2` feature,
which selects the separate default Rust backend. No Rust source is changed.

The product explicitly enables ZIP's full default compression and AES
capabilities, substituting this C backend for the default bzip2 backend.
The crate is a dependency, excluded from product workspace membership;
product `--all-features` checks still cover all first-party features. No
license allowlist or advisory ignore is changed. Remove this patch when a
compatible upstream release makes the native backend independently selectable.

Sources:

- https://crates.io/crates/zip/9.0.0
- https://doc.rust-lang.org/cargo/reference/features.html#dependency-features

Bazel materializes this Cargo patch dependency through `@crates`; the repository
intentionally excludes local `codex-rs/third_party` BUILD packages. The generated
crate target uses the feature set resolved from the product Cargo manifest.
