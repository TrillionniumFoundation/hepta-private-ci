# Starlark BLAKE3 patch alignment

This is the official Starlark 0.14.2 crate. Only the normalized Cargo manifest's
exact BLAKE3 pin changes, from 1.8.2 to 1.8.7, which the maintained Matrix store
encryption release requires. The original manifest retains its upstream inherited
workspace declaration. No interpreter implementation or execution policy changes.

All 685 official files are retained. Repository formatting differences are
separately verified against an identical formatter replay. The functional patch,
complete member provenance, and official archive identity live under
`qualification/matrix-sdk-019-current/`. The existing execution-policy tests and
BLAKE3 known-answer regression must pass on this candidate before admission.
