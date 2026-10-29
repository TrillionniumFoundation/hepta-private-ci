# Hepta compatibility patch for i18n-config-0.4.8

This is a modified copy of the official upstream crate. Replace the unmaintained basic-toml dependency with the maintained toml parser. Keep the age encryption format and the existing internationalization configuration structures.

Upstream archive: https://static.crates.io/crates/i18n-config/i18n-config-0.4.8.crate

Archive SHA-256: `3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`. The archive was checked against the official crates.io checksum before extraction. Upstream license files and all upstream source files are retained.

`HEPTA_COMPATIBILITY.patch` records every changed upstream line. `HEPTA_UPSTREAM_PROVENANCE.json` records the original file identities; `HEPTA_PATCH_PROVENANCE.json` records the retained identities. The repository verifier reverses the patch and checks the original hashes.

Remove this local compatibility patch when a supported upstream release provides the corresponding maintained dependency and satisfies the workspace compatibility constraints. Do not reformat unchanged upstream sources.
