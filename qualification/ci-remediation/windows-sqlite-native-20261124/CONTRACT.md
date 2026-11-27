# SQLite namespace observations and native owner diagnostics

## Observed source and native result

The existing native job ran commit
`fb00e4422c293ffb318c9d7535e1991a3bbac707`, not this follow-up:

- Run `45434906085`, job `138589954514`.
- Early artifact `14941310872`,
  `hepta-windows-primitives-fb00e4422c293ffb318c9d7535e1991a3bbac707`.
- Downloaded ZIP SHA-256, checked against GitHub's artifact digest:
  `1750e547d3d9d65913e07a5d5251d86111660b44adc96ca416491bee8c2788cf`.
- Artifact `head.txt` identifies that exact head; `rustc.txt` reports
  Rust 1.96.0, commit `ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96`,
  host `x86_64-pc-windows-msvc`.
- Path primitive selection: **12 executed, 10 passed, 2 failed**, with 5
  unrelated tests outside the selector. Both failures persisted on retry.
- The original nine primitive cases all passed, including the retained old
  reader, one-character native rename, reparse/hard-link rejection, exclusive
  writer lock, directory namespace retention and actual writable-directory flush.
- Registry selection: **2 executed, 2 passed**, 26 outside its selector. This
  includes post-rename poisoning/reopen, not just successful publication.

The two new SQLite failures are retained as adverse results:

1. Ordinary `std::fs::write` creates a file which the exact same-handle private
   owner/ACL checks reject. The old generic PermissionDenied did not distinguish
   owner, ACL flags, ACE trustee or mask. This follow-up preserves every check
   and only reports that distinction, without emitting account SIDs. No owner
   mismatch or default-token-owner cause is claimed as already observed.
2. Creating a new child did not make the retained directory's identity, length
   and FILE_BASIC_INFO timestamps differ. The existing
   `verify_unchanged(before).is_err()` assertion failed. Timestamp metadata is
   therefore insufficient as the only directory namespace witness on this host.

Raw early-log hashes:

- `native-primitives.log`:
  `d7b352c4a39af6bcdfb0c45b617ee647fa28685a55d3c96108b89c1ca7790b65`.
- `registry-native.log`:
  `97f9f8ccb0647f338263ac3b6dc4e1f43d4e973d323be3e1ae51ed8895bd553f`.

## Change and preserved contract

Directory snapshots now contain the original same-handle metadata plus the
complete sorted list of observed child names, file IDs, attributes, lengths and
non-access timestamps. File `Snapshot` remains a distinct unchanged type.

Enumeration uses the retained native directory handle and
`GetFileInformationByHandleEx(FileIdBothDirectoryRestartInfo)` followed by
`FileIdBothDirectoryInfo`. Each new capture restarts. A mutex serializes the
handle's enumeration cursor. Two complete enumerations must agree and the
directory metadata must agree before and after them.

The buffer is explicitly 8-byte aligned. Record headers, UTF-16 lengths,
next-record offsets and duplicate names are checked. Budgets are 64 KiB per
page, 128 pages and 4,096 entries, with at most 255 UTF-16 code units per name.
Malformed, changing or over-budget results are errors. This does not add a
dependency, substitute a weak hash, read by an unbound pathname, or grant write
access to read-only inspection.

The original drift assertion remains. A new native test creates 300 long names
to exceed one enumeration page, checks repeated captures restart correctly, and
requires a later rename to be detected. The recovery parent holds the new
`DirectorySnapshot` by reference during revalidation.

This is an **endpoint namespace observation**, not an atomic snapshot,
continuous history, ABA detector, file-content write fence, or authentication
that a cold image is current. File content/identity checks and the independent
current-cut policy remain required. Ordinary timestamps may still be delayed;
this change does not claim that they prove content stability.

Strict owner equals effective TokenUser remains required. Administrators,
Everyone and other trustee substitutions are not accepted. No existing owner
or ACL is repaired. The default `PrivateDirectory` contract remains protected,
non-inheriting and owner-only. Any confirmed incompatibility of SQLite's actual
creation identity requires a creation-time solution, not a relaxed validator.

## Validation status for this follow-up

- Repository `just fmt` and `git diff --check`: passed.
- Independent actual-source Windows MSVC `cargo check --tests --locked
  --offline`: passed in 0.724 seconds, with nine source files unchanged before
  and after. This used an isolated 55-package graph and compiled the new test;
  it did not execute it and is not full integrated-lock qualification.
- Independent parser and contract review found no additional blocker.
- At the time the source was committed, new native enumeration and refined
  diagnostics were pending. The subsequent bounded result is recorded below;
  the old failing head has not been relabeled successful.

## Subsequent bounded native probe

Normal push workflow on the independent branch
`research/wsp-windows-fixtures-sqlite-probe-20261124-87d09924` executed source
`db23d3a74ea0edfe31c3d4f8bd574f7df8304684`, tree
`963bb11dfe2d46c2fba85043c9191fce9f3756d7`:

- Run `45438901826`, job `138604205211`, early artifact `14941023944`.
- Verified ZIP SHA-256:
  `f0bc9f7a0561bb99b18d3f81ebbd807d4de096031be97b6a1b55669c55f381a2`.
- Native primitive result: **13 executed, 12 passed, 1 failed**, 5 outside
  the selector. The previous namespace-drift failure and new 300-long-name
  multi-page/restart/rename case both passed. The original nine again passed.
- Registry result: **2 executed, 2 passed**, 26 outside the selector.
- The remaining test failed twice with the precise diagnosis:
  `storage object owner differs from the effective token user`.
  This establishes owner inequality on this runner. No concrete owner SID was
  collected, so this receipt does not identify it as Administrators or any other
  group. The exact owner requirement was not relaxed.
- After the early ZIP and its exact head were verified, the separately
  authorized budget stop cancelled **only this probe**. GitHub's independent
  final readback is `completed / cancelled`, updated `2026-11-24T16:38:26Z`.
  This is partial native evidence, not a successful complete workflow or
  consumer qualification. The ordinary `fb00` run was left running.

Primitive raw-log SHA-256 is
`7e5e4447947aee3da4d0ecb029669a8ea25bfc26f88fb0130ff41e1387aadc35`;
registry raw-log SHA-256 is
`08a57112582dbe782fb2fc31558ac00e7287b2ac62d26873acc8063e5c15c736`.

The namespace repair therefore has positive native evidence while the ordinary
SQLite file creation owner remains a genuine open requirement. Windows assigns
a new object's default owner from the effective token's `TokenOwner` when no
explicit owner is supplied. An inheritable DACL alone is not an explicit owner
at creation. A future creation-time solution must preserve same-user identity,
exact owner checking and absence of repair; changing process-wide token state
or accepting a broader owner is not qualified by these results.

## Primary API contracts

- <https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex>
- <https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info>
- <https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ne-minwinbase-file_info_by_handle_class>
- <https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object>

The file-ID documentation explicitly limits uniqueness over time. This code
does not treat a file ID alone as a lifetime or currentness proof.
