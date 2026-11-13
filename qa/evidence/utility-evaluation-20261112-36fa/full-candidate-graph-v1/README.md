# Complete mode-aware candidate graph — prepared only

The independently reconstructed canonical tree is exactly `b7b357c07b5539769a068c6b9b009629f5612d1e`. Applying the frozen 110-path overlay produces expected tree **`4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09`**. Both roots, counts, modes and update counts match Root's separate actual Git index/write-tree review.

This preparer does not create source tree or commit objects, move refs, run H, format, compile, execute QA or materialize a complete working source repository. The new root is an expected graph, not a native qualification result. The published source baseline is `cc57c7198db6293ccca562253c42fffbe2a04633`; useful real task-chain results remain 0 / Unknown.

## Exact recovery source

The canonical inventory was reused from `/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json`. Its complete 5,611,184 bytes match SHA-256 `13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9` and Git blob identity `7f94788b70546a8b8030dfd2b9182a7d9287c537`.

The five existing published base64 parts were all rechecked locally against their fixed size/SHA/Git identities and their retained original full Git GET SDK contents. Their decoded offsets and chunk hashes reconstruct the exact original gzip and raw inventory. No part was downloaded again and no new native inventory read is claimed. `INPUT_RECOVERY_PROOF.json` records the full chain.

The applied overlay is fixed map `148e9efc242f3ee3ee4e525281ec170feecf3f19`. Every covered source file was read in full from its isolated directory and checked against the map; every original blob and existing mode also matched the canonical inventory before applying the update. The prior complete Git content availability record for all 110 overlay blobs is `106e4ed2e978b7eb2fb39696678c675a74a0f62e`.

## Complete expected counts

| Measure | Canonical cc57 | Candidate |
|---|---:|---:|
| File paths, including symlink | 15,188 | 15,237 |
| All repository `.rs` paths | 6,741 | 6,788 |
| `.rs` paths under `codex-rs/` | 6,619 | 6,666 |
| `.rs` paths outside `codex-rs/` | 122 | 122 |
| Git mode `100644` | 15,097 | 15,146 |
| Git mode `100755` | 90 | 90 |
| Git mode `120000` | 1 | 1 |
| Directory paths | 1,849 | 1,849 |

There are **109 actual updates: 49 new paths and 60 modified paths**. One covered Rust file already equals its canonical original and needs no update. There are no canonical deletions. All executable and symlink rows retain their complete path/mode/blob/size/SHA identities.

The old candidate-only helper name remains absent from both full graphs. Its historical removal is not a deletion from cc57; no `sha:null` update is generated. The complete-tree counts here supersede any earlier conditional arithmetic for planning, but they remain expected counts until actual isolated materialization verifies them.

## Git tree construction

`derive_graph.py` uses every canonical leaf, preserves `100644`, `100755` and `120000`, sorts immediate children using Git's filename ordering with the directory `/` suffix, serializes raw tree entries, and hashes `tree <length>\0<body>` bottom-up. The canonical root is independently pinned before applying the overlay.

Exactly ten directory trees change. `TREE_OBJECT_PLAN.json` provides them in bottom-up order, with full immediate API entries, expected tree SHA, raw-byte SHA-256 and complete raw body as base64. `EXACT_UPDATE_ENTRIES.json` provides the 109 exact root-relative blob update entries, complete before/after identities, empty deletion list and the one unchanged covered path. `BLOB_REUSE_PLAN.json` identifies the existing immutable source blobs to reuse. These are plans for Root; they have not been submitted as source-object creation calls by this preparer.

`CANDIDATE_FILE_GRAPH.json` is the complete path/mode/blob/bytes/SHA graph. `TREE_IDENTITIES.json` contains every before/after directory identity. Both are preserved losslessly through the gzip/base64 parts listed in `ENCODING_MANIFEST.json`. A computed raw or gzip blob identity in that manifest does not claim that the raw body was separately uploaded as a standalone Git blob. The full base graph is deterministic from the already-published canonical inventory; it was not redundantly uploaded.

## Retained local Git probe failure and independent check

An optional local `git hash-object -t tree --stdin` call outside a repository exited with **-11**, with empty stdout and stderr, while hashing the 2,155-byte canonical root body already reproduced as exact B7 by Python. The original probe scripts and `STRICT_GIT_HASH_DIAGNOSTIC.json` are retained. This is a local tool failure, not a Rust, H or candidate-test result; no cause is asserted and no success is substituted for it.

Root independently completed Git `update-index --index-info` and `write-tree --missing-ok` in its own fresh bare store with separate indices. This preparer read that fixed review and compared both roots, all counts, modes and update count exactly. `GIT_HASH_CROSSCHECK.json` distinguishes the failed optional local probe from Root's successful independent Git result. No further probe or source gate was run here.

The 5,128-path evidence cut and all original source/evidence refs remain outside this preparation and were not modified.
