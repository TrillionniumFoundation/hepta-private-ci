# Retained unsuccessful native formal-05 attempt

This directory preserves evidence from [GitHub Actions run 40675343830](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40675343830).
The completed run concluded **failure**. Its original native CI receipt remains
unsuccessful; this evidence is **not finalization authority**. Successful byte
transport checks do not change the execution or scientific results.

All 52 original regular files other than `artifact.zip` are copied from
`/workspace/scratch/76e2020e4b36/native-ci-artifacts/formal-05` with their relative paths and bytes unchanged. The source directory,
including the original ZIP, is retained. `RETENTION.json` states this scope;
`COPY_VERIFICATION.json` separately records source and destination byte counts
and SHA-256 identities for every copied file.

The original ZIP (9,812,062 bytes, SHA-256
`e1c03b906df23f52d7088a0c471f0d594fddc3976a569ab47b3ff0b7e43cba12`) is retained at
`/workspace/scratch/76e2020e4b36/native-ci-artifacts/formal-05/artifact.zip`. It is not copied into Git. Its observed size and digest
match the retained GitHub artifact metadata and `DOWNLOAD.json`; no signed
download URL is retained.

`TRANSPORT.json`, `INDEX.json`, `receipt.json`, and the 33
ordered files under `chunks/` retain the original 9,770,832-byte
`memory-v9-evidence.tar.xz` without recompression. Concatenating chunks in manifest
offset order reconstructs that archive exactly; its SHA-256 is
`64b08e784c8261a6e2a05a61e860fa8da1fe0a877d5fc5cb7027509b9ac2c460`. The unchanged `INTEGRITY.json` records the previous full
archive verification of 467 ordinary raw files.
The copy operation verifies all copied byte identities and the concatenated
archive identity; it does not rerun the native tests, model inference or scoring.

`LOCAL_FILES.json` remains the original local acquisition inventory, including
`artifact.zip`, which is intentionally absent from this repository directory.
It must not be interpreted as a repository publication inventory. Other original
JSON files, logs, diagnostics and binary parts are preserved unchanged, including
all failure flags and missing-report records. The three new publication files
are `RETENTION.json`, this README, and `COPY_VERIFICATION.json`.
