# Original Git replacement regression source

This directory preserves one original 2,321-byte Python source object from the frozen source-candidate set. The source bytes are reused from the existing Git object and remain unchanged.

The original file was named `hepta_git_replace_local_repro.py`. A contemporaneous project ledger names hepta-private-ci commit `90dd67e39b1b8b4c462716144536524e104c04de`; that immutable commit adds the same `ls-tree` / `cat-file` / worktree comparison exercised by this reproducer. This concrete relationship supports the current isolated archival placement. It does not establish a unique historical owner.

`SOURCE_MANIFEST.json` records the original identity, Library version, target path and provenance. `INDEPENDENT_REVIEW.json` records a separate full source read and hash check. No archived source has been executed here. The file is a historical regression reproducer, not a production verifier or evidence that a current product vulnerability exists.

The containing repository is public. The source contains a fixture email at `example.invalid`; no obvious credentials, private keys or real personal email were found in the complete source reads.

Only a complete immutable commit/path byte readback matching the Git blob, SHA-256 and byte count permits adding this one candidate to the formal verification ledger. The 48 separately verified additional objects remain outside the frozen 6,116 candidates. No original Library item is deleted; archive, dot-directory and full-history completeness remain unproven.
