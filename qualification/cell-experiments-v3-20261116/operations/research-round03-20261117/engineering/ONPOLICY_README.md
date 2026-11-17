# On-policy engineering evidence

This package supports review of the E2 loop and shared-adapter pool implementation.
It is engineering evidence and does not establish E1–E6 scientific success.

## Files

- `onpolicy-engineering-evidence.zip`: code history and evidence views.
- `INDEX.json`: archive hash, source hashes, provenance, omissions and status.
- Code snapshots are content-addressed: `snapshots/source-01..04.json` map paths
  to byte-identical Python files under `code_blobs/`; identical versions share blobs.
- `ARCHIVE_MEMBER_HASHES.json` hashes the actual archive members.
- `SOURCE04_ORIGINAL_FILE_HASHES.json` lists every original source-04 file hash.
  This original-snapshot listing is not the archive inventory.

## What actually ran

- E2 flow: five protocol/business-verifier tests passed; scripted model/fit fixtures.
- Warm start: one actual tiny CPU Qwen2/PEFT save/load/hash/update test passed.
- The complete original PTY output bytes and actual exit status are included.
- Warm-start attempt01 failed importing `hepta_cells`; corrected attempt02 passed.
- Source-04 lifecycle/cache: 11 dependency-free behavior tests passed.
- Independent review repeated those 11 tests and accepted the Circuit interface.
- Import failures and corrections are retained, including the reviewer's failed
  namespace harness and its explicit correction of an inaccurate fallback label.

## Public derived views

JSON views retain original error text, status and codes. Only redundant `bytes_hex`
fields and internal tunnel URL fields are omitted recursively. Each view records
the original file SHA256, JSON pointer and every omitted field with its value hash.
Derived JSON is not labelled as original bytes. Its own SHA256 is separately listed.
Code blobs and extracted complete PTY bytes remain byte-identical to their sources.
Sealed source-01 through source-04 originals were not modified.

## Still unverified

Real pool A/B/A numerical switching, default-backend smoke, production pool loading,
actual GPU memory recovery and a native Python 3.10 run remain NOT_RUN/NOT_MEASURED.
No GPU job or remote operation was performed while preparing this package.
The root integration 37 tests were not rerun. Independent sample increment is zero.
New C, native adoption and scientific confirmation remain unqualified.
