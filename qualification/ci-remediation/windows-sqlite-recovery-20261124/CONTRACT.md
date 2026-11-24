# Native Windows cold recovery and private SQLite candidates

Later native execution exposed a real default-owner mismatch in ordinary file
creation. The original preparation account below is retained; the measured
failure, revised independent owner controls, and still-required actual SQLite
creation qualification are recorded in
[the owner fixture contract](../windows-sqlite-owner-fixtures-20261124/CONTRACT.md).

## Scope and status

This patch implements Windows retained-source inspection, bounded cold-image
deserialization and new-candidate materialization. It also removes the Windows
ACL no-op in the cognitive owner and uses the already introduced native rename
and directory-flush primitives. Existing Unix checks remain enabled.

At preparation, `just fmt`, `git diff --check` and actionlint for both changed
workflows completed successfully. The parent independently compiled the actual
path-utils production source and its 12 Windows tests with Rust 1.96 for
`x86_64-pc-windows-msvc` in an isolated 55-package graph: exit 0, no warnings,
6.29 seconds, matching before/after source hashes. The subsequent change in that
layer only clarified the `remove_created(File)` caller precondition in rustdoc.
This compile check did not execute Windows code, compile the complete consumers,
or validate the final integrated Cargo/Bazel lock. Native and Unix execution is
required by the normal workflows below; no passing execution is claimed here.

## Two explicit directory contracts

| Type / operation | Existing-object policy | Creation / effects |
| --- | --- | --- |
| `PrivateDirectory` | Current token user owns the object; protected DACL; one explicit full-access ACE for that user; no inheritance flags | The existing strict default remains unchanged |
| `PrivateSqliteDirectory::prepare` | Current token user owns the directory; protected DACL; one explicit full-access owner ACE with OI/CI | Atomic private directory creation, or validation without ACL repair; real directory flush |
| `PrivateSqliteDirectory::open_writable` | Same SQLite directory policy | Existing directory only; no implicit creation; real flush required |
| `PrivateSqliteDirectory::inspect` | Either of the two protected owner-only directory policies | Existing directory only, read access, no creation, ACL repair, or flush |
| SQLite file inspection | Current token user is owner; one full-access ACE for that user, either explicit/protected or inherited/unprotected | Same-handle validation; never adds an administrator/SYSTEM/group exception |

The SQLite directory is a separate type because SQLite creates and deletes its
own WAL/SHM/journal files. The inspected upstream `libsqlite3-sys` 0.39.1 bundled
`sqlite3.c` passes a null security-attributes argument in both ordinary
`winOpen` and the shared-memory file open. Windows inherits the directory ACE
for these files. The three new path-utils tests exercise actual ordinary file
creation, not a helper that supplies the expected child security descriptor.

Owner equality is still required on every file. A host whose token defaults
newly created files to a different owner does not qualify by assumption; native
tests must expose that failure. No token-owner mutation or broad-owner exception
is introduced. Existing broad or differently configured roots are rejected,
not silently converted. Missing cognitive ancestors are created individually
with native no-reparse opens and private descriptors; existing ancestors are
not chmod-ed or given new ACLs.

## Source and candidate boundaries

The Windows source guard retains the directory and database, plus present
WAL/SHM/rollback-journal handles or explicit absence facts. Every open uses
`OBJ_DONT_REPARSE`; regular files additionally use the existing non-directory /
open-reparse-point flags. All handles must refer to local NTFS, with persistent
ACL support and a local volume GUID. Each file must be regular and singly linked.

Snapshots include volume serial, file ID, attributes, link count, length,
creation time, last-write time and change time. The same handles and their
original namespace bindings are rechecked. Access times are deliberately not
identity facts. These checks detect drift; they do not make file contents atomic
or authenticate currentness. The independent complete logical current-cut
witness and integrity checks retain that responsibility.

The cold-image path rejects every sidecar, including an empty one. It copies at
most 128 MiB from the retained read-only descriptor, revalidates the bundle and
deserializes only the private copy with SQLite READONLY/FREEONCLOSE. Reconnect
deserializes that same copy. `query_only = OFF` must not make it writable.

Materialization reads the source database and optional WAL/journal from retained
descriptors with the previous 128 MiB per-file / 256 MiB bundle limits. SHM is not
copied. Only after revalidation can exclusive `FILE_CREATE` candidate files be
created relative to the retained private root. They are explicitly protected
owner-only files. Each file and the directory are flushed, and a partial failure
removes only actual retained handles created by that attempt. A preexisting
candidate or WAL is never overwritten or deleted.

`remove_created(File)` is not a branded directory capability: its caller must
retain and pass the exact handle returned by that directory's `CreateNew`.
All production callers in this patch do so. Kind/owner/ACL checks on an arbitrary
`File` alone do not prove parent-directory membership.

The cognitive owner keeps the directory handle with its shared/exclusive store
fence, validates the candidate's full current cut and integrity under the
existing authority ceremony, checkpoints and reopens the copy, then replaces
the active pointer with the native handle-relative atomic rename. A successful
rename followed by a failed directory flush retains the possibly-active pointer
and candidate and is reconciled as `Indeterminate`.

**The two original filename recovery writer entries remain `Unavailable`:**
`open_immutable_recovery_pool` and
`open_identity_bound_durable_evidence_pool`. A normal SQLite pathname is not a
qualified descriptor-backed VFS. The new writable candidate is a separate
private generation; SQLite never opens the suspect source filename.

## Required qualification

The existing Windows workflow retains its original primitive, registry and
consumer tests, then adds:

```text
just test -p codex-utils-path --lib --locked windows_private::tests::
just test -p codex-state --lib --locked -E 'test(sqlite_recovery::)'
just test -p codex-hepta-memory --lib --locked -E 'test(cognitive_store::recovery::) | test(cognitive_store_tests::)'
```

There are three added path-utils tests and four new Windows state tests. The
existing two state cold-image tests, four cognitive cold-image tests and the
byte-identical replacement/current-witness test now also run on Windows. The
native state tests cover namespace replacement, hardlinks, sidecar appearance,
ACL broadening, content drift, reparse roots, absent roots, exclusive candidates,
SHM exclusion and partial-copy cleanup. Existing revoked/old/tampered witness,
exclusive writer fence, post-rename ambiguity and writable generation tests
remain required. No assertion is removed to bypass an unsupported platform.

The existing GNU fixture job reuses its compiled state/memory dependencies for:

```text
just test -p codex-state -p codex-hepta-memory --lib --locked -E 'test(sqlite_recovery::) | test(cognitive_store::recovery::)'
```

Both workflows run scoped `just fix` and require a clean diff. Both record the
actual integrated commit and upload logs. The integration owner updates both
locks; this patch adds only Windows workspace dependencies on `codex-utils-path`.

## Primary API references

- [Microsoft file security and default ACL inheritance](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [Microsoft ACE inheritance rules](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)
- [Microsoft ACE_HEADER flags](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-ace_header)
- [Microsoft FILE_BASIC_INFO and ChangeTime](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)
- [Microsoft GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
- [Microsoft NtCreateFile options and dispositions](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)

No real credentials, accounts, trading data, or Pocket4 checkpoints are part of
these fixtures or evidence. No power-loss durability simulation is claimed.
