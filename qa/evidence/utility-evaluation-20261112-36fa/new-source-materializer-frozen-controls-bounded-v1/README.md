# Frozen materializer controls: bounded lossless archive

This package preserves exactly 24 frozen materializer controls and their 48 previously saved original Git create/full-GET SDK files. Native handed off this closed set in `GIT_READBACK_LEDGER.v2.json`; its exact 7,201 bytes are retained as `HANDOFF_LEDGER.original.json`. No staging runtime or materialization runtime directory is included.

The 72 input byte strings total 5,903,437 bytes. Sixty-six fit directly in the evidence leaf limit. The remaining six are the three 699 KB staging request bodies and their three complete GET SDK files. Each is represented by deterministic gzip plus three strict base64 parts. The 84 input-representation leaves have a maximum size of 349,529 bytes; no leaf requires an exception to the 512,000-byte limit.

`ENCODING_MANIFEST.json` records every original length, SHA-256 and Git blob identity, together with direct or compressed storage mapping. For encoded records, concatenate strict base64-decoded parts by their recorded offsets, verify each decoded part and the complete gzip identity, decompress, and verify the complete original triple. Raw SDK blob identities are reconstruction identities where no standalone raw GET is asserted.

All 89 initial archive leaves and preparation metadata were actually created in Git and fetched in full. `FULL_GET_RECONSTRUCTION_REVIEW.json` then rebuilt all 72 original byte strings from those returned contents and matched each one to the frozen source files. `FULL_READBACK.json` covers the complete subsequently closed payload list, and `PLACEMENT.json` provides paths relative to the current evidence leaf.

`ARCHIVE_REVIEW.json` retains its earlier local-only/pending-upload observation unchanged. The later full-GET report supplies the actual completion; prior HOLD and approval-candidate states are never rewritten. The new compression is an archival representation of existing original bytes, not another native capture or qualification result. No H, source/ref mutation, bootstrap, materializer, formatter, Rust or QA execution occurred in this archive task.
