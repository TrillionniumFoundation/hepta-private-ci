# Original S/C readback guard repair

Published source: `f4e008f6ce1162239f0a02f4ce89b8c8185abc36`.
Parent: `dd4b6c17344986a3a9379e372bf19d282f812a30`.
Tree: `7afea5a8f468ccf04b84ff5f6b7e314d2b3bd18e`.

The six-file change updates source guards and mutation tests only. It preserves
all original caller boundary records, all protected-file records, and all
RootAdmin tests. No Rust, dependency, authority, grant, signer or runtime policy
changes are included.

## Guard changes

The existing S/C receipt owners split completed authentication into three
responsibilities. `decode_completed` checks exact saved receipt and full signed
bytes. `finish_original_readback` performs actual publication and predecessor
reads, reads the original journal again, then samples the current clock.
`authenticate_completed` is pure and uses that final clock for every original
signature and independent role check. Both concrete source locations retain
their required order. The remote path brackets the journal with actual original
predecessor reads without recursively opening those reads in `prepare`.

Guards now protect those exact functions and their order. They additionally
require a permanent `completion_fenced` check and failure transition after both
attestation and readback. The local-owner order and remote-owner order remain
separate protected branches. New mutations remove these physical-read/fence
checks, change new-attestation mode to readback, and reject hiding mandatory
guards in dead code. Existing full signature, scope, role, controller, original
deadline and journal-equality checks remain protected.

Two stale expected caller tuples were corrected to already registered Model
current-admission/readback callers. No caller edge was opened by this commit.

## Observed verification

`existing-scope-v1.log` is the complete output of the eight affected source-test
modules. It reports **51 tests passed**, including all 11 unchanged RootAdmin
tests and the 24 method IDs affected in the earlier fixed-627 failure.
The original test runner elapsed 159.119639912 seconds; unittest reported
157.939 seconds. Raw log: 11,492 bytes, SHA256
`9e52f45237e82fa2cbc4e19269ef967fb79fef99e2cf9e47ba3918a35120636a`.

The run was on the six-file working change based on dd4. Afterwards the two
updated TOML records were serialized as one function row per line for review;
an exact parsed-TOML equality check confirmed no semantic change. Therefore
this scoped run is not represented as a byte-pinned run of the published SHA.
Root owns the final fixed-source full qualification after integration.

All six uploaded Git blobs were read back and matched byte-for-byte, and the
remote tree matches the local source tree. The source manifest records those
identities. `git diff --check` passed.

The newly added Training/Selector read-only service and consuming-host factory
boundaries still need their own complete CALLERS registration and source gates.
No full caller proof, Rust build, native test or ordinary A/B/C/cold-restart
acceptance is claimed. Positive adoption: **0**. Complete NoUpdate/fallback:
**0**. Real daemon and Root cold restart: **0**.
