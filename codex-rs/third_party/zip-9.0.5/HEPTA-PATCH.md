# ZIP 9.0.5 native BZip2 feature backport

The upstream MIT release by zip-rs is preserved in UPSTREAM.crate. Its SHA-256 is 6e04976da629d3b04204ba8105b396a193af8ad2583b2c79bfb3ab8af580a11e. The embedded VCS record identifies zip-rs/zip2 commit 0123ed144cfa7d672dae78b79a034d8900f9aaeb. The 47 files under src, LICENSE, README.md, Cargo.toml.orig and the VCS record match the archived release byte for byte.

The normalized Cargo.toml inserts one question mark in the bzip2-rs feature dependency, yielding bzip2?/bzip2-sys. The same feature already activates dep:bzip2 explicitly. The weak reference enables the C backend without implicitly enabling zip's same-named bzip2 feature and its additional Rust backend. All upstream ZIP implementation code remains identical. Cargo.toml.orig records the upstream pre-normalization manifest.

The plugin retains its earlier archive method set. The workspace pins ctutils 0.4.4 for the updated AES dependency chain. To retire this local patch, test a fixed official release for the same feature resolution, license inventory and ordinary archive compatibility, then remove the workspace path patch and regenerate both locks.

Upstream release: https://static.crates.io/crates/zip/zip-9.0.5.crate
