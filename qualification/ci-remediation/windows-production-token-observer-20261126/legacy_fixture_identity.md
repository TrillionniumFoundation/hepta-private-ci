# Explicit ordinary identity for the owned legacy fixture

This candidate changes the authorization premise of one test's newly created,
empty temporary directory. It does not change a production token, production
ACL, public execution entry point, timeout, retry policy or expected result.
It has not been compiled or run on Windows.

## Actual evidence motivating the fixture change

The exact 2c6 source ran the original two-case selection once. Strict Clippy
passed, but both native cases failed. The legacy command emitted five access
denials and left all three allowed files in place. Its actual child primary
token had Administrators as deny-only, with Users and Authenticated Users
enabled. The observed selected token facts matched its launch token. Its
pre-spawn descriptors granted full access to Administrators and System, while
Users had read/execute plus directory creation rights. They lacked the
Authenticated Users grant seen before the earlier 04c3 run, where the legacy
assertion passed. The source of that earlier inherited grant is unknown.

The token observations are eight selected field classes, not a complete or
atomic token identity proof. Redacted facts that agree across runs do not
establish equality of hidden SIDs. The separate production factory still
allowed parent DELETE_CHILD while denying target DELETE, and its outside file
was actually deleted. These facts must not be conflated with missing ordinary
identity authorization in the legacy fixture.

## Frozen fixture contract

Before creating any test children or starting sandbox setup, the helper takes
the owned `TempDir`, verifies that the current thread is not impersonating,
opens its root with no-follow semantics and retains that handle. The root must
be an actual empty directory. A null DACL, deny ACE or unsupported ACE is a
fixture error; it is not repaired.

The helper captures the actual process TokenUser. It adds exactly one grant
for that SID: `FILE_ALL_ACCESS`, inheritable by files and directories. Existing
entries remain the input to `SetEntriesInAclW`. No World or Authenticated Users
ACE is added. The only security mutation is `SetSecurityInfo` on the retained
empty fixture-root handle, before any child exists. No user directory, account,
pre-existing workspace, production policy or other test root is modified.

The new ordinary-user grant includes target DELETE and parent DELETE_CHILD.
It applies equally to the future allowed roots, the outside negative control,
and the protected `.git` directory. That makes the negative controls stronger:
their survival must result from the sandbox policy, rather than the ordinary
identity lacking deletion rights in the first place. It does not grant any
production restricting capability and does not remove the `.git` deny.

The same retained handle supplies complete before/after descriptor reads.
The whole installed DACL must exactly equal the ACL returned by
`SetEntriesInAclW`; raw owner and group SIDs and file attributes must be
unchanged. A readback mismatch fails the fixture. Original and new descriptor
structure are logged under `HEPTA_LEGACY_FIXTURE_ACL` with a shared 16 KiB cap;
raw SIDs are retained only in the bounded comparison buffers, not printed.
Those buffers and all handles are released before sandbox setup begins.

## Preserved behavior and evidence boundaries

The original five command actions, 5-second child limit, 10-second exit/drain
deadlines, complete final tuple, outside file content and `.git` directory
assertions remain unchanged. The 18 existing descriptor records, 15 factory
records, actual-child token observation, original two test identities, eight
controller commands, 20-minute job limit and zero retries are unchanged. No
new native command is added. All previous failures and differing results are
retained under their original source identities.

The descriptor reader is extracted to accept an already retained file handle;
the previous path-based reader delegates to that same body and preserves
descriptor-before-file drop order. The mutating fixture helper is separate
and only reachable from the selected test setup. There is no new product API.

Passing setup establishes an ordinary-identity premise; it does not establish
restricted-token confinement. If parent DELETE_CHILD still bypasses the
production boundary, the original outside or `.git` assertion must fail.
The independent fail-closed branch, the earlier minimal-rights matrix, and
PSEC backend research remain distinct. No publication or native execution is
represented by this source candidate.
