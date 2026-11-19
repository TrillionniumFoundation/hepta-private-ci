# Unresolved source custody - 2026-11-07

The 12 unique originals (13 recorded Library occurrences) are preserved as data in source-custody.tar.gz, with their original unresolved-direct-code/ names, exact bytes and Git modes. SOURCE_CUSTODY.json is unchanged beside the container. The original version of this document and the original manifest are also preserved inside it.

ARCHIVE_MANIFEST.json maps each original repository path to its unique member and binds the source commit, Git blob, mode, size and SHA-256. An unknown original product insertion path remains unknown. Neither Rust snippet is installed as active source, and no synthetic Cargo context is invented.

Run the maintained data-only verifier from the repository root:

    python3 library-recovery/20261107/verify_custody.py

It checks the complete source manifest and every member without extracting or executing them. Missing, duplicate, unsafe, linked or modified members fail validation.

The original document records historical parsing and 23 standalone tests; those records are preserved without claiming a new execution. E4, physical-token and strict-E2 programs still lack their recorded package context. This packaging does not run those programs or the Rust snippets. ARCHIVE_ONLY_DRAFT_HOLD, DENY_ALL, no product acceptance and the original attribution limits remain unchanged.
