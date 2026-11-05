# Legacy Windows deletion boundary: containment only

Status: **P0 OPEN**. This change stops direct same-user legacy sandbox execution.
It does not restore the original full-disk-read and root-scoped mutation contract.
The original native tests remain mandatory, unchanged, and are expected to reject
this containment-only candidate rather than report functional acceptance.

## Original execution and evidence

The failed [Windows job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41966043093/job/127043294552)
executed merge commit `9459cf8a4e5e43d6645e2b619b86455132c7df67`, not the PR head
alone. Its head was `3419b6ac8adf5b47b140e553f5fff9e74c98d352`, with base
`732e934ba496d90fbe042b8d41d479ef901643e5`. The containment patch starts from R3
`4e31abc907f09740d402d1ddef7a1d2fe0a366a6`.

`original-job-127043294552.log.gz` preserves the complete decoded original job
log. `provenance.json` records its uncompressed and compressed SHA-256 values,
runner identity, and the hashes of both complete original test files.

The original token fixture grants inheritable `FILE_ALL_ACCESS` to logon and
Everyone, gives the outside directory a different capability, and still requires
outside reads. Its outside write/create attempts were refused, but both actual
outside delete operations succeeded. The original legacy child also deleted the
outside file and protected `.git` directory. Its host-side result was
`(0, false, false, false, None, false)` instead of
`(0, false, false, false, Some("outside"), true)`.

These observations concern owned temporary fixtures. They do not establish that
real user files were deleted.

## Cause and the incomplete one-line alternative

The production token uses `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`.
The recorded direct target `DELETE` access check rejected access, but its parent
`FILE_DELETE_CHILD` check allowed it; native deletion still succeeded. Removing
that right from the capability allow ACE and adding a target deny did not remove
the ambient identity's parent-directory authorization.

The original diagnostic control removes only `WRITE_RESTRICTED`, retaining the
same restricting SIDs and security descriptor. Its `AccessCheck` result denies
both parent deletion and the required outside read. This is an access-check
control, not a successful native deletion run under a replacement token.

Microsoft documents [the parent-directory deletion alternative](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/irp-mj-set-information3)
and [the scope of WRITE_RESTRICTED](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken).
No extra flag has been qualified here that preserves the original ambient reads
while constraining all mutations. Changing the original fixture to finite read
roots, or adding a read-capability ACE to outside, would test a different contract.

## Containment behavior

`LegacyWindowsSandboxIsolationUnavailable` is returned before direct legacy
spawn/capture setup, capability persistence, ACL changes, or child launch.
Direct same-user token constructors, including the read-only constructors, also
refuse admission. The managed legacy preflight refuses before altering ACLs;
the pre-existing no-op for non-managed profiles is not sandbox qualification.

The source adds no retry with an unrestricted token and no new backend fallback.
The existing selector may route a workspace request to the separately provisioned
elevated backend. Dedicated-account `*_and_user_from` constructors and that
pre-existing routing remain separate from this direct-entry containment claim.
Neither backend selection nor the name "read-only" proves deletion isolation.

The availability impact is intentional and explicit: callers of these direct
same-user legacy APIs receive an error until a replacement enforces the original
contract. This draft must not be represented as a feature-complete repair.

## Verification and closing conditions

New admission regressions exercise the real factory, capture, preflight, and
session entry points, including TTY/stdin choices. They compare fixture contents
and DACLs and check that no home/capability state or child marker was created.
Those tests verify containment only.

The complete original `token_tests.rs` and `unified_exec/tests.rs` are byte-for-byte
preserved. No assertion, hostile ACL, operation, timeout, ignore marker, or expected
outcome is changed. The original Windows Bazel matrix and exact-head scope runner
remain enabled; the scope manifest only adds the admission tests.

The original tests returning the admission error are **failures**, not passes or
skips. P0 closes only when a replacement actually runs their original operations:
allowed workspace/TEMP/TMP mutation succeeds, outside reads succeed, outside
creation/overwrite/deletion is denied, and protected objects retain their content
and identity. Native target/parent deletion controls, rename/replace and recovery
must then qualify the same implementation and fixed source combination.
