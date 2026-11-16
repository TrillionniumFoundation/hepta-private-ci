# Exact historical evidence size exceptions

This review retains 22 original blobs from `ca1ae598efb77b552df3897b8debc0441bc7bd90`. GitHub Actions run 43822682848, job 133149163164, rejected these blobs above the existing 512000-byte limit. No original evidence, source status, size threshold or general path exception is changed.

The append file adds only `sha256:<digest> PATH` entries, using the repository's existing exact-content mechanism. It does not replace the allowlist or its other entries. In particular, the separate CALLERS.toml pin remains owned by the caller-proof review.

## Byte custody and interpretation

All 22 paths, Git blob IDs, sizes and SHA256 digests were checked against the retained original objects: 16910010 bytes total. Fifteen NPZ archives passed every ZIP CRC and safe NPY header/shape/dtype/payload-size check; no object dtype or pickle was loaded. Four JSON files parsed without rewriting their bytes. The cell validation tar.xz retained 112 exact file hashes totaling 19607272 uncompressed bytes. The second-cycle three-part archive retained its 1211050-byte aggregate hash and all ten original member hashes; only its two oversized parts need an exception.

The receipt identifies each original status source. Scientific HOLD_NO_GO, incomplete qualification and all_closed=false remain as recorded. Archive and array integrity do not establish scientific correctness, provider qualification, model adoption or a new successful run. Archive entries were read and hashed without filesystem extraction or execution.

## Policy verification

The unchanged checker and its unchanged ten tests were used. In an isolated repository, all 22 original blobs are rejected by the original allowlist, accepted by the exact additions, and rejected again after appending one byte to each blob. Both expected-negative outputs remain alongside the positive output. No production test was disabled, baseline broadened or assertion reduced.

`verification-script.py` is the exact one-time custody inspection used to create the receipt. Its staging directory contains `original-blob-records.json` (named `blob-policy-records.json` during execution), `blobs/<Git SHA>` copied from Git objects, and `custody-source/<repository path>` copied from the recorded original source commit. The third small second-cycle part is required for aggregate verification but receives no additional allowlist entry. The inputs are not extracted or executed.

The raw cell archive was recovered into a new isolated bare object store with one explicit blob want, using the existing repository transport: `git fetch --no-tags --no-write-fetch-head --filter=blob:none <existing-origin> adf445673f809c8b043dc8c54c08383ce9e3325e`. The resulting object files total 1390600 bytes. No ancestor commit pack or remote ref mutation was requested.
