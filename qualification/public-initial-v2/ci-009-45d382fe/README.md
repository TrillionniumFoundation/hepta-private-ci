# Lifecycle extraction compile failure

Run [40499847935](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40499847935)
tested source `45d382fe18610ee885c4f36bc73e923c49a913e2`, tree
`932f8442b8f424c7c88f5ecda9f85cfcd0a04474`, with Rust 1.96.0.
The actual CLI and four-package native commands both exited 101: the extracted
drain handle made two fields private while the original options equality code
still compared their four Arc operands at `app-server/src/lib.rs:577-578`.

No native test passed or executed to an observed result. The actual model test
target was unavailable, so cold runtime installation, public material rebuilding,
ordinary inference, repeated proposals and descendant training were all skipped.
Lint failed and the final required-outcomes gate failed. There were zero model
forwards, zero training rounds and zero installed children in this attempt.

GitHub step `conclusion` values for `continue-on-error` steps were displayed as
success despite the underlying command failure. The retained execution receipts
and final required outcomes provide the actual result; step summaries are not a
passing gate. The later two-line `pub(super)` repair preserves the original Arc
identity comparison and is a separate source version requiring its own real CI.

`original-records.zip` is the complete original 31,526-byte artifact, SHA-256
`428200b17d0738f9f087ca18448828880da9333b31e0137f909e60660620b9e6`.
All eleven indexed members and the original index were verified. The compressed
API-decoded job log is supplementary; raw command logs are inside the original
ZIP. This record does not replace the prior f75 model observations or claim a
successful lifecycle repair, installed upgrade or product qualification.
