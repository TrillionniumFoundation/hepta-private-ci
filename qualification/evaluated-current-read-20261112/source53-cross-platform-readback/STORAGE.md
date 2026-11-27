# Original source53 log access

The INITIAL, PROGRESS and FINAL manifests retain their original logical paths,
offsets, byte lengths and hashes. All 34 log parts are now stored beside those
paths as standard gzip carriers named `<original_path>.evidence.gz`. Decompression
preserves every original byte, including carriage returns and trailing spaces.

The original storage inventory already covered one part. The other 33 mappings
are recorded in
`qa/repository-consolidation/20261124/source53-log-gzip/raw-evidence-storage.json`.
The original inventory remains at
`qa/repository-consolidation/20261115/raw-evidence-storage.json`.

From the repository root, verify all three original manifests, part offsets and
complete log identities without extracting files:

```bash
python3 -B scripts/verify_source53_log_custody.py
```

To read files at their original paths, restore the combined 110-file inventory
to a new directory outside the checkout:

```bash
python3 -B qa/repository-consolidation/20261115/restore_raw_evidence.py /tmp/hepta-raw-evidence
```

This recreates the 34 source53 paths under the destination's
`qualification/evaluated-current-read-20261112/source53-cross-platform-readback/`
directory. The nine final logs still contain exactly 6,954,814 original bytes.
The command validates all registered files before creating its destination and
refuses an existing destination. It neither executes preserved content nor
queries or replays the historical jobs. Original failure and qualification
boundaries remain those recorded in the unchanged manifests and summaries.
