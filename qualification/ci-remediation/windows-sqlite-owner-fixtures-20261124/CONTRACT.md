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

## Subsequent native owner-control qualification

The bounded Windows probe at source
`051be3cda3aad7a145830884a45999f2e549278f` executed all 14 selected private
path cases successfully; 5 other cases were outside the selector. Registry
ownership and post-rename poisoning separately passed 2/2, with 26 other
cases outside that selector. The two test-source files in this source are
byte-identical to fixture commit
`640825cbfe71d978991a30959b52a0b60a509895`; blob IDs and SHA-256 values are
recorded in `native-probe051-receipt.json`.

The ordinary database-shaped and WAL-shaped files each independently reported
`ordinary_creation_owner_matches_effective_user=false`. Thus this runner
executed the wrong-owner rejection, unchanged security descriptor/contents,
and explicit-owner inherited-DACL positive controls. The ordinary-creation
matching-owner branch did not execute in this runner; a test that handles both
contexts is not evidence that both environments were exercised.

The probe's overall conclusion was **cancelled**, after its early evidence was
preserved and a separate C-VFS build step failed. The state consumer step was
cancelled, and cognitive and later consumer selections were skipped. These
primitive successes do not qualify the C-VFS or SQLite consumers and do not
turn the complete probe into a successful workflow. No assertions, production
owner checks, or security descriptors were relaxed to produce these results.

- [Probe run and job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45451454733/job/138649381190)
- Public early artifact: `14947368172`, 4,418 bytes, included unchanged as
  `native-probe051-artifact.zip`.
- ZIP SHA-256, verified against GitHub's digest:
  `617b71211f66981e583f7b0e5ea48c28f52eb4eb8da6cd21771ad16cbf21bffc`.
- The receipt records all member hashes, unique test names, source pins, and
  the observed owner booleans. Repeated nextest summary output is not counted
  as additional execution.

## Primary references

- [Owner of a new object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)
- [Security descriptors for new objects](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptors-for-new-objects)
- [InitializeSecurityDescriptor](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-initializesecuritydescriptor)
- [SetSecurityDescriptorOwner](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setsecuritydescriptorowner)
- [Absent DACL versus a present null DACL](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setsecuritydescriptordacl)
