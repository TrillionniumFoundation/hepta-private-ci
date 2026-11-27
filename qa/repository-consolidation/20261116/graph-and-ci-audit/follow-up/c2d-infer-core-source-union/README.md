# Inference core source union evidence

This package preserves the original inputs, source proposal, commands, logs, and results for the reviewed inference core union.

The final original package run passed 78 tests. 4 original tests remained skipped. The original format command, explicit format check, and scoped Clippy command also passed. All 13,692 frozen inputs were unchanged at every final stage.

The old implementation failed the real callback panic regression. A separate earlier Clippy run changed two equivalent nested conditions, so that attempt stopped at its input custody check. Both earlier outcomes remain preserved.

The tested dependency closure matches commit 4a5630661b1fee17582b452520c32fb5805831aa for inference core, shared types, all workspace manifests, local patches, and the listed controls. Other copied historical workspace files are outside this qualification. This evidence does not qualify the entire commit or the entire incoming branch family.

Every carrier is an independent gzip file. Decompress the carriers in the order recorded in manifest.json.gz, concatenate their raw bytes, and read the resulting tar archive. The manifest records every original length and SHA256, the complete tar SHA256, and each carrier's compressed and raw SHA256. Restoration was checked against every original byte.

The original timeout, stack size, default features, four test threads, and zero retries were retained. The final source plan and native receipts inside the archive state the exact scope and source hashes.
