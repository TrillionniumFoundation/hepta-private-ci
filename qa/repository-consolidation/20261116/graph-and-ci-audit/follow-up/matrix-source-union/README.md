# Matrix source union evidence

This evidence records the exact Linux source union and its original gates.

- Full package tests: 77 passed, 0 failed, 2 existing ignored tests.
- Native inputs: 7761. Full source and control inputs: 8072.
- All five successful stages kept every input unchanged.
- Original failed attempts and their complete logs are retained.
- This is not Windows or old store version qualification.
- This source union does not preserve the incoming branch ancestry.

Join the numbered `originals.tar.gz.part*` files in order to restore the
archive. The compressed manifest lists every original size and hash.
The publication index records all part sizes and hashes. Both JSON files
are stored as gzip so their original bytes remain unchanged.

The separate cache recovery archive records the narrowly authorized idle
incremental cache cleanup, including its first guarded stop and final
success. No source, audit file, dependency output, or build setting was
removed or changed by that cleanup.
