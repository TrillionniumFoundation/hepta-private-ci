# Three parent-descriptor memory checks

This is an unexecuted, test-only observation of the existing production factory
token. It does not repair the filesystem sandbox. The original two tests,
assertions, actions, time limits, zero-retry commands and failure outcomes remain
unchanged. No CI workflow or consumer is changed by this source candidate.

## Fixed placement and three inputs

The original factory test already impersonates its production token and calls
the observer before its four outside operations. After that observer's original
six checks, this addition borrows the same `OpenThreadToken(TOKEN_QUERY)` handle.
It runs once in the `before` phase, with at most three additional `AccessCheck`
calls. Every call requests only `FILE_DELETE_CHILD` (64), with the original file
generic mapping. It does not create, duplicate, adjust or impersonate a token.

| Order | Parent descriptor held in private memory | Purpose |
| --- | --- | --- |
| 1 | Byte-for-byte copy of the retained pre-action descriptor | Original parent grant control |
| 2 | The same contents with one leading deny for a workspace restricting SID | Capability-deny discriminator |
| 3 | The same contents with one leading deny for the actual `TokenUser` | Ordinary-identity denial control |

Both new ACEs request only bit 64 and have zero inheritance flags. The selected
capability is the first sorted expected SID. The observer first requires the
actual restricting list to equal the original two capabilities and checks that
the selected SID occurs in neither the actual user nor any ordinary token group.
No logged role name is used to infer raw SID equality.

## Memory custody and exact comparisons

`MakeAbsoluteSD` copies the retained self-relative descriptor into owned, aligned
buffers. `InitializeAcl`, `AddAccessDeniedAceEx` and `AddAce` create the new DACL
in private memory. `SetSecurityDescriptorDacl` updates only that private absolute
descriptor; `MakeSelfRelativeSD` produces the independent query input. None of
these calls installs an ACL. There is no `SetSecurityInfo`, file open, child
process, permission adjustment, added wait or retry in the new module.

Before any of the three access checks, the observer verifies descriptor validity
and full byte equality of the original owner, group, represented SACL, revision
and control fields. It requires every original ACE to remain byte-identical and
in the same order after exactly one leading deny. It checks that deny's type,
flags, mask and complete SID. API serialization may change component offsets and
unused padding; those are not claimed to be byte-identical. The captured source
requests OWNER, GROUP and DACL, so preserving its represented SACL does not claim
to have captured every filesystem security policy or integrity label.

All buffers are aligned to `usize`, each at most 64 KiB. Absolute conversion has
five fixed output buffers; ACL parsing has at most 256 ACEs, and adding an ACE
requires fewer than 256 source entries. ACL byte sizes also fit their 16-bit
format. Every returned extent is checked before parsing. No retry is used for
changed size requirements. All absolute pointers retain their owners through
serialization; the three self-relative buffers live through all access checks.

After the queries, the same handle supplies another complete existing
`TokenFacts` snapshot. Exact collected raw facts, original source memory and all
three input buffers must still match. These are sequential comparisons of the
existing captured fields, not an atomic token-state lease or a claim to capture
every token information class. A change in a privilege-used bit is retained as
an unequal observation; it alone does not prove changed authorization.

## Output and interpretation

One separate `HEPTA_PARENT_DELETE_CHILD` JSON line has a hard 4096-byte cap,
including prefix and newline. The existing 15 observer records retain their
prefix and schema. Output contains only fixed roles, counts, typed API results
and equality facts; it contains no SID text or bytes, paths, ACL payloads or user
content. Completed access rows are retained if a later observation fails.
Serialization or size failure emits a fixed unknown record. API/allocation work
and output have bounded counts and sizes, not a new elapsed-time guarantee.

An API failure is distinct from a successful call reporting denied access. A
usable discriminator additionally needs the baseline to grant exactly 64, the
ordinary-user control to deny with zero granted access, all three APIs to succeed,
each allowed result to grant exactly 64 (each denial zero), and the memory/token
comparisons to hold. Otherwise the summary is `unknown`.
The capability row may grant or deny; neither outcome is converted into an
original test pass. No absence, truncation or missing row is a positive result.

A denied capability row would show an effective deny only for this descriptor,
token and requested access in `AccessCheck`. A granted row with valid controls
would show this one proposed trustee denial did not block that check. Neither
result establishes the kernel's file-deletion path or coverage of arbitrary host
parents. Any installed-ACL or production repair requires a separate review and
actual allowed/outside/protected I/O controls. The current native failures stay
open.

Removing `WRITE_RESTRICTED` is not part of this candidate. The documented factory
contract would then apply restricting-SID checks to reads as well. The original
factory test's successful outside read is a required compatibility control; no
modified-token result or general read-compatibility conclusion is claimed here.

Primary contracts: Microsoft [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck),
[MakeAbsoluteSD](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-makeabsolutesd),
[MakeSelfRelativeSD](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-makeselfrelativesd),
[AddAccessDeniedAceEx](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-addaccessdeniedaceex),
[AddAce](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-addace),
and [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken).
