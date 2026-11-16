# Source recovery storage and known archive gap

Seven incoming blobs exceed the repository's 512000-byte limit: five original
raw ZIP pieces and two complete source-only tarballs. Their bytes are retained
as ordered pieces of at most 400000 bytes under `storage-20261115/`.
`STORAGE_MANIFEST.json` binds every original path, size, SHA-256 and Git blob ID
to its piece inventory. Every original was reconstructed from the stored pieces
and matched exactly before this ordinary merge was committed. No blob-policy
exception was added. Historical indices keep their original archive identities.

## Reconstruct the available original files

From the repository root, choose a new destination directory. This restores the
seven chunked files; unchanged small files and sidecars remain in the repository.

```sh
python3 qa/repository-consolidation/20261115/restore_library_recovery.py /tmp/hepta-source-recovery-originals
```

The restore command reads the original inventory and checks every part and
complete archive against its original length, SHA-256 and Git blob ID before
creating the destination. Four stored parts now use complete `.evidence.gz`
containers to preserve their binary bytes; the original part identities remain
in this manifest and the raw-evidence storage index supplies their containers.
An existing destination is rejected.

## The raw HCSN V9 ZIP is incomplete

The incoming commit contains only original ZIP parts 000, 001, 002, 003 and 005.
Part 004 is absent from its full Git tree and from the prior integrated tree.
The sidecar describes an 11257341-byte full archive; available pieces total
9257341 bytes, leaving 2000000 bytes missing. Splitting the available pieces
does not restore that gap. A full raw ZIP hash check or experimental replay is
not possible from these retained pieces. No replacement bytes were fabricated.

The complete **source-only** HCSN V9 tarball is separate and available. All three
complete source-only tarballs match their sidecar and internal manifest; 339
selected members match length/SHA-256, with 243 Python syntax and 31 JSON parsing
checks passing. Original experiment datasets/checkpoints/results are outside
that source-only claim. No bundle member was extracted or executed.

## Historical tools and notebook

The two dated bundle scripts are preserved source for the original `/mnt/data`
operation. They have top-level actions and are not current CI gates. In
particular, the old verifier's missing-manifest branch can omit a failed bundle
from its summary and its reported issues do not set a nonzero process exit;
do not use its exit code as archive qualification. This consolidation used
independent strict member/inventory checks over all three actually supplied
bundles, rather than running the historical fixed-host script.

The notebook's only code cell was reviewed and run independently: its existing
24 first-passage parameter cases, 48 discounted cases and 24 stationary cases
pass their finite-grid tolerances. This is analytic/numerical consistency only,
not a training, model-quality or production result. Original notebook bytes and
outputs are preserved exactly in its adjacent `.evidence.gz` container. Use
`restore_raw_evidence.py` to restore the original notebook path before opening it. The historical Library deletion/HOLD instructions
are retained records; this work did not delete or modify any Library item.
