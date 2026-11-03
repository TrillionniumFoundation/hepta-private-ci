# Retained unsuccessful native formal-06 attempt

This directory preserves evidence from [GitHub Actions run 40683606875](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40683606875).
The completed run concluded **failure**. Its original native CI receipt remains
unsuccessful; this evidence is **not finalization authority**. Successful byte
transport checks do not change the execution or scientific results.

All 51 original regular files other than `artifact.zip` are copied from
`/workspace/scratch/76e2020e4b36/native-ci-artifacts/formal-06` with their relative paths and bytes unchanged. The source directory,
including the original ZIP, is retained. `RETENTION.json` states this scope;
`COPY_VERIFICATION.json` separately records source and destination byte counts
and SHA-256 identities for every copied file.

The original ZIP (7,847,958 bytes, SHA-256
`056119f58b0998ca1684ed2b56b0425becbf5aca4668b2848506cbcb57d2b4fc`) is retained at
`/workspace/scratch/76e2020e4b36/native-ci-artifacts/formal-06/artifact.zip`. It is not copied into Git. Its observed size and digest
match the retained GitHub artifact metadata and `DOWNLOAD.json`; no signed
download URL is retained.

`TRANSPORT.json`, `INDEX.json`, `receipt.json`, and the 27
ordered files under `chunks/` retain the original 7,805,148-byte
`memory-v9-evidence.tar.xz` without recompression. Concatenating chunks in manifest
offset order reconstructs that archive exactly; its SHA-256 is
`4afac9351c3af2b85dcb57c37e42895a211a9c91d353d0f048518f741d48b8b8`. The unchanged `INTEGRITY.json` records the previous full
archive verification of 487 ordinary raw files.
The copy operation verifies all copied byte identities and the concatenated
archive identity; it does not rerun the native tests, model inference or scoring.

`LOCAL_FILES.json` remains the original local acquisition inventory, including
`artifact.zip`, which is intentionally absent from this repository directory.
It must not be interpreted as a repository publication inventory. Other original
JSON files, logs, diagnostics and binary parts are preserved unchanged, including
all failure flags and missing-report records. The three new publication files
are `RETENTION.json`, this README, and `COPY_VERIFICATION.json`.
