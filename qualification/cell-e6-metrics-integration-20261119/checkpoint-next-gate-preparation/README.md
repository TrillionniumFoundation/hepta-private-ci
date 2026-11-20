# #6703 exact-object blob gate preparation

This package prepares the original, unchanged 512000-byte Git blob gate for the next checkpoint. It does not claim a passing gate for a new checkpoint. The next complete file manifest, exact new commit and its tree are still owned by the root integration task.

## Fixed baseline

- Base commit: `238fc48402f786db3d7f2a80b0abad6c0e5322bb`.
- Base tree: `74478db5dad451c13483dd575cd5d94c0a3e6864`.
- Original checker blob: `18bc6175c274abaeabe3ef0c32d82627d498bbe7`.
- Original checker SHA256: `eb7a9eab936b7c7948ed13fbd6d6aca09aa38997c20685a8ee12d72e388d52c3`.
- Original allowlist blob: `7d46f41aa8fa354ce459471ba590804259548a33`.
- Original allowlist SHA256: `56a9a1cd05a0d81bba73a43c19e1451b213443f631dabacfa5b4e8d145e43d1c`.

`base-preparation-2/MANIFEST.json` binds 40 unique raw Git objects: 1 commit, 10 trees and 29 blobs. The retained preparation also checked the 21 original static file rows against their local bytes and Git blob map. These 21 files are not the complete next checkpoint.

## Actual preparation history

Preparation 1 failed before Git or a gate because GitHub's base64 transport included line breaks and the strict decoder did not remove transport whitespace. Its exact controller, failure receipt and all partially retained raw objects remain in `base-preparation-1/`.

Preparation 2 removed only transport whitespace before strict base64 decoding. All content hashes remained mandatory. It exited 0 in 0.13804308099861373 seconds, invoked zero Git commands and zero gates, and produced the 40 exact objects above. The original controller used by this successful preparation is preserved in `base-preparation-2/controller-original.py.txt`; its SHA256 is `6c07fe60f904935bcaf6a77a0c2dd5f99f2aadd4b08e6ac52f8322bb71a1e1b5`.

The reusable controller subsequently added a check that the original static manifest still has its frozen SHA256, and records its own and all input-manifest hashes in the result. The updated Python source parsed successfully as an AST. The updated check path has not been run against an invented or interim head. These changes do not edit the original checker, allowlist, 512000-byte limit or 120-second gate timeout.

## Run only after the final commit and full file manifest are frozen

From `/workspace/scratch/e9e051ab0825`, with an unused output directory:

```sh
python metrics_gate_work/checkpoint_blob_gate.py check \
  --base-manifest /workspace/scratch/e9e051ab0825/metrics_gate_work/base-preparation-2/MANIFEST.json \
  --files-manifest /absolute/path/to/final-complete-file-manifest.json \
  --head-api /absolute/path/to/final-exact-commit-api.json \
  --head FULL_FINAL_COMMIT_SHA \
  --output /absolute/path/to/new-gate-output
```

The file manifest is a list, or an object with a `files` list. Each row supplies `path`, `local_path`, `bytes`, `sha256` and `git_blob` (the aliases `git_blob_sha1` and `sha` are accepted); mode is `100644` unless explicitly `100755`. `--files-manifest` may be repeated. Duplicate paths must resolve to identical blob bytes. The complete manifest must include all 21 original static files and every other changed path in the actual final commit.

The controller creates a new local bare object store without a remote, imports and independently reads back exact objects, reconstructs every changed ancestor tree, requires the reconstructed root to equal the final commit API tree, checks the unsigned commit's exact Git SHA, and requires the actual full Git diff to equal the manifest. It then invokes the original checker over **238 → exact final head** and retains actual stdout, stderr, return code, timeout, elapsed time, object map and repository identity before/after. No checkout or ref is moved. Signed commits require exact raw bytes through `--head-raw`; signature bytes are never stripped. The final commit must currently have the single parent 238, otherwise an explicit ancestry extension is required.

For paths under an existing base directory not represented by the prepared trees, obtain that exact nonrecursive base tree API and its ancestor chain. A modified file also requires its old blob. The controller reports missing objects rather than fetching or weakening its checks. Additions under new directories need no prior tree. Deletions and renames are not supported by this checkpoint manifest workflow; any unrepresented change makes the reconstructed root mismatch.

## Evidence and limits

The preparation archive includes both attempts, exact raw APIs and objects, the original static manifests and policy pack metadata, the current controller, and an independent read-only cold-use design review. The raw object pack contains all original policy-pack objects; the already retained compressed transport parts are referenced by their unchanged PACK metadata, not duplicated as a second archive. Local absolute paths in original receipts are retained literally.

The review does not modify `e6_head_use_design` and does not implement, sign, compile or run its proposed APIs. The final gate receipt will be kept outside the tested checkpoint, avoiding a recursive attempt to put an exact-head gate result inside its own tested commit. Preparation work introduces zero model calls, training updates, native task children or remote owners.
