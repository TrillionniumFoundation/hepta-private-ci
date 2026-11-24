# Creation-time owner controls for the Windows SQLite fixture

## Actual finding retained

The bounded native probe at
`db23d3a74ea0edfe31c3d4f8bd574f7df8304684` ran 13 primitive cases: 12 passed,
and the ordinary-file inheritance case failed twice with
`storage object owner differs from the effective token user`. The registry
selection passed 2/2. The probe was intentionally cancelled after its verified
early artifact; it was not a successful full workflow.

The observation establishes file-owner inequality. It does not identify a
particular owner SID or prove that the actual TokenOwner field was queried.
The original positive assertion had assumed that inheriting the directory DACL
also supplied the directory's owner. That assumption is false for a creator
whose default object owner differs from its effective token user.

## Revised native fixture contract

Production security code and the ordinary file creation operation are unchanged.
The test still uses ordinary `fs::write`, which provides no explicit security
descriptor, to create a database-shaped file and a WAL-shaped file. An
independent `GetSecurityInfo` observation from each retained test file handle
compares its actual owner with the already validated private root's owner.

| Independently observed owner | Required production result |
| --- | --- |
| Equal to the private root's effective-user owner, with its one inherited full-access ACE | Inspection must succeed |
| Different from that owner, even with the same one inherited full-access ACE | Inspection must return `PermissionDenied` |

Both paths require unchanged owner, DACL control flags and complete ACL bytes
before and after inspection, plus unchanged file contents. Only an equality
boolean is logged; raw SIDs are not printed. This adapts the expected outcome to
an independently measured Windows fact, not to the validator's success or error
text. A wrong-owner success and a matching-owner failure both fail the test.

A second, separate native control creates two new synthetic files with
`CreateFileW(CREATE_NEW)`. Their creation descriptor contains an explicit owner
from the validated private root and leaves `SE_DACL_PRESENT` clear, allowing
the private root's DACL to be inherited. It does not set a present-but-null DACL.
The test independently verifies the resulting owner, unprotected DACL, and one
inherited full-access owner ACE, then requires normal production inspection to
succeed. This control is explicitly a synthetic Windows creator, not an
unmodified SQLite success claim.

The strict `PrivateDirectory` rejection of an inheritable root, read-only
inspection of a protected strict file, and rejection of writable sidecar access
under a strict root are preserved. No token, process default DACL, existing
owner, or existing ACL is changed. Every explicit-owner fixture uses exclusive
new-file creation; it cannot repair or overwrite an existing object.

## Qualification boundary

The test has the same name and selection; the total selected primitive count
remains 14 after the preceding canonical-name case. All changes here are in
test-only files. The actual SQLite DB/WAL/SHM/journal/temp creation path requires
its independent opt-in VFS implementation and execution tests.

Before integration on 2026-11-24:

- Actual path-utils and tests, Rust 1.96.0 MSVC isolated 55-package graph:
  `cargo check --tests --locked --offline`, exit 0, 0.865 seconds.
- Actual normal workspace and existing lock:
  `just fix -p codex-utils-path --target x86_64-pc-windows-msvc --locked --offline`,
  exit 0, 2.565 seconds; no source changes, existing unused `imbl` patch warning.
- After replacing the fixture reader's numeric flags with the equivalent
  Windows API constants, the same scoped workspace compilation/Clippy command
  passed on the final source in 2.389 seconds, again without source changes.
- All ten path-utils source hashes matched before and after each command.
- Native execution for these revised controls is pending. No failure count is
  retroactively changed, and no SQLite functionality is declared closed.

## Primary references

- [Owner of a new object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)
- [Security descriptors for new objects](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptors-for-new-objects)
- [InitializeSecurityDescriptor](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-initializesecuritydescriptor)
- [SetSecurityDescriptorOwner](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setsecuritydescriptorowner)
- [Absent DACL versus a present null DACL](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setsecuritydescriptordacl)
