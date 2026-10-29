# Hepta compatibility patch for matrix-sdk-0.19.1

This is a modified copy of the official upstream crate. Use the maintained anymap3 successor in place of archived anymap2. Preserve native Send + Sync context storage and the WASM-local context bound through the supported CloneAny trait combinations.

Upstream archive: https://static.crates.io/crates/matrix-sdk/matrix-sdk-0.19.1.crate

Archive SHA-256: `2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e`. The archive was checked against the official crates.io checksum before extraction. Upstream license files and all upstream source files are retained.

`HEPTA_COMPATIBILITY.patch` records every changed upstream line. `HEPTA_UPSTREAM_PROVENANCE.json` records the original file identities; `HEPTA_PATCH_PROVENANCE.json` records the retained identities. The repository verifier reverses the patch and checks the original hashes.

Remove this local compatibility patch when a supported upstream release provides the corresponding maintained dependency and satisfies the workspace compatibility constraints. Do not reformat unchanged upstream sources.
