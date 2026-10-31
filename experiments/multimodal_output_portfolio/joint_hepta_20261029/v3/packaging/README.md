# Lossless evidence transport

`evidence_pack.py` uses only the Python standard library. It packages real
evidence directories, including binary parameter checkpoints, emitted media,
raw outputs, trajectories, seals and manifests. It never deletes source files.

Each bundle contains:

- `INDEX.json`: compact, directly readable summary and trusted digest anchor.
- `CHUNKS-*.json`: ordered pages of at most 128 chunk identities.
- `archive.part-*.bin`: consecutive bytes of one deterministic tar.xz stream,
  at most 393,216 bytes (384 KiB) each.
- `PACK_REPORT.json`: actual packing/verification time, byte-copy costs and
  integrity results. This timing record is deliberately outside the deterministic
  archive and index.

The potentially large per-file manifest is the first archive member. It records
every relative path, kind, byte size, SHA256 and ordinary permission bits. Its
size and SHA256 are anchored in `INDEX.json`. Actual files live under the archive
`payload/` prefix, which is removed on restoration. Empty directories are kept.
Owner IDs/names and timestamps are canonicalized; this is exact content/path
preservation, not a backup of all original filesystem metadata.

For the same source content/modes, ordering, preset and compression runtime, the
archive and root index are deterministic; the test changes source timestamps and
checks that both digests stay identical. New matrix bundles use XZ preset 8
(32 MiB dictionary), emit directories first, and group model parameter files by
their full path before other evidence. This keeps each seed/width/core cell's
parameter variants adjacent without changing a single restored byte. Previously
completed bundles retain their original preset/order and identity.

## Commands

Run from the experiment directory or use absolute paths. Destination parents
must already exist, and bundle/restoration destinations must not exist.

```bash
python v3/packaging/evidence_pack.py pack evidence-directory new-bundle-directory
python v3/packaging/evidence_pack.py verify bundle-directory \
  --expected-index-sha256 TRUSTED_INDEX_SHA256
python v3/packaging/evidence_pack.py unpack bundle-directory new-restoration-directory \
  --expected-index-sha256 TRUSTED_INDEX_SHA256
```

All bundle files can be retrieved as ordinary repository files. The trusted
root index digest should come from the pinned publication commit or a separately
retained receipt. SHA256 checks detect corruption; an attacker who replaces the
whole bundle and its untrusted index does not thereby provide authenticity.

The repository's unchanged blob gate allows at most 500 KiB (512,000 bytes) per
file. Transport chunks and metadata pages are bounded more tightly at 384 KiB
(393,216 bytes); the large per-file manifest stays inside the compressed stream.
No gate or allowlist exception is required. Publication includes only completed
bundles, source code, and small readable summaries/receipts. The interrupted
`pilot_matrix_20261030` transport copy and `restored_checks/` are excluded; the
original pilot evidence is preserved completely in the replacement bundle.

### Selecting the restored root

The destination becomes the source directory itself: `payload/` is removed,
and no extra source-name directory is nested inside it. Run this concrete
example from `v3/`; choose an unused destination whose parent exists:

```bash
python packaging/evidence_pack.py unpack \
  packaging/bundles/open_text_final_20261030 \
  /tmp/hepta-open-text-restore-20261030 \
  --expected-index-sha256 a2fb1dc26e84eaa99bd0857dea7e2290ed069e4dba5e940430b6bb06315d5f80
```

The table below maps each bundle to its original experiment root. A published
checkout already contains selected readable summaries and audit source files,
so some of these roots will exist even in a fresh checkout. Restore first to an
unused directory outside the checkout, as in the example above. To hydrate the
original tree, preserve the existing target by renaming it to a distinct,
previously nonexistent backup path, then unpack at the now-absent original path.
Keep that backup for comparison. Do not merge or silently overwrite an existing
tree. The tool performs neither backup nor merge on the user's behalf.

Audits that use the original experiment-relative paths require the corresponding
complete mapped tree; an isolated out-of-tree restore is sufficient for byte
inspection, but is not itself the complete audit execution layout.

| Bundle under `packaging/bundles/` | Original root relative to `v3/` |
| --- | --- |
| `pilot_matrix_grouped_20261030` | `evidence/matrix_20261030` |
| `final_matrix_20261030` | `evidence/matrix_frozen_20261030` |
| `diagnostics_final_20261030` | `evidence/diagnostics_frozen_20261030` |
| `critic_choice_final_20261030` | `evidence/critic_choice_frozen_20261030` |
| `open_text_pilot_20261030` | `evidence/open_text_20261030` |
| `open_text_final_20261030` | `evidence/open_text_frozen_20261030` |
| `native_generation_20261031` | `native_generation/evidence` |
| `audit_20261031` | `audit` |

Use each bundle's own trusted INDEX digest; the example text-bundle digest does
not apply to another bundle. An inventory entry in this table alone does not
mark a bundle complete: completion requires its INDEX and successful pack
report. The final publication catalog records the completed identities.

`verify` reads every chunk, checks the ordered complete archive hash, then
decompresses and hashes every actual file. `unpack` performs the same integrity
checks while writing a newly created private directory. It does not call tar
extraction APIs. Traversal paths, symlinks, hard-link archive entries, special
files, duplicate members/metadata, missing or extra members and overwrite
attempts are rejected. A failed restoration removes only its newly created
destination. Source symlinks and special files are rejected without following.

`pack` inventories and hashes the source, hashes the actual bytes read into the
archive again, and performs a second complete filesystem walk after compression.
Any detected file addition, removal or identity/stat change prevents creation
of a completed index. Partial chunks from a failed pack remain visibly
uncommitted, without `INDEX.json`. Run only on completed/stopped evidence trees;
the tool does not lock an active experiment or defend against a malicious
same-user process racing every filesystem operation.

## Validation

```bash
python -m unittest \
  experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.packaging.test_evidence_pack \
  -v
```

Tests include deterministic multichunk round-trip restoration of binary data
and empty directories; altered chunk bytes; wrong trusted index; existing
destination preservation; self-consistent malicious traversal, duplicate and
symlink archives; source symlinks; and a new source file introduced during
packing. The corruption and malicious-archive tests do not depend on merely
changing a declared hash to produce the desired rejection.

Small study summaries and external process receipts should remain directly
readable in the repository alongside these bundles. Packing one directory does
not silently include similarly named sibling receipts or archives.

`RESTORE_REPORT.json`, when present, records an actual restoration into a fresh
directory and a second independent full hash inventory comparison with the
original source, including ordinary modes and empty directories. Restored check
copies and an interrupted compression attempt are retained locally but are not
publication bundle members. Only completed bundles with `INDEX.json` and a
successful `PACK_REPORT.json` belong in the publication catalog.
