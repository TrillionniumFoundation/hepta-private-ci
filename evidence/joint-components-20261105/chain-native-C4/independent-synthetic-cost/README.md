# Independent C4 Sparse accounting

The full result and review are in `independent-sparse-recomputation.json` and `independent-sparse-review.md`. These recompute the actual C4 raw record arithmetic; they do not rerun native work or independently certify clock truth. `root-review.json` records a separate root recomputation of all 270 class/arm CPU and wall aggregates.

## Reproduce from retained bytes

1. In `../complete-raw/`, read `C4-synthetic-delivery.json`. Concatenate only its declared parts in ascending index, checking each byte count, offset and SHA-256. Check the resulting archive is exactly 7915876 bytes with SHA-256 `5e8d57f85c506e797a75fb46c46603fce18d00e7572aa10689db59f1ce4d7451`.
2. Inspect the tar members and match the retained export index and `root-synthetic-archive-review.json`. Extract the verified regular files into a fresh directory named `extracted` in a new scratch review folder. The resulting raw directory must be `extracted/synthetic-census-two-child`. Do not overwrite an existing result or follow archive links.
3. Copy `recompute_sparse.py` into that fresh review folder and run it with Python 3. Its paths are relative to its own location. It deliberately uses exclusive creation for its output, so rerunning in the deliverable directory with existing outputs is not supported.
4. Compare the newly produced JSON bytes/hash and cost table against the preserved result and review. Original absolute desktop/workspace provenance paths are retained as history; they are not required to be live in the review environment.

The 18-row cost table includes per-epoch setup, all 512 attempts per class/target/arm across eight samples, cleanup and teardown. Material creation/eligibility, verification and audit costs remain separately reported. The two target streams share challenge material and cannot be summed into independent work. Eight rotations do not balance all fifteen positions. The frozen calibration/evaluation selection is not replaced by the retrospectively cheapest arm.
