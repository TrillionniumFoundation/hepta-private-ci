# Windows44 result and the remaining production authority boundary

The mutation-only deny correction now has direct native support. It does not
close the production outside-delete defect. There is no justified flag-only or
SID-list-only Windows45 replacement that preserves the present raw factory's
ambient-read behavior for arbitrary unprepared objects.

This is a source-bound conclusion for Windows44, PR #5270, commit
`883b85f2c0198e9373022e8082d866c080178c0a`, tree
`6634442bb8fb0bc8b1f86278ff4fffefdaafd23e`. `SOURCE_BINDING.json` verifies sixteen
inspected source files and rehashes all eleven tree objects in the complete
80-entry source-subtree response. Its current subtree is linked through the
already audited four-tree reconstruction to the exact native checkout. This
report does not introduce a production candidate or run a new native test.

## What the original native run establishes

Run `42352197933`, attempt 1, Windows job `128343024490`, actually checked out
`194e8fa6ba96e0b717e4ca25612b1f02720cb1cf`, whose tree equals the source above.
The owning Windows sandbox unit target failed after 114.1 seconds without a
cached target marker. The later complete 38-job API records whole-run failure.

| Fixed case or observation | Actual result | Limit |
| --- | --- | --- |
| Prepared full-restriction probe | `ok` | Direct case result; no captured F0-F4 numbers were emitted |
| Complete-deny mapped-mask unit | `ok` | This specific unit, not all ACL behavior |
| Normalized recursive/effective six-right unit | `ok` | This specific unit, not stale-ACL migration |
| Fresh generic-read/data-mutation unit | `ok` | New correctly created deny mask |
| Original broad-identity regression | `FAILED` | Outside overwrite/create denied; both outside deletion calls returned success |
| Original legacy regression | `FAILED` | Actual tuple remained `[0, false, false, false, None, false]` |

`SAFE_NATIVE_OBSERVATIONS.json` contains zero FULL records. A successful
libtest case can suppress captured stdout; therefore no F0-F4 access masks,
individual operations, token values or cleanup fields are reconstructed from
the passed probe or inherited from Windows43. The original probe source and
its final assertions are unchanged, so its direct `ok` is meaningful without
inventing those absent records.

The original broad assertion is the four-element result of `Result::err()`
for overwrite, create, remove-file and remove-directory. Its actual values are
`[PermissionDenied, PermissionDenied, None, None]`; here the last two `None`
values mean those deletion calls succeeded. The legacy tuple separately uses
`read_to_string(...).ok()` and `is_dir()`. Its `None` and `false` do not retain
the underlying error and cannot alone distinguish absence from a failed query.
Its expected tuple remains `[0, false, false, false, Some("outside"), true]`.

Only the first complete pretty-assert hunk for each fixed case was decoded.
Later printed headers are explicitly `NOT_PARSED`. A 149-line normalized
console context is exactly repeated around the two sets of case-summary
lines; it is not an independent invocation. The initial two local assertion
parser failures and both predecessor scripts remain preserved.

## The exact production call chain remains different from the probe

| Bound source | Actual production or fixture behavior |
| --- | --- |
| `token_tests.rs` | The broad regression directly calls `create_workspace_write_token_with_caps_from(base, [cap_a, cap_b])`; no read-root path or preparation receipt enters that API |
| `token.rs` | All six exported raw factory routes reach the shared constructor; it still sets `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED` |
| `token.rs` | The legacy writable route excludes Logon/Everyone from its restricting list, but remains in write-only restriction mode |
| `unified_exec/backends/legacy.rs` | The actual legacy regression route requires full-disk-read policy and rejects additional deny-read overrides |
| `spawn_prep.rs` | `prepare_legacy_session_security` creates the token from write-root SIDs before `apply_legacy_session_acl_rules` grants writable paths and applies carveouts |
| `lib.rs` | The separate capture route has the same full-read admission and token-before-ACL preparation order |
| `cap.rs` and `spawn_prep.rs` | `caps.readonly` is persistent and is passed to `add_allow_ace` on allowed paths; it is not a newly issued globally read-only authority |
| `token.rs` | Ordinary capability inputs receive `GENERIC_ALL` in the default DACL; a distinct read role cannot be inserted into that vector unchanged |

Windows44 changes only `acl.rs` and `acl_tests.rs`. New Write denies contain
the six required mutation bits, without the generic sources of READ_CONTROL
and SYNCHRONIZE. Existing broader deny ACEs remain preserved. The mutation
mask fix, migration of existing ACLs, and replacement of the token enforcement
mode are separate questions. This run provides no new stale-ACL migration
evidence and no basis for deleting an existing third-party ACE.

Microsoft describes a normal restricted token as requiring both the enabled
identity check and the restricting-SID check. The write-only flag limits when
that second list is considered. Removing it changes reading as well as
mutation authorization; adding an ordinary identity to recover reading makes
that identity an alternative grant match in the second check. [1, 2]

## A narrow counterexample to a token-only replacement

The following is a conditional access-control argument, not a newly executed
Windows fixture and not a claim that every Windows enforcement mechanism is
impossible. Its scope is the existing token factory and ordinary DACL checks,
without an additional object or access-mediation provider.

Consider an outside regular file with a non-null DACL, owned by someone other
than the sandbox principal. Assume no applicable deny, owner shortcut, enabled
privilege bypass or extra read-only matching ACE. Its only relevant allowed
identity Q grants ordinary file reading and DELETE, but not WRITE_DAC. The
currently permitted caller can read that file. Neither current writable
capability nor a newly invented R SID has an ACE there. The parent need not
grant FILE_DELETE_CHILD for this counterexample.

With full restriction, excluding Q from the restricting list denies the
required read. Including Q grants both that read and DELETE through the same
ACE. SID_AND_ATTRIBUTES does not provide a per-SID access-mask cap. Turning Q
into a deny-only identity also removes its positive read grant. A new R value
does not create an ACE. The caller's ability to read that object does not imply
the WRITE_DAC permission needed to prepare a new read ACE. [1, 3]

This counterexample does not require guessing the complete DACL of the
original failing fixture. It shows why the current input interface cannot
generically synthesize ambient read plus mutation denial by changing only its
flag or SID list. Separate integrity, broker, container or filesystem
enforcement would be a different mechanism with its own admission contract;
none is established by this argument or by the present source.

## What a real PreparedAuthority producer must supply

A viable full-restriction route needs a privately constructed preparation
object before token creation. A public constructor accepting arbitrary SIDs or
an asserted setup-success Boolean would not supply the missing authority.

1. **Actual base identity and policy.** The producer receives the admitted base
   token, the original read/write policy and launch resources. It distinguishes
   the current ambient full-read promise from a finite prepared-root policy;
   silently substituting a finite list would change supported behavior.
2. **Independent read role.** It owns a distinct R SID and the grants needed for
   the declared resource class. R never inherits persistent write-capability
   grants and is not put into the existing GENERIC_ALL capability default DACL.
3. **Complete preparation and permission to perform it.** It obtains the needed
   object authority, verifies the exact effective rights and covers protected
   descendants, inheritance exceptions and later resources promised by the
   declared policy. Permission to read is insufficient to modify a DACL. A
   held object handle alone is not a security-descriptor freeze. [3]
4. **Write and runtime separation.** Active write-root roles and protected-child
   rules remain intact. Executables, libraries, registry/IPC, standard handles
   and child-created object defaults need the appropriate separate grants;
   arbitrary existing child applications do not automatically use a new broker.
5. **Lifetime and post-creation verification.** Preparation survives through
   launch/use and has an explicit cleanup boundary. Token queries verify the
   effective restricting set, base identity and privileges; an already
   restricted base can intersect the requested set. No fallback restores a
   broad identity or drops full restriction when an admission step fails. [1]

The existing elevated path does not provide this object. Its read setup may
skip a root already readable by built-in identities and grants the shared
sandbox-users group rather than a distinct R. Full setup may launch the read
helper asynchronously, or omit launch because its mutex already exists.
Neither outcome is a request-specific completed R-grant receipt. The command
runner still calls the factories that add the token user and broad identities.
Routing the legacy function to this existing backend is therefore not a
drop-in proof of the missing read authority or outside-delete boundary.

## Smallest justified next step

**No Windows45 product patch is ready under the unchanged current interface
and ambient-read promise.** The next implementation boundary is the production
authority producer and its admitted resource class, followed by its token and
launch consumers. It is not another permission-mask change or a native probe
with the same inputs. A reviewable implementation sequence would be:

- define the private preparation ownership and exact read-coverage contract;
- implement and verify a producer capable of fulfilling that contract under
  the original policy, including runtime access and failure cleanup;
- then remove write-only restriction for that admitted route and migrate all
  real callers, retaining the original outside-read, inside-write/delete and
  outside-mutation-denial assertions.

The direct broad regression provides only a base token and two write SIDs. It
does not call such a producer. Changing that test to supply new preparation
would test a new API contract; it cannot be silently counted as the original
raw factory becoming correct. Returning an unsupported error from the old
factory would be containment rather than fulfillment of its positive behavior.
An unused typed wrapper would likewise not close a production blocker.

This report preserves the passed prepared mechanism, the two failed production
regressions, and the open ACL migration as distinct facts. There is no new
source candidate, privilege, environment change, retry, or native invocation.

## Primary references and local evidence

1. Microsoft, [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken), read 2026-11-07: full versus write-only restrictions, SID attributes and existing-list intersection.
2. Microsoft, [Restricted Tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens), read 2026-11-07: the two-check access model.
3. Microsoft, [SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo), read 2026-11-07: DACL modification authority and propagation limitations.
4. Microsoft, [File Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights), read 2026-11-07: shared generic rights and file access semantics.
5. `SOURCE_BINDING.json`: exact sixteen sources; no broad repository-current claim.
6. Windows44 `SAFE_NATIVE_OBSERVATIONS.json` and `PRETTY_ASSERTION_VALUES.json`: fixed native enums, source/checkout identity and explicit missing-data limits.
7. Frozen `round3_native/windows_read_authority_37/FEASIBILITY.md`: earlier interface report; its prospective mechanism status is historical and is not rewritten by this report.
