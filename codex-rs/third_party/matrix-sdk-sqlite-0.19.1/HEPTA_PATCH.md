# Matrix SDK SQLite compatibility patch

Source: crates.io `matrix-sdk-sqlite 0.19.1`, SHA-256
`8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`.

The upstream Rust semantics and SQL migration bytes are unchanged. Rust files
are mechanically normalized by the repository's `just fmt` policy; the
source-normalization receipt verifies them against independently formatted
upstream originals. Both Cargo
manifests advance `rusqlite` from 0.40.2 to 0.41.1, retaining its explicit
`limits`, `fallible_uint`, and `cache` features. This keeps one native SQLite
library shared with SQLx 0.9.1, using fixed `libsqlite3-sys 0.39.1`.

`BUILD.bazel` includes the actual upstream SQL migration files. The upstream
Rust 1.96 minimum is preserved. Existing store directories are retained;
the SDK's own versioned migrations, rather than a new directory, upgrade
old data. Actual consumer and migration tests are required before deployment.
