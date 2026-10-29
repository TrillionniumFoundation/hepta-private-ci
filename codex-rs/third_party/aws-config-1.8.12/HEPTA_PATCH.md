# Hepta compatibility patch for aws-config-1.8.12

This is a modified copy of the official upstream crate. Update the credentials-login P-256 implementation to 0.14 and its compatible random-number API. Use ToSec1Point for the same uncompressed JWK coordinates. The AWS provider configuration API, login support and signature protocol are retained.

Upstream archive: https://static.crates.io/crates/aws-config/aws-config-1.8.12.crate

Archive SHA-256: `96571e6996817bf3d58f6b569e4b9fd2e9d2fcf9f7424eed07b2ce9bb87535e5`. The archive was checked against the official crates.io checksum before extraction. Upstream license files and all upstream source files are retained.

`HEPTA_COMPATIBILITY.patch` records every changed upstream line. `HEPTA_UPSTREAM_PROVENANCE.json` records the original file identities; `HEPTA_PATCH_PROVENANCE.json` records the retained identities. The repository verifier reverses the patch and checks the original hashes.

Remove this local compatibility patch when a supported upstream release provides the corresponding maintained dependency and satisfies the workspace compatibility constraints. Do not reformat unchanged upstream sources.
