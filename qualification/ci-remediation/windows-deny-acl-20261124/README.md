# Windows deny ACL repair: source and compile qualification

## Observed failure

The Windows 2/4 job for run `45104012523`, job `137461937853`, on source
`07c8994f2402a58f6b59eb648c801fc40c6e2b96` executed the actual native test
`token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes`.
Its repeated repairs were `(true, true, true)` instead of the required
`(false, true, false)`. The preceding write-denial assertions succeeded.

The original decoded job log has SHA-256
`bf49ce6af4b1c7fef8288517872f8e335db9d678eebd05097cfced9deebdf49f`.
[Original public job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45104012523/job/137461937853).

## Repair

Source commit: `3689e8f3d7d3dfff3f9421dc35274dafd42f3e25`.

Files use an effective object-only deny; directories use an effective
object-and-container-inheritable deny. A file deny does not require the
directory-only `FILE_DELETE_CHILD` right. New ACEs contain fully mapped file
rights rather than redundant generic flags. Existing ACEs are mapped before
comparison, and only a complete, leading, explicit, unconditional deny with
the correct scope can justify skipping a repair.

The target type, existing DACL, and replacement DACL are accessed through the
same retained file handle. The leaf must not be a reparse point. This guarantees
that inspection and installation target the same opened object. It does not
prove ancestry safety, prohibit renaming that object, or prove propagation to
every descendant. In particular, omitting delete sharing on an attributes and
security-only handle must not be described as a rename-resistant path lock.

Two new native tests compare object versus recursive scope and perform actual
repeated read/write deny installation on both a file and a directory. The
original partial-delete-deny assertion `(false, true, false)` is unchanged.
The existing failed-update test still requires the precise error and now uses
fallible test control flow instead of a Clippy-denied `expect_err` call.

## Executed checks and limits

- Rust 1.96.0 `cargo check --tests --target x86_64-pc-windows-msvc` compiled the
  actual repository ACL, token, winutil, and associated test source through an
  isolated 27-package manifest. It did not execute Windows tests. Its initial
  resolver used anyhow 1.0.105; that first result is retained separately.
- Final `just fix` and non-fixing `just clippy` both exited zero with the owning
  workspace's Clippy lint settings and pinned workspace versions: anyhow
  1.0.103, tempfile 3.27.0, pretty_assertions 1.4.1, and windows-sys 0.52.0.
  Both commands compiled the Windows test target. Source hashes before and
  after those commands are equal. Two existing missing-safety-doc warnings in
  unchanged token helpers remain visible in the logs.
- Repository `just fmt` and `git diff --check` passed. An independent source
  review found no blocker within the stated repair scope.
- Native Windows execution and the combined workspace build are pending.

## Separate deletion-confinement failure

This patch is **not** a fix or qualification for the distinct sandbox deletion
escape. The same original job observed outside-file and outside-directory
deletion despite blocked write/create attempts. Its unified-exec test also
observed deletion of an outside file and protected `.git` directory. Those
failures remain open until an effective execution boundary is independently
verified. No expectation was weakened, test skipped, or access widened to
claim those failures were repaired by the ACE idempotence change.

## Primary references

- [ACE inheritance and generic-right mapping](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)
- [SetSecurityInfo and child propagation limits](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)
- [MS-FSA share access algorithm](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/82b364ce-6d7b-422f-8d88-4db32eea809a)
- [CreateRestrictedToken flags and restricting-SID checks](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [DeleteFileW: file DELETE or parent DELETE_CHILD](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
