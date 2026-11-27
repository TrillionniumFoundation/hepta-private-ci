# Archived native runner source

`native-runner.py.gz` is the exact original 66-line native runner source, stored
as deterministic gzip. `ARCHIVED_SOURCE_STORAGE.json` gives original and stored
byte counts, SHA-256 values and Git blob IDs. Decompression was checked against
the original blob before committing; its original trailing blank line remains.
The historical `evidence-manifest.json` is unchanged and still describes the
original `native-runner.py` bytes. Restore the decoded bytes at that relative
name in a separate reconstruction directory when checking the old manifest.

This historical script executes operations at module top level. It is archival
source, not an importable current test or a new execution entry point. Do not
import or run it as part of discovery. It expects a specific old host, exact
source/three-file hashes and isolated target directory; it intentionally removes
two admission calls for a negative control and restores them before its original
full-package test. No current source has been changed by this archive.

All 39 original evidence-manifest members were verified before the storage
representation change; reconstruction of the one compressed member preserves
that exact manifest. Eight phase streams and the decompressed materialization
inventory match their retained hashes. These integrity checks do not rerun or
transfer the original Linux qualification to the current combined source.

The three current plasticity documents retain the normal semantic merge and
separate public DENY_ALL admission from private mechanics. Their generated
projection and test references match the current local documentation source.
Their bytes differ from the old qualification's documentation-output pins
because other composed documentation is preserved; the old pins remain historical.
