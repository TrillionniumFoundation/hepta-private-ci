# Coordinator operation provenance 01

This is an immutable snapshot of explicitly selected files that existed at the operations directory root when selection began. It is not a claim that all future or parallel execution history has been captured. Source files were read without modification.

The selection excludes exact file keys already named in NATIVE_SOURCE_PLAN_01.json or NATIVE_EVIDENCE_PLAN_01.json, publication-*-input*.zip and publication-*-part*.bin temporary transfer duplicates, and CI_JOB_*.log files verified byte-equal to their existing CI_FAILURE_LOGS_02.zip members. Both earlier plans are themselves included unchanged. No subdirectory was traversed. Base weights, environments, caches, raw C data, and ongoing model-result directories were not selected.

The snapshot preserves current helper sources, earlier helper 01/02 ZIP bytes, the diagnostic freeze, model recovery 04 archive, prepared/failed receipts, launch and transfer records, formatting records, and historical coordination notices. Preserving a launch intent, test log, or failure receipt does not turn it into evidence of a completed model run. These historical source copies do not replace the parent's separate review/publication of active modules or actual results.

## Content and verification

MANIFEST.json pins the selected-member index, complete ZIP stream, split parts, selection interval, and archive checks. MEMBERS.jsonl.gz is a compressed mechanical index: its member rows contain every original name, repository-relative source path, ZIP name, size, SHA-256, and before/after source metadata; exclusion and untraversed-directory rows make the scope explicit.

Original member bytes were checked before and after ZIP creation. The ZIP CRC, every decompressed member, and the reassembled part stream were checked against those exact bytes. This is a verified selected-file snapshot across the stated observation interval, not a filesystem-wide atomic snapshot or proof that a future writer cannot change the original files. ZIP container timestamps are fixed for reproducibility; original source metadata is retained in the index. No original contents or line endings were rewritten.

The complete ZIP is retained only as ordered ARCHIVE.partNNNN.bin files. Each part is at most 322,560 bytes; every published file is below 512,000 bytes. Do not add a reconstructed larger ZIP or extracted large logs to Git.

## Restoration

Concatenate the parts in MANIFEST.json order outside the repository, verify each part's size/SHA-256 and the resulting ZIP size/SHA-256, then use a standard ZIP reader. The archive members are under operations/. Verify their uncompressed size/SHA-256 using the member rows from MEMBERS.jsonl.gz. Keep the historical snapshot separate from active operation files when extracting.

The create-only Mac copy is a preservation copy. A separate MAC_VERIFIED.json receipt is added only after the target verifies all manifest files, reconstructs the complete ZIP, checks CRCs, and checks every member against the compressed index. That receipt records transfer verification; it does not extend the captured source-history interval.
