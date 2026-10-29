# Hepta compatibility patch for matrix-sdk-sqlite-0.19.1

This is a modified copy of the official upstream crate. Keep rusqlite 0.39 so Matrix and SQLx 0.9 use the same fixed libsqlite3-sys 0.37 native SQLite owner. The rest of this package is the fixed upstream Matrix 0.19.1 release.

Upstream archive: https://static.crates.io/crates/matrix-sdk-sqlite/matrix-sdk-sqlite-0.19.1.crate

Archive SHA-256: `8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`. The archive was checked against the official crates.io checksum before extraction. Upstream license files and all upstream source files are retained.

`HEPTA_COMPATIBILITY.patch` records every changed upstream line. `HEPTA_UPSTREAM_PROVENANCE.json` records the original file identities; `HEPTA_PATCH_PROVENANCE.json` records the retained identities. The repository verifier reverses the patch and checks the original hashes.

Remove this local compatibility patch when a supported upstream release provides the corresponding maintained dependency and satisfies the workspace compatibility constraints. Do not reformat unchanged upstream sources.
