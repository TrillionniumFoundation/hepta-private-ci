# Historical raw evidence storage

The spelling check on published head `8576cdb3` identified 60 findings in 22
historical evidence files. A local run of the identical Codespell 2.4.3
configuration found nine more files in the newly merged historical records.
The document reference check also reported 38 immutable request, source and API
captures containing workflow paths from their original source or an upstream
repository. Their original references must remain intact as historical evidence.
Eight further frozen Learning captures were added after the next 23 ordinary
merges. These 77 files are captured console fragments, encoded
transport fragments, reference decoders and verbatim third-party source
captures, binary archive parts and a frozen recovery notebook. They are not
maintained application source. The archive reconstruction readers are updated
to find the compressed parts; other exact-path references in active source and
QA areas are preserved historical inventories and audit records.

Each file is stored beside its former path as an individual deterministic gzip
container ending in `.evidence.gz`. Every container expands to the exact
original bytes. The index records the original source commit, Git blob,
length and SHA-256, and the stored container length and SHA-256. No original
message, source spelling, scientific result or historical manifest was edited.
Every new blob remains below the existing 512,000-byte limit.

The spelling workflow, ignore lists, custody verifier, document validator and size limit are
unchanged. The preserved bytes now have a proper binary container, including
fragments that were previously being interpreted as ordinary text.

## Restoration

From the repository root, restore the 110 original repository-relative paths
into a new directory outside the checkout:

```bash
python qa/repository-consolidation/20261115/restore_raw_evidence.py /tmp/hepta-raw-evidence
```

The command validates all containers and original hashes before creating the
destination. It refuses an existing destination. Historical manifests continue
to describe their original paths and hashes; combine the restored paths with
the unchanged inputs from the corresponding historical source when reproducing
those records.

The existing `restore_neuro_evidence.py` command also reads these individually
compressed fragments when reconstructing its two original large records. Its
original complete-record length and checksum checks remain in place.

The `restore_library_recovery.py` command reconstructs the seven available
library recovery archives using their original part and complete-file hashes.
It does not manufacture the already missing original ZIP part. The frozen
notebook is restored by `restore_raw_evidence.py` before it is opened or rerun.

Historical failures remain failures of their recorded source. This storage
change does not confer execution, scientific or integration qualification.

## Complete source53 log view

The 2026-11-24 transport extension adds the remaining 33 source53 cross-platform
readback log parts to the existing 77-member inventory. Its separate index is
`qa/repository-consolidation/20261124/source53-log-gzip/raw-evidence-storage.json`;
the original index and all three source53 manifests remain unchanged. One
source53 part was already registered in the original inventory. Together the
34 decoded parts reconstruct all nine final logs, totaling 6,954,814 bytes.

Each original path in the source53 INITIAL, PROGRESS and FINAL manifests remains
a logical data path. The restore command above recreates those paths under its
new external destination, and `read_verified` resolves the same paths in memory
from the checkout. The separate extension index records each exact mapping to
`<original_path>.evidence.gz`. Existing historical document links and inventories
retain their original identities and refer to this restored view.

To verify the original part offsets, part identities and complete log identities
without writing files, run:

```bash
python3 -B scripts/verify_source53_log_custody.py
```

The current reader pins both storage inventories and rejects truncated,
concatenated or oversized gzip data. Its previous source and this document's
previous bytes are preserved in the extension's `prior-controls/` directory.
No historical log is replayed or used to grant new qualification.
