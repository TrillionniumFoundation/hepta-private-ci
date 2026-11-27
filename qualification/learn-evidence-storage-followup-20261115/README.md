# Original adjacent Learning evidence storage

10 historical artifacts are stored as ordered 500,000-byte parts under the unchanged 512,000-byte blob limit. 9 are original base64 export pieces; 1 are complete original source audit JSON files. Concatenation restores exactly the original Git blob bytes, including their original formatting and newline. No experiment conclusion or historical export manifest is rewritten.

`VERIFICATION.json` records each original commit and blob, full SHA-256, length, ordered part manifest and actual restoration results. Each `.parts.json` also includes original and part hashes, offsets, lengths and exact no-clobber restoration/checksum commands.

Run from the repository root to restore the original repository-relative paths under a separate destination:

```sh
python3 qualification/learn-evidence-storage-followup-20261115/restore_original_evidence.py /tmp/hepta-learning-evidence-restored
```

Omitting the destination restores the original paths under the current directory. Every output must be absent. The program verifies every part and full original before creating files with exclusive mode. It never overwrites an existing file.

All listed originals were reconstructed in a temporary destination and compared byte for byte with their original Git blobs. The second restoration refused the existing outputs. All documented checksum commands passed. The listed original helper JSONL export groups were reassembled against their unchanged export manifests, decoded strictly from base64, checked by full original hash and length, and parsed as JSONL. The original source audit JSON also parsed. This is storage verification only and creates no native, live-owner or ordinary-adoption acceptance result.
