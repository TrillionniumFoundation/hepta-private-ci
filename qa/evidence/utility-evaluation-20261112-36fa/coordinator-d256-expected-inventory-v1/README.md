# Expected inventories for actual candidate d2567544

These complete expected inventories bind the actual Root-created and fully read-back commit d25675445c39f76db69a7bd8e71a1a72e1cd5b9f, tree a489b394666b8141840275128a780605b024cde0, sole parent cc57c7198db6293ccca562253c42fffbe2a04633. The 935-byte original commit body is preserved and independently reproduces the typed commit hash. Source refs are not moved here.

Before deriving this candidate, the unchanged original 5118 serializer reproduces every byte of the complete 5,611,184-byte cc57 inventory, and the unchanged original native projection function reproduces the 3,530,181-byte baseline with SHA-256 20008a0c.... No original driver main or source snapshot function is executed.

EXPECTED_CLEAN_INVENTORY.json contains 15,243 rows in the original full format. EXPECTED_NATIVE_FIVE_FIELD.json contains exactly path, mode, bytes, sha256 and blob, sorted by os.fsencode(path), serialized with original sorted compact JSON and no final newline. Both are pure expected metadata. Clean status, stable reads, index equality and the 15,243-file count remain requirements for a future actual materialization, not new observed facts.

All 90 executable files and the one symbolic link retain their complete original rows, including lstat permissions. Relative to cc57 the complete graph has 55 additions and 63 modifications, retaining the other 15,125 original rows. There are no canonical deletions.

ENCODING_MANIFEST.json pins the complete raw and deterministic gzip content and every lossless base64 part. The seven complete-inventory parts and six native-projection parts are independently bounded below 512,000 bytes. The raw large files are preserved by complete reconstruction; no separate direct raw-blob upload or second native read is claimed.

This package provides no maintenance, source-gate, Rust, QA, Root-case or real task-chain success. The earlier fix101 failure remains intact. A future exact materializer must independently produce the expected content before the separately approved original maintenance and qualification sequence can proceed.
