# Agentd native repair evidence

This directory preserves the exact original bytes of the v8, v9, v10, v11 failure, and v12 records. The index maps every original file to its stored bytes and records its SHA256 and Git blob hash.

JSON originals are stored as individual deterministic gzip files. Every original binary archive part is preserved through the carrier mapping. Each physical carrier is at most 500000 bytes. Restore a stage's original numbered parts first, then join them in order and decompress the resulting original gzip archive. The original stage manifest checks every recovered member.

The v8 and v9 diagnostic failures and the v11 resource failure are retained. V10 passed with temporary diagnostics. V12 removed those temporary diagnostics, then passed the original changed-files formatter, an explicit check of all ten final paths with the original formatter configuration, the original scoped Agentd fix command, the original 26-test selection, and eight codec tests. All recorded inputs remained unchanged at each v12 stage.

V12 covers its exact unpublished candidate and those five commands. It does not qualify all Agentd tests, the repository, Windows, or a later commit. The separately stored plan prose clarification preserves the original plan and explains its inherited v10 label. Resource recovery intent and result records preserve the exact authorized cache cleanup.

No temporary diagnostic Rust source is added to an active source path by this evidence publication.

## Restore the original compressed evidence

The physical archive carriers are individually compressed gzip files. Follow the [storage index and restore command](../compressed-evidence-storage-v1/README.md) first. The command verifies each carrier, unwraps and joins the original compressed stream, and restores every original logical fragment with its original SHA256 and Git blob identity. Existing stage manifests and publication indexes remain byte-for-byte historical originals and apply to those restored logical files. Their original filenames are not the new physical carrier filenames.
