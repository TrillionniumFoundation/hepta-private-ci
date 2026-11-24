# Native relative rename qualification

## Observed Windows result

Source `676d59ef602e59790a58614541bfb92325bdc71f` ran on Windows Server 2025
10.0.26100, image `windows-2025-vs2026` version `20261116.315.1`:

- [Run 45428321717, job 138566329525](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45428321717/job/138566329525).
- The private-path selection executed 9 tests: 7 passed and 2 failed. Nextest
  also reported 5 tests outside this selection as skipped.
- Both failures returned Windows error 87, `InvalidInput`, from the atomic
  rename call: `one_character_target_uses_a_complete_rename_header` and
  `private_state_replaces_atomically_and_reopens_with_the_same_acl`. Both also
  failed the configured retry.
- The 7 passing tests cover broad-DACL rejection without repair, reparse roots
  and ancestors, reparse children/replacement targets, hard links and invalid
  leaves, exclusive writer locking, retained-root rename resistance, and the
  actual writable-directory flush call.
- The flush diagnostic recorded `ordinary_directory_open=Some(5)` and
  `writable_directory_flush=None`. This proves these fixture calls' observed
  behavior; no power-loss experiment was performed.

The job uploaded artifact `14937547950`, named
`hepta-windows-durable-676d59ef602e59790a58614541bfb92325bdc71f`, with provider
digest `sha256:5d14d2c3dd9660317cd157220d2688b9e79aa930d1d3d2ce5c7c80ebed03f22c`.
The remaining registry/consumer/Clippy steps stopped during compilation:
`durable_payloads.rs` lacked the `File` import, and `rollout/src/list.rs` called
the removed `Timestamp::timestamp_nanos_opt` method. Those are separate fixes;
the job did not execute the downstream consumer assertions.

## Correction under qualification

The rename implementation calls user-mode `NtSetInformationFile` with native
`FileRenameInformationEx` class 65. A `repr(C)` native header contains the flags,
retained directory handle, UTF-16 byte length, and flexible filename array.
The allocated and submitted length includes the complete header plus the
filename bytes, including for a one-character destination.

`REPLACE_IF_EXISTS | POSIX_SEMANTICS` preserves replacement with an already-open
old reader. The source handle is synchronous and remains open through the call;
the target remains a validated single leaf relative to the retained directory
handle. ACL validation, reparse rejection, link-count checks, source/target
identity checks, file flush, directory flush, and error propagation stay intact.
The correction leaves the two failing test functions unchanged.

The observed failure identifies the previous Win32 call boundary. It does not
establish the internal cause of error 87. Current Microsoft documentation
explicitly allows a relative filename and directory handle in `FILE_RENAME_INFO`,
so this change makes no claim that the prior `RootDirectory` argument violated
that documented contract. Native execution must establish whether the direct
NT operation resolves this runner's failure.

## Validation boundary

`just fmt` and `git diff --check` passed. An independent Rust 1.96 MSVC
`cargo check --tests --locked --offline` of the actual path-utils source passed
in 12.97 seconds using the existing isolated 55-package graph. All 8 source-file
hashes matched before and after the check. The changed handles source SHA-256 is
`e927417b72ac0a6c2b37567b207e58bc4611d15b39365c9ffbb794abe3b27763`.
This check executed zero native tests and does not qualify the integrated lock
graph, runtime rename behavior, SQLite recovery, or downstream consumers.

The existing normal Windows job must execute the same two failing tests, retain
the seven passing attack checks, and run the additional SQLite/consumer checks
on the integrated candidate. Its early primitive artifact upload makes the
small-test results available before the consumer compilation finishes; every
later step and the final complete artifact remain enabled.

## Primary API references

- [FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)
- [FILE_RENAME_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)
- [FILE_INFORMATION_CLASS](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ne-wdm-_file_information_class)
- [NtSetInformationFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntsetinformationfile)
