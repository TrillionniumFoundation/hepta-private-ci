# Original ARM recovery and external nextest store

This independent packet preserves the successful, unchanged Recovery23 attempt 2,
the recovered original ARM failure, and the narrowly published Unit27 source fix.
Older packets and the failed recovery attempt remain unchanged. It does not grant
native business qualification to the fixed source.

## Original recovery identities

Recovery #5116 source 7eea44fd62d75579e85c49666ffe44303bfddde9 and tree
07f129414cf4058d66bdac5e582c517f5b428119 ran as attempt 2 of 42280081679,
job 128116479789. The only authorized unchanged network retry succeeded. Root had
first durably published attempt 1's original timeout, ZIP, console and API
snapshots in #5123. Its retry intent and accepted API response are included here.
No timeout, source guard, collector bound or authorization was changed for retry.

Both recovery ZIP containers are retained byte for byte. Artifact 13535974710 is
3,616,662 bytes, SHA256 2da1057f6adec00aaa44abd0a2598d97cdb0f48668697f80e531614c2953f2c6.
Artifact 13537635259 is 65,228,946 bytes, SHA256 c08bb9175e2360b3591a704550f5b68ceaa3f838f67f5a91c0285fa4ff094f9f.
All four ZIP members were independently CRC, size and SHA256 checked. Their
947 selected original files, 64,562,356 bytes, match the exact inventory, original
member CRCs and selected file hashes. The native tar is 65,228,800 bytes with
SHA256 6b0f3da6c6edb40b0b7f0ee2f18ad6c56d917c73bda6e999dcae16ae43c2f077.
Its member mode is 0600. Inert local restoration used 0644; these are distinct
representations. Root's first mistaken 0644 tar expectation, correction and final
independent audit are retained without rewriting the initial note.

The 176,950-entry original ZIP catalogue is retained inside the manifest ZIP.
The exact native recovery driver verified the entire 3,673,783,489-byte original
artifact 13527344954, SHA256 17e3a426bb725839873cfa4f685e53eb5bf5dfa9bc67a468ea3c120d7f68bad5.
That original large ZIP was not downloaded again locally and is not reconstructible
from this packet. The two original recovery ZIPs preserve the complete declared
projection, not the excluded dependency or build trees. Excluded member CRCs were
not independently checked. Catalogue classification is not a fresh filesystem
walk and cannot prove that excluded native trees contain no directory links.

## The recovered failure and corrected diagnosis

The old ARM run is #5081 source 99e53dc988476d96c1e61354fbb0aeecd4c1cf17,
tree e368e870e179b0e726189192343f03b151bd1fa4, run 42247397355,
job 128023284385. Command 024 completed its native Cargo build successfully.
Command 025 completed metadata successfully, with target_directory already
/hepta-build/cold-test. That original metadata disproves the initial hypothesis
that CARGO_TARGET_DIR was missing or wrong; SOURCE_REVIEW retains the correction.

Command 026 then exited 96 while nextest 0.9.103 tried to create its independent
default store under the read-only source workspace's target/nextest/default.
Its original 295-byte stderr and all other selected logs are in the native tar.
Fixed official source shows that the store comes from workspace_root joined with
store.dir, independently of Cargo's correct target_directory. The business test
had not started. This is not an inferred test failure or a compiler failure.

The old collector also failed separately: 10,694 files matched its suffix rule,
with a maximum path length of 231 bytes. Therefore it exceeded the 5,000-file
count, not the 1,024-byte path bound. The original collector and full artifact
remain preserved; a later explicit diagnostic-view proposal is separate.

## Unit27 source and mechanism evidence

Unit27 changed only 20 lines in the ARM build helper. It creates an external
nextest store and tool configuration, supplies the same configuration to both
build-stage list commands, records and verifies its identity, and removes one
unused import. The repository profile, filters, retries, timeouts, Cargo metadata,
readonly source and native product commands remain unchanged. #5132 published
head cef06d5c2e4732e6e99070d8f1c60b034497443a and tree
56965aa1897e9383a704aec229b47e9512d1a329. Final source blob is
23fcde8ddffb17a8b321c466f6aedf74d0399842. The changed helper is outside the
sealed port source roster; no historical source seal or product lock was edited.

The final local Linux x86_64 probe used the fixed official nextest 0.9.103 binary
and inherited HOME, CODEX_HOME and every sandbox variable unchanged. The original
list actually exited 96 under a read-only-by-permission source. With the external
store, binaries-only and full-list commands each exited zero. Local denial was
a permissions error, not the native read-only-mount error. Two ordinary cases and
one ignored case were enumerated; zero test bodies and zero product tests ran.
The small source, metadata and binary identities stayed fixed. Root and the peer
reviewed these exact raw outputs without treating them as native ARM execution.

The first local probe had changed child HOME. It is retained as an unaccepted
earlier compliance attempt, alongside the separately executed inherited-environment
probe. Initial formatter and private-index audit failures are also preserved.
Final original just fmt, Ruff and original codespell passed. The private checkout
formatter restored its prior complete diff and status; root separately formatted
its own publication checkout. None of these checks substitutes for ARM behavior.

At the retained #5132 API snapshots, ARM job 128135711813 in run 42288193903 was
still in progress. It includes the actual Unit27 helper, unlike #5119's older
failed helper. Newer results require an additional source-bound audit; they are
not retrospectively inferred in this packet.

## Restoration and omissions

Run `python restore.py /absolute/new-directory` to restore every INDEX input as
inert regular 0644 files. The previously reviewed bounded reader differs only in
its fixed INDEX SHA256. It verifies the complete file set and identities before
writing, never executes evidence and never restores executable permissions.
Original file modes remain separately recorded in INDEX and native receipts.
The selected originals can be inspected through the retained recovery ZIPs and
tar, with their original roster and member checks. No whole original ARM archive,
compiler installation, Cargo cache or local probe executable is included.
Restoration does not rerun the native recovery, local probe or product tests.
