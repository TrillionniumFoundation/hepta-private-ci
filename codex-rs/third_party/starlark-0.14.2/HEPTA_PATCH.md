# Hepta compatibility patch for starlark-0.14.2

This is a modified copy of the official upstream crate. Advance the exact BLAKE3 pin from 1.8.2 to 1.8.7, satisfying the fixed Matrix release without replacing the Starlark language or policy APIs.

Upstream archive: https://static.crates.io/crates/starlark/starlark-0.14.2.crate

Archive SHA-256: `9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`. The archive was checked against the official crates.io checksum before extraction. Upstream license files and all upstream source files are retained.

`HEPTA_COMPATIBILITY.patch` records every changed upstream line. `HEPTA_UPSTREAM_PROVENANCE.json` records the original file identities; `HEPTA_PATCH_PROVENANCE.json` records the retained identities. The repository verifier reverses the patch and checks the original hashes.

Remove this local compatibility patch when a supported upstream release provides the corresponding maintained dependency and satisfies the workspace compatibility constraints. Do not reformat unchanged upstream sources.
