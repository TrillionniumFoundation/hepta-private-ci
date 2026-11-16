# Matrix source union evidence

This evidence records the exact Linux source union and its original gates.

- Full package tests: 77 passed, 0 failed, 2 existing ignored tests.
- Native inputs: 7761. Full source and control inputs: 8072.
- All five successful stages kept every input unchanged.
- Original failed attempts and their complete logs are retained.
- This is not Windows or old store version qualification.
- This source union does not preserve the incoming branch ancestry.

After restoring the original logical fragments with the command below, join the numbered fragments in order to restore the archive. The compressed manifest lists every original size and hash.
The publication index records all part sizes and hashes. Both JSON files
are stored as gzip so their original bytes remain unchanged.

The separate cache recovery archive records the narrowly authorized idle
incremental cache cleanup, including its first guarded stop and final
success. No source, audit file, dependency output, or build setting was
removed or changed by that cleanup.

## Restore the original compressed evidence

The physical archive carriers are individually compressed gzip files. Follow the [storage index and restore command](../compressed-evidence-storage-v1/README.md) first. The command verifies each carrier, unwraps and joins the original compressed stream, and restores every original logical fragment with its original SHA256 and Git blob identity. Existing stage manifests and publication indexes remain byte-for-byte historical originals and apply to those restored logical files. Their original filenames are not the new physical carrier filenames.
