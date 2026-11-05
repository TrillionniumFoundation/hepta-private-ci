# Restore the frozen complete repository inventory

[The typed index](../fourth-repository-inventory-20261105.json) describes the complete inventory observed on 2026-11-05 at 03:16–03:24 UTC. It is an index, not the original inventory JSON object. The frozen counts remain 1,103 open PRs, 1,079 Drafts, 24 non-Drafts and 5,193 branches. This packaging change adds no new observation or qualification.

The original JSON is the `complete-inventory.json` member of the existing [archive manifest](archive-manifest.json) and its 18 existing base64 parts. Its identity remains:

- Bytes: `1846885`
- SHA256: `4adb3a73f03226fd73daba8c5ae2a5644fb84cde7702ddc892abb72d75a810f9`
- Git blob: `5fac62f2526a56ebc0cdaa8cfe66531c9a33f912`

From the repository root, verify the complete archive without creating any files:

```sh
python3 qualification/r3-audit-repair-20261104/repository-inventory-20261105/restore_inventory.py
```

To restore the exact JSON, choose a new output filename:

```sh
python3 qualification/r3-audit-repair-20261104/repository-inventory-20261105/restore_inventory.py --output complete-inventory.restored.json
```

The verifier checks the original manifest identity, ordered part offsets and identities, strict base64, complete gzip CRC, complete TAR identity, every member name and identity, and the restored JSON schema and frozen count projection. It reads TAR members in memory and never extracts archive paths. Output is created only after all checks pass; an existing output file is rejected. Nothing in the archived evidence is executed.

Parse the restored file to access `prs`, `branches`, observations, graph edges and all other original fields. A parser must not treat the typed index as the original `hepta.complete-repository-inventory.v2` object. The original internal `raw_identity_index` remains relative to its historical archive layout. Reconstructing only the JSON does not materialize those related API files.

The existing inventory builder writes `complete-inventory.json`; the historical root review reads that exact logical file and verifies it against the original archive member. Both frozen scripts and their original source paths remain unchanged. The Markdown reports link to the typed index. The current evidence index records the new index identity and retains the full original identity separately; historical receipts continue to describe the original bytes.

All 18 part files, the original archive manifest, original root review and their historical Git identities are reused unchanged. Blob-size and spelling policies are unchanged.
