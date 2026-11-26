# Production-token deletion observations (source candidate only)

## Status and scope

This candidate is based on `be271ddfa2a2d519a44112e4f176d2d8c3499c25`.
It adds bounded read-only observations to the existing
`token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`
case. No production function, token flag, SID list, DACL, permission mask,
filesystem operation, expected result, timeout, workflow, or retry policy changes.
It adds no Rust test identity and has not been compiled or executed.

The original case still requires all four outside operations to return
`PermissionDenied`, then checks original content and namespace. The retained
native failure at this source reports writes/create denied but file and directory
deletion allowed. The separate real-child regression also retains its original
outside-file and protected-directory assertions. Neither failure is closed here.

The controlled native-handle disposition result at
`9d64ed36d5923329e27006e58d428e353ab959d8` is a different contract: a full restricted
token with a DELETE-only handle marked three owned empty directories for deletion
and retained the Neither negative control. It does not qualify this production
WRITE_RESTRICTED token, arbitrary native children, or the original Win32 matrix;
the original matrix remains two passed and two failed tests. The alternative
permission-support experiment remains design-only.

## Facts and unresolved mechanism

The existing production factory passes
`DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED` (`0xD`), with no explicitly
disabled SID entries. The workspace-write factory excludes the ordinary user,
logon and World identities from its restricting SID list. Its actual capability
SIDs and post-factory token properties are observed here rather than inferred
only from arguments. Other product factories have different identity lists.

The pinned Windows SDK maps `FILE_GENERIC_WRITE` to `0x120116`; it contains
neither `DELETE` (`0x10000`) nor `FILE_DELETE_CHILD` (`0x40`). This is a mapping
fact. Microsoft's public WRITE_RESTRICTED description does not specify the full
kernel decision for every mixed access mask. A hypothesis that deletion avoids
the second check must remain a hypothesis until distinguished by evidence.

The existing production `WRITE_ALLOW_MASK` is `0x1301bf`: it already contains
READ_ATTRIBUTES and SYNCHRONIZE. Consequently, the minimal full-token directory
fixture's observed Win32/native access difference does not explain or repair
production outside deletion. Target DELETE and parent DELETE_CHILD are distinct
possible authorization routes; this candidate does not remove either grant.

An enabled ordinary SID may grant access, while a deny-only SID cannot satisfy
an allow ACE. Object ownership is not itself a documented DELETE grant. Actual
owner equality and ordinary/deny-only group facts are reported to avoid assuming
these properties from the process account or token-creation flags.

## Fixed six-query protocol

All six requests use the actual impersonated thread token obtained with
`OpenThreadToken(TOKEN_QUERY, OpenAsSelf=TRUE)`. OpenAsSelf controls authorization
for the query handle; it does not substitute a process token for the client token.
No new restricted token or impersonation scope is created by the observer.

| Order | Captured object | Exact requested access | Purpose |
|---|---|---:|---|
| 1 | `outside/keep.txt` | DELETE, `0x10000` | Target delete authorization |
| 2 | `outside` | FILE_DELETE_CHILD, `0x40` | Parent delete authorization |
| 3 | `outside/keep.txt` | DELETE + FILE_WRITE_DATA, `0x10002` | Target write-bearing mixed request |
| 4 | `outside` | FILE_DELETE_CHILD + FILE_ADD_FILE, `0x42` | Parent write-bearing mixed request |
| 5 | `outside/keep.txt` | FILE_WRITE_DATA, `0x2` | Write control |
| 6 | `outside/keep.txt` | FILE_READ_DATA, `0x1` | Read control |

Before freezing this candidate, the initial unexecuted proposal used SYNCHRONIZE
in rows 3 and 4. It was replaced with the explicit data-write/create bits above
because SYNCHRONIZE also appears in generic read and execute mappings. Neither
proposal has produced a new observation or native result.

The two descriptors are obtained once before impersonation, using read-control
handles with all three sharing flags and no delete-on-close. OWNER, GROUP and
DACL information are captured from the same opened handle; both handles close
before the original impersonated operations. The LocalAlloc-owned, validated,
self-relative descriptor memory remains alive throughout both observation phases.
No parent handle with delete authority is retained.

The six checks run once after the unchanged allowed-root operations and before
the unchanged outside operations, then once after the outside operations. Thus
there are at most twelve AccessCheck calls. Both phases explicitly identify their
descriptors as `pre_action_memory`. If the bug removes `keep.txt`, the second phase
still uses the original descriptor; it must not be reported as a fresh SD query
on the now-missing object. The directory deletion operation on `keep-dir` remains
unchanged but its distinct SD is not independently diagnosed by these six queries.

After the existing impersonation guard restores the original identity, the
observer rereads the parent SD and, only if the target still exists, its SD.
Full byte equality is reported. Absence is reported as absence; it is neither an
unchanged-SD claim nor a fabricated readback. The original guard aborts if
RevertToSelf fails; this candidate does not change that lifecycle.

## Token facts and bounds

Each phase captures the actual token user/attributes, default owner, ordinary
SID-and-attribute set, restricting SID-and-attribute set, privileges, integrity
SID/attributes, mandatory policy, token type and impersonation level. Complete
sorted semantic collections are compared before/after in memory. No volatile
TokenStatistics timestamps, counters, structure padding or raw token identifier
is treated as a permission invariant.

The log reports counts, owner-equality booleans, exact expected capability-set
comparison, World/logon attributes, token type/level, integrity RID/attributes,
and the first eight privilege tuples with an explicit truncation flag. It does
not print user/logon SID bytes. SID parsing validates allocation bounds before
calling IsValidSid; returned collections are capped at 256 entries and each
allocation at 64 KiB. Privilege-set size and count are checked after AccessCheck.

Each observer emits at most 16 KiB, including fixed prefixes and truncation
markers. Errors are bounded to 256 characters. API errors, unavailable snapshots,
invalid lengths and budget exhaustion are `unknown` observations. AccessCheck
API failure and an API-success authorization denial are recorded separately.
No observer error substitutes for, skips or changes any original assertion.
The output has no PASS/qualification marker; completeness alone is not a safety
result. All token-query handles are owned and close before the original next
filesystem operation; descriptor storage is released with LocalFree.

AccessCheck evaluates a captured security descriptor. It does not reproduce path
resolution, an NTFS kernel trace, mandatory-label evaluation omitted from the
requested descriptor, handle-cache behavior or the filesystem driver's parent
fallback. A positive result cannot establish that a path operation is confined.
A before/after mismatch or incomplete observation prevents a causal attribution.

## Review and staging

A source preservation check must remove only the observer declarations/calls and
recover the entire original test file byte for byte. Production token/ACL/process
sources, the real-child regression, original matrix/LIST/open/disposition sources,
all workflow gates, manifests and locks remain at their pinned identities.

The candidate can be reviewed in two coherent source stages: the private owned
SD/token snapshot helper, then the private observer and the existing case's four
observation points. Each helper module is below 500 lines. Public product API is
unchanged. Formal formatting and static checks are recorded separately from the
still-pending Rust compilation and Windows execution. Publication and execution
require a later explicit source/identity review; neither is authorized by this
source-only protocol.

## Primary references

- [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [Restricted tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens)
- [SID attributes](https://learn.microsoft.com/en-us/windows/win32/secauthz/sid-attributes-in-an-access-token)
- [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)
- [File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
- [Filesystem SetInformation access-check example](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/irp-mj-set-information3)
- [SeAccessCheck](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/nf-wdm-seaccesscheck)

The filesystem example is a driver contract/example, not source evidence for the
specific Windows kernel branch exercised by the retained failures. SDK bindings
are pinned to the existing windows-sys 0.52 package; no dependency is added.
