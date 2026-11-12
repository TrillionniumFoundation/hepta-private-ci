# Exact recovery of the pre-maintenance Git index

This package records one offline, identity-bound reconstruction. It is not a maintenance rerun, a qualification result, or a new native read of the earlier index.

## Established facts

1. The original maintenance job `1a1d10d8ad0-2564-1bff` used source `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`. Its actual fix command returned **101**, and fmt was **not run**. The original final Git audit made the wrapper result **UNKNOWN**. Those original records remain unchanged.
2. Original before and fix.after Git-state records have the same blob, `3dfa3c7919d44ee7b7b81e52817888ced2d86d8c`. The final record is `ced763797ed34c019e0aec22db03e5ace977badd`. Only `index_sha256` differs; both records give an index size of 2,072,488 bytes. HEAD, tree, raw HEAD, config and refs identities are equal.
3. Native subsequently retained the actual current index with two stable full reads. Its 2,072,488 bytes have SHA256 `b19fab7a860a4281331096bd6a9c2ab5b6b9ef95ff8411e9f757cd1373380f15`, exactly matching the original final record. The native raw snapshot is distinct from this offline reconstruction. Its normal terminal is `547dc8f51f440a4dd2b5d7586aa5b76cc5f061eb`; its complete stdout is `cbcefe95809b1e7de64f258b53fe8231ee5ee1f2`. Its lossless transfer manifest is `b4b3ec7fc2840f3b660cbb26b0e9df20f60a554d`.
4. At 2026-11-12 19:16:15 UTC, the parser in this package made exactly one candidate: zero the nine standard stat uint32 fields in every index entry, preserve every other byte except the trailing checksum, then recompute the SHA1 checksum. The candidate's full size and SHA256 exactly match the independent original before record: **2,072,488 bytes / `111345e57b5b7276c8fdb4e91302c7bafb6d7c8ca905f83dd1a6c72a28154a16`**. Its derived Git blob identity is `3c18e139aa23f5f2898b740941b70f20fbd824ab`.
5. The actual index is version 2 with 15,188 entries. Mode, object ID, path, stage, flags, padding, the header, and all extensions remain byte-identical. Every entry's logical mode/object/path agrees with the full original physical inventory, SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`. All stages and upper flag bits are zero. Its sole `TREE` extension, including the header, is 68,856 bytes and remains unchanged.
6. The restored before index contains zero values in those nine stat fields. Eight fields changed for all 15,188 entries; cached file size changed for 15,128 entries. The nine fields are ctime seconds/nanoseconds, mtime seconds/nanoseconds, device, inode, uid, gid, and file size. **Mode is not one of the fields zeroed.** The exact original hash match proves that the before-to-final byte difference is limited to these stat fields and the trailing checksum. No search over further ignored fields was performed.
7. The current index's recorded mtime is 18:48:59.971771627 UTC, inside the original artifact-generating `git diff` interval, 18:48:57.599973–18:48:59.992974. This timing is consistent with Git's documented automatic stat refresh. It is not a direct observation of the writer, and the native Git version was not recorded. Writer identity and native Git version therefore remain **Unknown**.
8. No repository file, Git object, index, ref or configuration was changed by this analysis. No native command, Cargo command, formatter or qualification gate was run. The original wrapper UNKNOWN, fix101, and fmt-not-run facts are not relabeled by this explanation.

## Minimal successor recommendation

Keep all original raw Git equality checks and complete physical-source checks. Change only the artifact-generating diff invocation inside `archive_transition` to pass the command-local option `-c diff.autoRefreshIndex=false` before `diff`. Do not write Git configuration or treat future index differences as ignorable. The new maintenance run must still use its own actual initial Git state and the separately authorized exact source-advance evidence. The original fix7200/fmt900 budgets and qualification gates remain unchanged. This package does not implement or execute that successor.

The relevant fixed official sources are Git **v2.43.0**, rather than a claim about the unknown native installed version:

- [Git index format](https://github.com/git/git/blob/v2.43.0/Documentation/gitformat-index.txt): entry fields, flags, padding, extensions, and checksum.
- [diff.autoRefreshIndex documentation](https://github.com/git/git/blob/v2.43.0/Documentation/config/diff.txt): porcelain diff's default automatic stat refresh.
- [builtin/diff.c](https://github.com/git/git/blob/v2.43.0/builtin/diff.c): `refresh_index_quietly` and its invocation after a stat-only mismatch.
- [read-cache.c](https://github.com/git/git/blob/v2.43.0/read-cache.c): `repo_update_index_if_able` and the index write path.

The original command chronology is preserved in `04fea8e8dec0d7b2c2340d2a48cde4766a63f0b5`. The original maintenance result is `30300f4cf4743e3fb80ccf404f7e7be4d8b81ac6`; the original fix terminal is `d3777e7c9b18f23b1b0dd91ab5b787117cb348cb`.

## Reconstruction and storage

`RECONSTRUCTION.json` gives every size, SHA256, Git-content identity and part order. Each stored part is UTF-8 base64 with one final LF. Decode each part independently and concatenate the decoded bytes in increasing ordinal order; do not concatenate padded base64 strings before decoding. Verify the resulting gzip identity, decompress it, then verify the complete raw identity. The recovered before index uses three parts; the complete per-entry derived audit uses four parts. Each stored part is smaller than 500 KB.

The raw/gzip Git identities describe their exact content; only the small records, script and encoded parts are committed as blobs in this package. The earlier actual after-index transfer and its eleven SDK witnesses are owned by the native retention package and are referenced here without claiming new reads or duplicating its archive.

`REPORT.json` is the actual offline parser result. `entry-stat-audit.json` is a derived complete entry-by-entry analysis, not a native original record. `index.before.exactly_recovered.bin` is exact-byte recovery under the original independently observed SHA256, not a newly observed historical file.
