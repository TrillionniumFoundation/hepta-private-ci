# Historical Memory archive storage

The 75 files indexed in `HISTORICAL_ASSETS.json` total **351,656,533 bytes**.
They are historical raw archives and receipts, each larger than the current
512,000-byte blob limit. Their exact bytes remain in commit
`1657238edcc0793bc353c931f9ca445ef992315c`, which is a parent of the ordinary
Memory merge and remains reachable through its history after branch retirement.
The current tree stores the complete path, mode, source commit, Git blob ID,
length and SHA-256 inventory. No new size exception or duplicated archive was
introduced. The five separate active fixtures with exact SHA exceptions remain
at their existing paths.

## Verify and restore offline

From the repository root:

```sh
python3 qa/repository-consolidation/20261115/memory/restore_historical_assets.py --verify-only
python3 qa/repository-consolidation/20261115/memory/restore_historical_assets.py --output /tmp/hepta-memory-historical-assets
```

The destination must be a **new directory outside the repository**. The tool
checks that the source commit is an ancestor of HEAD, every original path binds
to the declared blob in that source tree, and every blob matches its type,
length, Git object hash, and SHA-256. It verifies written bytes again. Existing
destinations are refused. Git replacement refs and implicit network retrieval
are disabled. A shallow or partial clone must already contain the recorded
history and blobs; missing objects cause an explicit failure, with no automatic
fetch. Restore the required history using an independently authorized repository
operation before rerunning the tool.

This operation restores the original files and any original archive pieces.
It does not unpack them, execute archived programs, combine incomplete archive
sets, or turn historical records into fresh qualification. Dated inventories
continue to refer to their original paths and hashes; use the external restored
projection for historical inspection.

All 75 files were actually restored to a temporary external directory and
rechecked byte for byte before the current-tree copies were removed. The
receipt is `historical-object-storage-verification.json`. Nine temporary-Git
regressions passed, including tampered path/hash/size, non-ancestor history,
traversal/duplicate paths, existing output refusal, Git replacement substitution,
and missing local blobs with a synthetic promisor that must never be invoked.
No real network or archive contents were executed by those tests.
