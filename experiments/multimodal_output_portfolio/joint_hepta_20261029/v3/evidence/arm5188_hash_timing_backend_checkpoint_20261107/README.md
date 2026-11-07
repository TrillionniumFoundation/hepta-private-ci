# ARM timing and backend evidence

This packet preserves the failed ARM qualification for source #5188, commit `5043c1a1937200edb5b34d044425e39f5dfd3281`, tree `f7b0144a48fbc5c2f9947e8ae0570c839bc3e6b3`, run `42312327246`, job `128217534470`, attempt 1. The single selected business test timed out under the original 1200-second policy: zero passed, one timed out and eight were filtered. Both original build-stage enumeration commands passed, and source and seed integrity checks remained true.

## What the observations establish

The 36 completed, disjoint spans around the original file read and validation calls total 692.469 seconds and 10,544,121,936 bytes. These spans include reading and validation; they do not isolate CPU hashing or account for all work. The second post-ready release record did not finish. The first post-ready sync was not reached. The final unfinished span has no assigned duration.

The real AArch64 Cargo compiler records contain sha2 0.10.9 with default/std features and optimization level zero. The exact locked crate source selects its software backend for those features. CPU SHA2 capability and the performance of any future accelerated configuration remain unmeasured. No dependency, lock, budget, profile, assertion, retry or validation call was changed by this audit.

## Original bytes and limits

The original 185-file `FREEZE.json` is retained unchanged. This packet includes 183 of those files, totaling 97,653,763 bytes, and explicitly excludes only the two private whole-job console files named in the INDEX. Their identities remain in the original freeze; their contents are not reconstructed by this packet. The backend source review, timing36 source change, preparation failures, final checks and source reviews are also retained without rewriting their earlier conclusions.

Both original narrow diagnostic ZIPs are included. Their four members, all 1,447 selected payloads totaling 68,383,939 bytes, and the 84,421-entry source catalogue were audited. The full 1,788,250,243-byte artifact has an API identity only: it was not downloaded, hashed locally or reconstructed. Catalogue information for excluded entries does not reproduce their contents. The original projected tar uses mode 0600; the outer inert restoration uses mode 0644 and records each input's original mode separately.

The independent root audit is identified as an external companion in the INDEX; it is not silently included in this inventory. This packet does not establish an accelerated product, newly generated locks, hardware availability or a passing business test.

## Restoration

Run `python -O -B restore.py NEW_EMPTY_DESTINATION` from this packet directory. The unchanged bounded reader verifies the fixed INDEX seal, each independent gzip segment, the complete XZ and tar identities, and every member's path, size and digest before creating the destination. It writes only inert regular files with mode 0644 and never executes archived code.

The author checked the same canonical reader through its `read_package` function in memory, compared the complete recovered set and original bytes, and checked inert archive modes. No second expanded disk copy was created during packaging. The fixed limits remain 64 MiB compressed, 256 MiB uncompressed, 2,048 files, 450,000 bytes per wrapped part and 440,000 bytes per decoded segment.
